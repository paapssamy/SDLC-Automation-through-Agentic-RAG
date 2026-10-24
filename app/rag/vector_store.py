"""VectorStore interface (Strategy) and its PostgreSQL/pgvector implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import text

from app.db.base import session_scope

SEARCHABLE_STATUSES = ("APPROVED", "PUBLISHED")


@dataclass
class SearchHit:
    doc_id: int
    service_name: str
    content: str
    version: int
    market: str
    product: str
    score: float  # cosine similarity 0..1 (1 = identical)


class VectorStore(ABC):
    @abstractmethod
    def search(
        self, embedding: list[float], market: str, product: str, limit: int
    ) -> list[SearchHit]: ...


def to_pg_vector(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


class PgVectorStore(VectorStore):
    """One SQL query: cosine distance (HNSW index) with market/product filters."""

    SQL = text(
        """
        SELECT doc_id, service_name, content, current_version, market, product,
               1 - (embedding <=> CAST(:q AS vector)) AS score
        FROM   service_document
        WHERE  market = :market AND product = :product
          AND  status IN ('APPROVED', 'PUBLISHED')
          AND  embedding IS NOT NULL
        ORDER  BY embedding <=> CAST(:q AS vector)
        LIMIT  :limit
        """
    )

    def search(self, embedding, market, product, limit=10):
        with session_scope() as s:
            rows = s.execute(
                self.SQL,
                {
                    "q": to_pg_vector(embedding),
                    "market": market,
                    "product": product,
                    "limit": limit,
                },
            ).all()
        return [
            SearchHit(
                r.doc_id,
                r.service_name,
                r.content,
                r.current_version,
                r.market,
                r.product,
                float(r.score),
            )
            for r in rows
        ]
