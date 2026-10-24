"""Shared fixtures. Tests use a SEPARATE database (sdlc_rag_test), the mock LLM and the hash
embedder, so no test ever calls a real LLM or downloads a model."""

from __future__ import annotations

import os

os.environ["EMBEDDING_MODEL"] = "hash"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["ADO_MODE"] = "mock"
os.environ["CONFLUENCE_MODE"] = "mock"
os.environ["TEST_RUNNER"] = "mock"

from app.config import get_settings, reset_settings  # noqa: E402

_base_url = get_settings().database_url
TEST_DB = "sdlc_rag_test"
TEST_URL = _base_url.rsplit("/", 1)[0] + "/" + TEST_DB
os.environ["DATABASE_URL"] = TEST_URL
reset_settings()

import hashlib  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.db import models  # noqa: E402
from app.db.base import Base, session_scope, set_engine  # noqa: E402
from app.db.init_db import create_schema, seed  # noqa: E402
from app.llm.mock_client import MockLLMClient  # noqa: E402
from app.rag.embedding_service import HashEmbedder, set_embedder  # noqa: E402
from app.services.auth import CurrentUser  # noqa: E402


def _ensure_test_database() -> None:
    admin_url = _base_url.rsplit("/", 1)[0] + "/postgres"
    eng = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        exists = c.execute(
            text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": TEST_DB}
        ).first()
        if not exists:
            c.execute(text(f"CREATE DATABASE {TEST_DB}"))
    eng.dispose()


@pytest.fixture(scope="session")
def engine():
    _ensure_test_database()
    eng = create_engine(TEST_URL, future=True)
    set_engine(eng)
    set_embedder(HashEmbedder())
    create_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine, tmp_path, monkeypatch):
    """Empty, seeded database for each test + isolated workspace folder."""
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    seed(engine)
    ws = tmp_path / "workspace"
    ws.mkdir()
    from app import config

    s = get_settings()
    patched = type(s)(**{**s.__dict__, "workspace_dir": ws})
    monkeypatch.setattr(config, "_settings", patched)
    yield engine


def make_user(role: str) -> CurrentUser:
    from sqlalchemy import select

    with session_scope() as s:
        u = s.scalars(select(models.User).where(models.User.role == role)).first()
        return CurrentUser(u.user_id, u.username, u.full_name, u.role)


@pytest.fixture()
def users(db):
    return {
        r: make_user(r)
        for r in ("BUSINESS_ANALYST", "TECHNICAL_LEAD", "DEVELOPER", "QA_LEAD", "ADMIN")
    }


def add_document(
    name: str, content: str, status: str = "APPROVED", market="SG", product="PAYMENTS"
) -> int:
    emb = HashEmbedder().embed(f"{name} {content}")
    with session_scope() as s:
        d = models.ServiceDocument(
            market=market,
            product=product,
            service_name=name,
            content=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            embedding=emb,
            status=status,
        )
        s.add(d)
        s.flush()
        return d.doc_id


@pytest.fixture()
def kb(db):
    """Small knowledge base of approved service documents."""
    docs = {
        "Pacs008MessageBuilder": "Builds ISO 20022 pacs.008 credit transfer messages with group "
        "header settlement amount charge bearer debtor creditor",
        "PaymentValidator": "Validates mandatory fields amount limits and charges option OUR SHA BEN",
        "SanctionsScreeningService": "Screens creditor country against sanctioned country list",
        "CutOffTimeService": "Cut-off time for SGD high-value payments next business day",
        "ChargesCalculator": "Calculates charges and supports options OUR SHA BEN",
        "MT103Mapper": "Maps payment to SWIFT MT103 message field 71A charges",
    }
    return {n: add_document(n, c) for n, c in docs.items()}


@pytest.fixture()
def mock_llm():
    return MockLLMClient()


@pytest.fixture()
def java_copy(tmp_path):
    """Copy of the sample Java app that tests may modify safely."""
    src = get_settings().sample_data_dir / "java-payments-app"
    dst = tmp_path / "java"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture(autouse=True)
def _cleanup_tmp():
    yield
    tempfile.tempdir = None
    _ = Path
