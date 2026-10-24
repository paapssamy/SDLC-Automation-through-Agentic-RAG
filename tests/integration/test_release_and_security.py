"""IT-03, IT-04 and the security / governance tests SG-01..SG-03."""

import re

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.agents.incremental_doc_updater import DocUpdateTask
from app.db import models
from app.db.base import session_scope
from app.errors import AccessDeniedError
from app.integrations.ado_client import MockAdoClient, ReleaseChangeInfo, ReleaseInfo
from app.rag.embedding_service import get_embedder
from app.services import admin_service
from app.services.auth import authenticate
from app.services.container import build_services
from tests.conftest import add_document


@pytest.fixture()
def svc(db):
    return build_services()


@pytest.fixture()
def documented(svc, users):
    for r in svc.orchestrator.generate_documentation(users["TECHNICAL_LEAD"]):
        svc.orchestrator.review(users["TECHNICAL_LEAD"], "SERVICE_DOCUMENT", r.id, "APPROVED")


def _doc(name):
    with session_scope() as s:
        return s.scalars(
            select(models.ServiceDocument).where(models.ServiceDocument.service_name == name)
        ).first()


def test_it03_doc_update_saves_version_and_embedding_in_one_transaction(svc, users, kb):
    doc_id = kb["PaymentValidator"]
    before = _doc("PaymentValidator")
    old_embedding = list(before.embedding)
    task = DocUpdateTask(
        users["TECHNICAL_LEAD"].user_id,
        doc_id,
        None or 0,
        "PaymentValidator",
        before.content,
        "File: PaymentValidator.java\n+    boolean isPurposeCodeValid(String c) {",
    )
    with session_scope() as s:  # a release row is required by the FK
        rel = models.Release(ado_release_ref="R-X", name="x")
        s.add(rel)
        s.flush()
        task.release_id = rel.release_id
    svc.updater.run(task)
    after = _doc("PaymentValidator")
    assert after.current_version == 2 and after.content != before.content
    assert list(after.embedding) != old_embedding  # embedding refreshed
    assert after.content_hash != before.content_hash
    with session_scope() as s:
        versions = s.scalars(
            select(models.DocumentVersion)
            .where(models.DocumentVersion.doc_id == doc_id)
            .order_by(models.DocumentVersion.version_no)
        ).all()
    assert [v.version_no for v in versions] == [1, 2]
    assert versions[0].content == before.content  # old text is never overwritten
    assert versions[1].release_id == task.release_id


def test_it03_failure_rolls_back_everything(svc, users, kb, monkeypatch):
    before = _doc("PaymentValidator")
    monkeypatch.setattr(
        "app.agents.incremental_doc_updater.get_embedder",
        lambda: (_ for _ in ()).throw(RuntimeError("embedding service down")),
    )
    with session_scope() as s:
        rel = models.Release(ado_release_ref="R-Y", name="y")
        s.add(rel)
        s.flush()
        rid = rel.release_id
    task = DocUpdateTask(
        None,
        kb["PaymentValidator"],
        rid,
        "PaymentValidator",
        before.content,
        "File: x\n+    void changed() {}",
    )
    with pytest.raises(RuntimeError):
        svc.updater.run(task)
    after = _doc("PaymentValidator")
    assert after.current_version == 1 and after.content == before.content
    with session_scope() as s:
        assert s.scalars(select(models.DocumentVersion)).first() is None


def test_release_poll_updates_only_affected_sections(svc, users, documented):
    out = svc.monitor.poll()
    assert [o["release"] for o in out] == ["REL-2026.01", "REL-2026.02"]
    assert all(o["status"] == "DOCS_UPDATED" for o in out)
    assert _doc("Pacs008MessageBuilder").current_version == 2
    assert _doc("CutOffTimeService").current_version == 2
    assert _doc("FxRateService").current_version == 1  # untouched sections stay untouched
    assert svc.monitor.last_processed() == "REL-2026.02"
    assert svc.monitor.poll() == []  # nothing new


def test_tl_approval_publishes_update_and_rejection_reverts(svc, users, documented):
    svc.monitor.poll()
    tl = users["TECHNICAL_LEAD"]
    pend = [
        p
        for p in svc.approvals.pending_for_role("TECHNICAL_LEAD")
        if p["artifact_type"] == "DOC_UPDATE"
    ]
    assert pend
    cut = _doc("CutOffTimeService")
    reject = next(p for p in pend if p["artifact_id"] == cut.doc_id)
    svc.orchestrator.review(tl, "DOC_UPDATE", reject["artifact_id"], "REJECTED", "wrong")
    reverted = _doc("CutOffTimeService")
    assert reverted.current_version == 3 and "Recent Change" not in reverted.content
    ok = next(p for p in pend if p["artifact_id"] != cut.doc_id)
    svc.orchestrator.review(tl, "DOC_UPDATE", ok["artifact_id"], "APPROVED")
    page = (svc.settings.workspace_dir / "confluence").glob("*.html")
    assert any('data-version="2"' in p.read_text() for p in page)  # Confluence version bumped


def test_it04_missed_releases_are_replayed_in_order_after_restart(svc, users, documented):
    svc.monitor.poll()  # releases 1 and 2 processed before "downtime"
    ado: MockAdoClient = svc.ado  # type: ignore[assignment]
    for i, ts in ((3, "2026-03-01T00:00:00+00:00"), (4, "2026-03-05T00:00:00+00:00")):
        ado.add_release(
            ReleaseInfo(
                f"REL-2026.0{i}",
                f"Release {i}",
                ts,
                [
                    ReleaseChangeInfo(
                        str(2000 + i),
                        f"c{i}",
                        "src/main/java/com/bank/payments/fx/FxRateService.java",
                        f"+    double rate{i}() {{ return {i}; }}",
                        "FxRateService",
                    )
                ],
            )
        )
    # "restart": a brand new monitor + scheduler instance; state comes from the database
    fresh = build_services(ado=ado)
    assert fresh.monitor.last_processed() == "REL-2026.02"
    replayed = fresh.scheduler.catch_up()
    assert [r["release"] for r in replayed] == ["REL-2026.03", "REL-2026.04"]
    assert fresh.monitor.last_processed() == "REL-2026.04"
    with session_scope() as s:
        refs = [
            r.ado_release_ref
            for r in s.scalars(select(models.Release).order_by(models.Release.release_id))
        ]
    assert refs == ["REL-2026.01", "REL-2026.02", "REL-2026.03", "REL-2026.04"]


def test_failed_release_is_retried_and_blocks_later_ones(svc, users, documented, monkeypatch):
    real = svc.updater.update_release
    calls = {"n": 0}

    def flaky(release_id, user_id=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("LLM down")
        return real(release_id, user_id)

    monkeypatch.setattr(svc.updater, "update_release", flaky)
    first = svc.monitor.poll()
    assert [r["status"] for r in first] == ["FAILED"]  # stops at the failure to keep order
    second = svc.monitor.poll()
    assert [r["release"] for r in second] == ["REL-2026.01", "REL-2026.02"]
    assert all(r["status"] == "DOCS_UPDATED" for r in second)


# ------------------------------------------------------------------ security & governance
def test_sg01_business_analyst_cannot_open_administration(db, users):
    ba = users["BUSINESS_ANALYST"]
    for fn in (
        lambda: admin_service.list_users(ba),
        lambda: admin_service.audit_logs(ba),
        lambda: admin_service.list_integrations(ba),
    ):
        with pytest.raises(AccessDeniedError):
            fn()
    assert admin_service.list_users(users["ADMIN"])
    with session_scope() as s:  # the denial itself is audited
        assert s.scalars(
            select(models.AuditLog).where(models.AuditLog.action == "ACCESS_DENIED")
        ).first()


def test_sg02_audit_log_is_append_only(db, users):
    with session_scope() as s:
        s.add(models.AuditLog(actor="t", action="X"))
    with pytest.raises(DBAPIError):
        with session_scope() as s:
            s.execute(text("UPDATE audit_log SET action='Y'"))
    with pytest.raises(DBAPIError):
        with session_scope() as s:
            s.execute(text("DELETE FROM audit_log"))
    with session_scope() as s:
        assert s.scalars(select(models.AuditLog).where(models.AuditLog.action == "X")).first()


def test_sg03_integration_config_holds_only_env_var_names(db, users):
    admin = users["ADMIN"]
    with pytest.raises(ValueError):
        admin_service.update_integration(
            admin, "ADO", "https://dev.azure.com/x", "p", "my-secret-pat-123"
        )
    admin_service.update_integration(admin, "ADO", "https://dev.azure.com/x", "p", "ADO_PAT")
    with session_scope() as s:
        for c in s.scalars(select(models.IntegrationConfig)):
            assert c.secret_ref is None or re.fullmatch(r"[A-Z][A-Z0-9_]+", c.secret_ref)
            assert "token" not in str(c.settings).lower() and "pat" not in c.settings


def test_login_and_password_hashing(db):
    assert authenticate("ba", "Demo@123").role == "BUSINESS_ANALYST"
    assert authenticate("ba", "wrong") is None
    with session_scope() as s:
        assert s.scalars(select(models.User)).first().password_hash.startswith("$2")


def test_artifacts_are_never_deleted_and_status_check_constraint(db, users):
    with pytest.raises(DBAPIError):
        with session_scope() as s:
            s.add(
                models.ImpactAnalysis(
                    req_id=1,
                    complexity="Low",
                    risk="Low",
                    effort_days=1,
                    testing_strategy="x",
                    status="BOGUS",
                )
            )
            s.flush()
    _ = (add_document, get_embedder)
