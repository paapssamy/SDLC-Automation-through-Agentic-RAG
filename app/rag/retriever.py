"""Retriever: semantic search, re-rank, threshold + baseline fallback, retrieval log."""

from __future__ import annotations

import logging
import re

from app.config import Settings, get_settings
from app.db import models
from app.db.base import session_scope
from app.rag.context_builder import Context, Source, load_guidelines
from app.rag.embedding_service import EmbeddingService, get_embedder
from app.rag.vector_store import PgVectorStore, SearchHit, VectorStore

log = logging.getLogger(__name__)


class Retriever:
    def __init__(
        self,
        store: VectorStore | None = None,
        embedder: EmbeddingService | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.store = store or PgVectorStore()
        self._embedder = embedder

    @property
    def embedder(self) -> EmbeddingService:
        return self._embedder or get_embedder()

    # -- public ---------------------------------------------------------------------------
    def get_context(
        self,
        query: str,
        market: str = "SG",
        product: str = "PAYMENTS",
        key_entities: list[str] | None = None,
        agent_name: str = "agent",
        guideline_categories: list[str] | None = None,
    ) -> Context:
        s = self.settings
        hits = self.store.search(self.embedder.embed(query), market, product, s.rag_top_k)
        best = max((h.score for h in hits), default=0.0)
        ranked = self._rerank(hits, market, product, key_entities or [])[: s.rag_keep_top]

        used_fallback = best < s.rag_threshold
        baselines = self._baseline_sources() if used_fallback else []
        if used_fallback:  # keep the prompt small: baseline specs + only the 2 closest hits
            ranked = ranked[: max(2, s.rag_keep_top - len(baselines))]
        sources = baselines + [
            Source(h.service_name, h.score, h.version, h.doc_id, False, h.content) for h in ranked
        ]
        if used_fallback:
            log.info("RAG fallback used: best score %.3f < %.2f", best, s.rag_threshold)

        ctx = Context(
            query=query,
            sources=sources,
            used_fallback=used_fallback,
            guidelines=load_guidelines(guideline_categories),
        )
        ctx.log_ids = self._log(ctx, agent_name)
        return ctx

    # -- internals ------------------------------------------------------------------------
    def _rerank(
        self, hits: list[SearchHit], market: str, product: str, entities: list[str]
    ) -> list[SearchHit]:
        """Order by cosine score + small boosts (exact market/product, keyword overlap)."""
        ent_words = {w for e in entities for w in re.findall(r"[a-z0-9.]+", e.lower())}

        def final(h: SearchHit) -> float:
            boost = 0.02 if (h.market == market and h.product == product) else 0.0
            if ent_words:
                words = set(re.findall(r"[a-z0-9.]+", (h.service_name + " " + h.content).lower()))
                boost += 0.05 * len(ent_words & words) / len(ent_words)
            return h.score + boost

        return sorted(hits, key=final, reverse=True)

    def _baseline_sources(self) -> list[Source]:
        """Baseline core product specifications used when the knowledge base has no good match."""
        out = []
        for f in sorted((self.settings.sample_data_dir / "baseline_specs").glob("*.md")):
            out.append(Source(f"BASELINE-{f.stem}", 0.0, 1, None, True, f.read_text("utf-8")))
        return out

    def _log(self, ctx: Context, agent_name: str) -> list[int]:
        ids = []
        with session_scope() as s:
            for src in ctx.sources:
                row = models.RetrievalLog(
                    doc_id=src.doc_id,
                    agent_name=agent_name,
                    query_text=ctx.query[:2000],
                    similarity_score=src.score,
                    used_fallback=ctx.used_fallback,
                )
                s.add(row)
                s.flush()
                ids.append(row.log_id)
        return ids
