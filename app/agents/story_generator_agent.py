"""Agent 3 – Story Generator Agent (module 3.4).

Works only from an APPROVED impact analysis (the gate is enforced by the orchestrator).
Output: title, "As a / I want / So that" description, Given/When/Then criteria and an INVEST check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agents.base_agent import BaseAgent
from app.agents.schemas import StoryDraft
from app.db import models
from app.db.base import session_scope
from app.prompts import render
from app.rag.context_builder import Context


@dataclass
class StoryTask:
    user_id: int | None
    analysis_id: int
    feedback: str = ""
    artifact_id: int | None = None
    market: str = "SG"
    product: str = "PAYMENTS"
    requirement: str = ""
    analysis_text: str = ""
    key_entities: list[str] = field(default_factory=list)


class StoryGeneratorAgent(BaseAgent):
    artifact_type = "USER_STORY"
    name = "StoryGeneratorAgent"
    guideline_categories = ["user_story_template", "invest_rules"]

    def prepare(self, task: StoryTask) -> None:
        with session_scope() as s:
            a = s.get(models.ImpactAnalysis, task.analysis_id)
            req = s.get(models.BusinessRequirement, a.req_id)
            task.requirement, task.market, task.product = req.req_text, req.market, req.product
            task.key_entities = list(req.key_entities or [])
            task.analysis_text = (
                f"Affected services: {', '.join(a.affected_services)}\n"
                f"Dependencies: {', '.join(a.dependencies)}\nComplexity: {a.complexity}; "
                f"Risk: {a.risk}; Effort: {a.effort_days} days\nTesting: {a.testing_strategy}"
            )

    def build_query(self, task: StoryTask) -> str:
        return f"{task.requirement} {task.analysis_text}"

    def build_prompt(self, task: StoryTask, context: Context) -> str:
        p = render(
            "user_story",
            requirement=task.requirement,
            analysis=task.analysis_text,
            context=context.text,
            guidelines=context.guidelines,
        )
        if task.feedback:
            p += f"\n## REVIEWER FEEDBACK (address this)\n{task.feedback}\n"
        return p

    def validate(self, raw: str, context: Context) -> StoryDraft:
        return self.parse_json_model(raw, StoryDraft)

    def persist(self, session: Session, result: StoryDraft, task: StoryTask, context: Context):
        invest = {k: v.model_dump(by_alias=True) for k, v in result.invest_check.items()}
        values = dict(
            title=result.title[:250],
            description=result.description,
            acceptance_criteria=result.acceptance_criteria,
            invest_check=invest,
        )
        if task.artifact_id:
            row = session.get(models.UserStory, task.artifact_id)
            self.approvals.reopen(session, row, self.name, task.feedback)
            for k, v in values.items():
                setattr(row, k, v)
            return row
        row = models.UserStory(analysis_id=task.analysis_id, created_by=task.user_id, **values)
        session.add(row)
        return row
