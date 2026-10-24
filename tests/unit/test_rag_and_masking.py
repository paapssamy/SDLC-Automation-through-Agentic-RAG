"""UT-03, UT-04, UT-07 and IT-01 style checks for the knowledge base / RAG layer."""

from sqlalchemy import select

from app.db import models
from app.db.base import session_scope
from app.rag.embedding_service import DIMENSIONS, HashEmbedder, get_embedder
from app.rag.retriever import Retriever
from app.services.masking import mask_sensitive
from tests.conftest import add_document


def test_ut03_embedding_dimension(db):
    assert len(get_embedder().embed("pacs.008 credit transfer")) == 384 == DIMENSIONS
    assert len(HashEmbedder().embed("x")) == 384


def test_ut04_no_related_document_uses_baseline_fallback(db, kb):
    ctx = Retriever().get_context("zzzz qqqq unrelated llama grazing", agent_name="t")
    assert ctx.used_fallback is True
    assert any(s.is_baseline for s in ctx.sources)
    assert ctx.text.strip() != ""  # LLM never receives empty context (SR-03)


def test_related_query_does_not_use_fallback(db, kb):
    ctx = Retriever().get_context("pacs.008 message builder charge bearer", agent_name="t")
    assert ctx.used_fallback is False
    assert ctx.sources[0].service_name == "Pacs008MessageBuilder"
    assert ctx.sources[0].score >= 0.35


def test_retrieval_is_logged(db, kb):
    Retriever().get_context("sanctioned country list screening", agent_name="unit")
    with session_scope() as s:
        rows = s.scalars(select(models.RetrievalLog)).all()
    assert rows and all(r.agent_name == "unit" for r in rows)


def test_unapproved_documents_are_not_searched(db):
    add_document("Hidden", "sanctions screening list", status="PENDING_REVIEW")
    ctx = Retriever().get_context("sanctions screening list", agent_name="t")
    assert "Hidden" not in ctx.service_names


def test_it01_short_requirement_against_40_sections(db):
    for i in range(40):
        add_document(f"Section{i}", f"generic payment processing section number {i} topic{i}")
    ctx = Retriever().get_context("Add LEI", agent_name="t")
    assert ctx.sources, "related services returned with scores (fallback if low)"
    assert all(isinstance(s.score, float) for s in ctx.sources)
    assert len([s for s in ctx.sources if not s.is_baseline]) <= 5


def test_ut07_masking_of_account_numbers():
    r = mask_sensitive("Debit account 123456789012 or SG44ABCD12345678901234 contact a@b.com")
    assert "123456789012" not in r.text and "a@b.com" not in r.text
    assert r.count >= 3


def test_masking_applied_before_llm_call(db, mock_llm):
    mock_llm.generate("TASK: x\naccount 99887766554433")
    assert "99887766554433" not in mock_llm.calls[0]
    assert mock_llm.last_masked_count == 1
