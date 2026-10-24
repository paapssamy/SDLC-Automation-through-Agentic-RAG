"""Context builder: text for the prompt + source references + similarity scores."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select

from app.db import models
from app.db.base import session_scope


@dataclass
class Source:
    service_name: str
    score: float
    version: int = 1
    doc_id: int | None = None
    is_baseline: bool = False
    content: str = ""

    def as_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "service_name": self.service_name,
            "version": self.version,
            "score": round(self.score, 4),
            "baseline": self.is_baseline,
        }


@dataclass
class Context:
    """Everything an agent needs: prompt text, sources (shown to the reviewer), fallback flag."""

    query: str = ""
    sources: list[Source] = field(default_factory=list)
    guidelines: str = ""
    used_fallback: bool = False
    log_ids: list[int] = field(default_factory=list)

    @property
    def text(self) -> str:
        lines = []
        for s in self.sources:
            snippet = re.sub(r"\s+", " ", s.content)[:700]
            lines.append(f"- {s.service_name} (score {s.score:.2f}): {snippet}")
        return "\n".join(lines)

    @property
    def service_names(self) -> list[str]:
        return [s.service_name for s in self.sources if not s.is_baseline]

    @property
    def source_refs(self) -> list[dict]:
        return [s.as_dict() for s in self.sources]


def load_guidelines(categories: list[str] | None) -> str:
    """Organisation guidelines from the `guideline` table (only the categories requested)."""
    if not categories:
        return ""
    with session_scope() as s:
        rows = s.scalars(
            select(models.Guideline)
            .where(models.Guideline.category.in_(categories))
            .order_by(models.Guideline.guideline_id)
        ).all()
    return "\n\n".join(f"### {g.title}\n{g.content}" for g in rows)
