"""BaseAgent – Template Method pattern.

`run()` is the fixed algorithm every LLM agent follows; subclasses only fill in the steps:
    retrieve context -> build prompt -> call LLM -> validate (schema + grounding) -> submit.
The result is NEVER used directly: it is saved as PENDING_REVIEW for a human checker.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.errors import GenerationError
from app.llm.client import LLMClient
from app.llm.structured import extract_json
from app.rag.context_builder import Context
from app.rag.retriever import Retriever
from app.services.approval_service import ApprovalService, SubmitResult

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
MAX_RETRIES = 3


class BaseAgent(ABC):
    artifact_type: str = ""
    name: str = "agent"
    guideline_categories: list[str] = []

    def __init__(self, llm: LLMClient, retriever: Retriever, approvals: ApprovalService):
        self.llm = llm
        self.retriever = retriever
        self.approvals = approvals
        self._prompt = ""

    # ---- the template method (do not override) ------------------------------------------
    def run(self, task) -> SubmitResult:
        self.prepare(task)
        context = self.retriever.get_context(
            self.build_query(task),
            agent_name=self.name,
            guideline_categories=self.guideline_categories,
            **self.filters(task),
        )
        self._prompt = self.build_prompt(task, context)
        raw = self.llm.generate(self._prompt)
        result = self.validate(raw, context)
        return self.approvals.submit(
            self.artifact_type,
            result,
            context,
            persist=lambda session: self.persist(session, result, task, context),
            created_by=getattr(task, "user_id", None),
            actor=self.name,
        )

    # ---- steps subclasses provide ---------------------------------------------------------
    def prepare(self, task) -> None:  # noqa: B027 - optional hook, intentionally empty
        """Optional hook before retrieval (e.g. entity extraction)."""

    def filters(self, task) -> dict:
        return {
            "market": getattr(task, "market", "SG"),
            "product": getattr(task, "product", "PAYMENTS"),
            "key_entities": getattr(task, "key_entities", []),
        }

    @abstractmethod
    def build_query(self, task) -> str: ...

    @abstractmethod
    def build_prompt(self, task, context: Context) -> str: ...

    @abstractmethod
    def validate(self, raw: str, context: Context): ...

    @abstractmethod
    def persist(self, session: Session, result, task, context: Context): ...

    # ---- shared helper: schema validation with retry (UT-05) -----------------------------
    def parse_json_model(self, raw: str, model: type[T]) -> T:
        """Strip text around the JSON, validate with Pydantic; on error retry (max 3 calls)."""
        last = ""
        for attempt in range(MAX_RETRIES + 1):  # first try + up to 3 retries
            try:
                return model.model_validate(json.loads(extract_json(raw)))
            except (ValueError, ValidationError) as exc:
                last = str(exc)
                log.warning("%s: invalid LLM output (retry %d/%d)", self.name, attempt, MAX_RETRIES)
                if attempt == MAX_RETRIES:
                    break
                raw = self.llm.generate(
                    f"{self._prompt}\n\n## PREVIOUS ATTEMPT WAS INVALID\nValidation error: "
                    f"{last[:600]}\nReturn ONLY valid JSON that matches the schema."
                )
        raise GenerationError(
            f"{self.name}: LLM output invalid after {MAX_RETRIES} retries: {last[:300]}"
        )
