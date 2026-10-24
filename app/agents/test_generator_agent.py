"""Agent 5 – Test Generator Agent (module 3.6).

Generates test scenarios from an APPROVED user story with a coverage checklist (positive,
negative, boundary, integration). Each scenario carries phase, type, priority, automated flag,
steps and expected result. The QA Lead reviews (and may edit) them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agents.base_agent import BaseAgent
from app.agents.schemas import ScenarioDraft, ScenarioList
from app.db import models
from app.db.base import session_scope
from app.prompts import render
from app.rag.context_builder import Context


@dataclass
class TestGenTask:
    __test__ = False
    user_id: int | None
    story_id: int
    market: str = "SG"
    product: str = "PAYMENTS"
    story_text: str = ""
    key_entities: list[str] = field(default_factory=list)


class TestGeneratorAgent(BaseAgent):
    __test__ = False
    artifact_type = "TEST_SCENARIO"
    name = "TestGeneratorAgent"
    guideline_categories = ["test_case_template"]

    def prepare(self, task: TestGenTask) -> None:
        with session_scope() as s:
            st = s.get(models.UserStory, task.story_id)
            an = s.get(models.ImpactAnalysis, st.analysis_id)
            req = s.get(models.BusinessRequirement, an.req_id)
            task.market, task.product = req.market, req.product
            task.key_entities = list(req.key_entities or [])
            task.story_text = f"{st.title}\n{st.description}\nAcceptance criteria:\n" + "\n".join(
                f"- {c}" for c in st.acceptance_criteria
            )

    def build_query(self, task: TestGenTask) -> str:
        return task.story_text

    def build_prompt(self, task: TestGenTask, context: Context) -> str:
        return render(
            "test_cases", story=task.story_text, context=context.text, guidelines=context.guidelines
        )

    def validate(self, raw: str, context: Context) -> list[ScenarioDraft]:
        return self.parse_json_model(raw, ScenarioList).scenarios

    def persist(
        self, session: Session, result: list[ScenarioDraft], task: TestGenTask, context: Context
    ):
        rows = []
        for sc in result:
            row = models.TestScenario(
                story_id=task.story_id,
                title=sc.title[:250],
                phase=sc.phase,
                test_type=sc.test_type,
                priority=sc.priority,
                automated=sc.automated,
                steps=sc.steps,
                expected_result=sc.expected_result,
                created_by=task.user_id,
            )
            session.add(row)
            rows.append(row)
        return rows
