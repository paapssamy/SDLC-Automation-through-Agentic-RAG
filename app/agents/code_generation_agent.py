"""Agent 4 – Code Generation Agent (module 3.5, the strictest gate).

Works only from an APPROVED user story. The LLM returns full new file contents; we build a
file-wise unified diff with difflib and validate it (file exists, diff not empty, Java parses
with javalang). Nothing reaches the repository until a Developer approves AND adopts it.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field

import javalang
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.ado_repos_connector import AdoReposConnector
from app.agents.base_agent import MAX_RETRIES, BaseAgent
from app.agents.schemas import CodeFiles
from app.db import models
from app.db.base import session_scope
from app.errors import GenerationError, ValidationFailedError
from app.prompts import render
from app.rag.context_builder import Context

log = logging.getLogger(__name__)


@dataclass
class CodeTask:
    user_id: int | None
    story_id: int
    feedback: str = ""
    market: str = "SG"
    product: str = "PAYMENTS"
    story_text: str = ""
    originals: dict[str, str] = field(default_factory=dict)
    key_entities: list[str] = field(default_factory=list)


@dataclass
class ChangeDraft:
    path: str
    original: str
    new: str
    diff: str


def make_unified_diff(path: str, old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


class CodeGenerationAgent(BaseAgent):
    artifact_type = "CODE_CHANGE"
    name = "CodeGenerationAgent"
    guideline_categories = ["java_coding_conventions"]

    def __init__(self, llm, retriever, approvals, repos: AdoReposConnector):
        super().__init__(llm, retriever, approvals)
        self.repos = repos

    def prepare(self, task: CodeTask) -> None:
        with session_scope() as s:
            st = s.get(models.UserStory, task.story_id)
            an = s.get(models.ImpactAnalysis, st.analysis_id)
            req = s.get(models.BusinessRequirement, an.req_id)
            task.market, task.product = req.market, req.product
            task.key_entities = list(req.key_entities or [])
            task.story_text = f"{st.title}\n{st.description}\nAcceptance criteria:\n" + "\n".join(
                f"- {c}" for c in st.acceptance_criteria
            )
            services = list(an.affected_services)
        task.originals = self.repos.fetch_class_files(services)
        if not task.originals:
            raise GenerationError("No source files found for the affected services")

    def build_query(self, task: CodeTask) -> str:
        return task.story_text

    def build_prompt(self, task: CodeTask, context: Context) -> str:
        files = "\n".join(
            f"=== FILE: {p} ===\n{c}\n=== END FILE ===" for p, c in task.originals.items()
        )
        p = render(
            "code_generation",
            story=task.story_text,
            files=files,
            context=context.text,
            guidelines=context.guidelines,
        )
        if task.feedback:
            p += f"\n## REVIEWER FEEDBACK (address this)\n{task.feedback}\n"
        self._task = task
        return p

    def validate(self, raw: str, context: Context) -> list[ChangeDraft]:
        """Schema + file exists + non-empty diff + Java syntax; retry with the error appended."""
        task = self._task
        last = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                files = self.parse_json_model(raw, CodeFiles)
                return self._check(files, task)
            except ValidationFailedError as exc:
                last = str(exc)
                log.warning("code validation failed (attempt %d): %s", attempt, last)
                if attempt < MAX_RETRIES:
                    raw = self.llm.generate(
                        f"{self._prompt}\n\n## PREVIOUS ATTEMPT WAS INVALID\n{last}\n"
                        "Return the complete corrected JSON."
                    )
        raise GenerationError(f"Generated code invalid after {MAX_RETRIES} attempts: {last}")

    @staticmethod
    def _check(files: CodeFiles, task: CodeTask) -> list[ChangeDraft]:
        drafts = []
        for f in files.files:
            if f.path not in task.originals:
                raise ValidationFailedError(f"File {f.path} does not exist in the repository")
            diff = make_unified_diff(f.path, task.originals[f.path], f.content)
            if not diff.strip():
                raise ValidationFailedError(f"File {f.path} has no changes (empty diff)")
            try:
                javalang.parse.parse(f.content)
            except Exception as exc:
                raise ValidationFailedError(f"File {f.path} is not valid Java: {exc}") from exc
            drafts.append(ChangeDraft(f.path, task.originals[f.path], f.content, diff))
        return drafts

    def persist(
        self, session: Session, result: list[ChangeDraft], task: CodeTask, context: Context
    ):
        rows = []
        for d in result:
            row = session.scalars(
                select(models.CodeChange).where(
                    models.CodeChange.story_id == task.story_id,
                    models.CodeChange.file_path == d.path,
                    models.CodeChange.status == "CHANGES_REQUESTED",
                )
            ).first()
            if row:
                self.approvals.reopen(session, row, self.name, task.feedback)
                row.original_content, row.new_content, row.unified_diff = d.original, d.new, d.diff
            else:
                row = models.CodeChange(
                    story_id=task.story_id,
                    file_path=d.path,
                    original_content=d.original,
                    new_content=d.new,
                    unified_diff=d.diff,
                    created_by=task.user_id,
                )
                session.add(row)
            rows.append(row)
        return rows
