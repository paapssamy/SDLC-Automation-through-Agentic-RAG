"""Agent 8 – Incremental Doc Updater (module 3.8, living documentation).

After a release it finds the affected documentation sections (class-name match first, then
vector search), rewrites ONLY those sections, skips unchanged text (content_hash) and saves
new text + new embedding + a document_version row in ONE transaction. The old text stays in
document_version, so nothing is ever overwritten. The Technical Lead then confirms the update
(DOC_UPDATE approval) before it is published to Confluence.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base_agent import BaseAgent
from app.db import models
from app.db.base import session_scope
from app.errors import GenerationError
from app.prompts import render
from app.rag.context_builder import Context
from app.rag.embedding_service import get_embedder
from app.services.approval_service import SubmitResult

log = logging.getLogger(__name__)


class UnchangedError(Exception):
    """The rewritten section is identical to the stored one (content_hash equal)."""


@dataclass
class DocUpdateTask:
    user_id: int | None
    doc_id: int
    release_id: int
    service_name: str
    current_content: str
    changes_text: str
    market: str = "SG"
    product: str = "PAYMENTS"
    key_entities: tuple = ()


class IncrementalDocUpdater(BaseAgent):
    artifact_type = "DOC_UPDATE"
    name = "IncrementalDocUpdater"
    guideline_categories = ["documentation_style"]

    # -- locating affected sections ---------------------------------------------------------
    def find_affected(self, release_id: int) -> dict[int, list[models.ReleaseChange]]:
        """doc_id -> release changes that touch it."""
        affected: dict[int, list[models.ReleaseChange]] = {}
        with session_scope() as s:
            changes = list(
                s.scalars(
                    select(models.ReleaseChange).where(
                        models.ReleaseChange.release_id == release_id
                    )
                )
            )
            docs = list(
                s.scalars(
                    select(models.ServiceDocument).where(
                        models.ServiceDocument.status.in_(("APPROVED", "PUBLISHED"))
                    )
                )
            )
            for ch in changes:
                cls = ch.file_path.rsplit("/", 1)[-1].removesuffix(".java")
                hits = [
                    d.doc_id
                    for d in docs
                    if d.service_name == cls
                    or f"class {cls}" in d.content
                    or f"interface {cls}" in d.content
                ]
                if not hits and docs:  # fall back to semantic search on the diff text
                    hits = self._vector_match(ch.code_diff or cls, docs)
                for doc_id in hits:
                    affected.setdefault(doc_id, []).append(ch)
            for lst in affected.values():  # detach for use outside the session
                for ch in lst:
                    s.expunge(ch)
        return affected

    def _vector_match(self, text: str, docs: list[models.ServiceDocument]) -> list[int]:
        hits = self.retriever.store.search(
            self.retriever.embedder.embed(text), docs[0].market, docs[0].product, 1
        )
        thr = self.retriever.settings.rag_threshold
        return [h.doc_id for h in hits if h.score >= thr]

    # -- orchestration of one release ----------------------------------------------------------
    def update_release(self, release_id: int, user_id: int | None = None) -> dict:
        affected = self.find_affected(release_id)
        updated, skipped = [], []
        for doc_id, changes in affected.items():
            with session_scope() as s:
                d = s.get(models.ServiceDocument, doc_id)
                task = DocUpdateTask(
                    user_id,
                    doc_id,
                    release_id,
                    d.service_name,
                    d.content,
                    "\n".join(f"File: {c.file_path}\n{c.code_diff}" for c in changes),
                    d.market,
                    d.product,
                )
            try:
                res = self.run(task)
                updated.append(res.id)
            except UnchangedError:
                skipped.append(doc_id)
        return {"updated": updated, "skipped": skipped, "affected": list(affected)}

    # -- template steps ---------------------------------------------------------------------------
    def build_query(self, task: DocUpdateTask) -> str:
        return f"{task.service_name} {task.changes_text}"[:1500]

    def build_prompt(self, task: DocUpdateTask, context: Context) -> str:
        self._task = task
        return render(
            "doc_update",
            service_name=task.service_name,
            current_content=task.current_content,
            changes=task.changes_text,
        )

    def validate(self, raw: str, context: Context) -> str:
        text = raw.strip()
        if len(text) < 40:
            raise GenerationError("Updated documentation text is too short")
        if (
            hashlib.sha256(text.encode()).hexdigest()
            == hashlib.sha256(self._task.current_content.strip().encode()).hexdigest()
        ):
            raise UnchangedError()
        return text

    def persist(self, session: Session, result: str, task: DocUpdateTask, context: Context):
        """New text + new embedding + document_version row – same transaction as the approval."""
        doc = session.get(models.ServiceDocument, task.doc_id)
        if not session.scalars(
            select(models.DocumentVersion).where(models.DocumentVersion.doc_id == doc.doc_id)
        ).first():
            session.add(
                models.DocumentVersion(
                    doc_id=doc.doc_id,
                    release_id=None,
                    version_no=doc.current_version,
                    content=doc.content,
                    change_summary="Baseline before release updates",
                )
            )
        doc.current_version += 1
        doc.content = result
        doc.content_hash = hashlib.sha256(result.encode()).hexdigest()
        doc.embedding = get_embedder().embed(f"{doc.service_name}\n{result}")
        session.add(
            models.DocumentVersion(
                doc_id=doc.doc_id,
                release_id=task.release_id,
                version_no=doc.current_version,
                content=result,
                change_summary=f"Updated for release #{task.release_id}",
            )
        )
        return doc


def run_one(updater: IncrementalDocUpdater, task: DocUpdateTask) -> SubmitResult:
    """Convenience wrapper used by tests."""
    return updater.run(task)
