"""Agent 2 – Impact Analysis Agent (module 3.3).

Steps: extract key entities (LLM) -> retrieve related services (RAG) -> generate an
ImpactReport (JSON, Pydantic-validated with retry) -> grounding check (NFR-01): services that
were not in the retrieved documents are moved to `unknown_services` and shown in red.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.agents.base_agent import BaseAgent
from app.agents.schemas import Entities, ImpactReport
from app.db import models
from app.db.base import session_scope
from app.prompts import render
from app.rag.context_builder import Context

log = logging.getLogger(__name__)


@dataclass
class ImpactTask:
    user_id: int | None
    req_id: int
    requirement: str
    market: str = "SG"
    product: str = "PAYMENTS"
    feedback: str = ""
    artifact_id: int | None = None  # set when regenerating after CHANGES_REQUESTED
    key_entities: list[str] = field(default_factory=list)


@dataclass
class ImpactResult:
    report: ImpactReport
    unknown_services: list[str]


class ImpactAnalysisAgent(BaseAgent):
    artifact_type = "IMPACT_ANALYSIS"
    name = "ImpactAnalysisAgent"
    guideline_categories = ["documentation_style"]

    def prepare(self, task: ImpactTask) -> None:
        """Step 1: key entities from the requirement text."""
        self._prompt = render("extract_entities", requirement=task.requirement)
        raw = self.llm.generate(self._prompt)
        try:
            task.key_entities = self.parse_json_model(raw, Entities).entities
        except Exception:  # entity extraction is helpful, not essential
            log.warning("entity extraction failed; continuing without entities")
            task.key_entities = []
        with session_scope() as s:
            req = s.get(models.BusinessRequirement, task.req_id)
            if req is not None:
                req.key_entities = task.key_entities

    def build_query(self, task: ImpactTask) -> str:
        return f"{task.requirement} {' '.join(task.key_entities)}"

    def build_prompt(self, task: ImpactTask, context: Context) -> str:
        prompt = render(
            "impact_report",
            requirement=task.requirement,
            entities=", ".join(task.key_entities) or "(none)",
            context=context.text,
            guidelines=context.guidelines,
        )
        if task.feedback:
            prompt += f"\n## REVIEWER FEEDBACK (address this)\n{task.feedback}\n"
        return prompt

    def validate(self, raw: str, context: Context) -> ImpactResult:
        report = self.parse_json_model(raw, ImpactReport)
        known = {n.lower(): n for n in context.service_names}
        grounded, unknown = [], []
        for svc in report.affected_services:
            (grounded if svc.lower() in known else unknown).append(known.get(svc.lower(), svc))
        if unknown:
            log.warning(
                "Grounding check: %d service(s) not in retrieved docs: %s", len(unknown), unknown
            )
        report.affected_services = list(dict.fromkeys(grounded))
        return ImpactResult(report, list(dict.fromkeys(unknown)))

    def persist(self, session: Session, result: ImpactResult, task: ImpactTask, context: Context):
        r = result.report
        values = dict(
            affected_services=r.affected_services,
            dependencies=r.dependencies,
            complexity=r.complexity,
            risk=r.risk,
            effort_days=round(r.effort_days, 1),
            testing_strategy=r.testing_strategy,
            unknown_services=result.unknown_services,
        )
        if task.artifact_id:
            row = session.get(models.ImpactAnalysis, task.artifact_id)
            self.approvals.reopen(session, row, self.name, task.feedback)
            for k, v in values.items():
                setattr(row, k, v)
        else:
            row = models.ImpactAnalysis(req_id=task.req_id, created_by=task.user_id, **values)
            session.add(row)
            session.flush()
        if context.log_ids:
            session.execute(
                update(models.RetrievalLog)
                .where(models.RetrievalLog.log_id.in_(context.log_ids))
                .values(analysis_id=row.analysis_id)
            )
        return row
