"""System tests: scripted end-to-end scenarios through the service layer."""

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import models
from app.db.base import session_scope
from app.errors import AccessDeniedError, GateError, InvalidTransitionError
from app.services.container import build_services


@pytest.fixture()
def svc(db):
    return build_services()


@pytest.fixture()
def documented(svc, users):
    """As-is docs generated and approved by the Technical Lead (knowledge base is ready)."""
    res = svc.orchestrator.generate_documentation(users["TECHNICAL_LEAD"])
    for r in res:
        svc.orchestrator.review(users["TECHNICAL_LEAD"], "SERVICE_DOCUMENT", r.id, "APPROVED")
    return res


def _status(model, pk):
    with session_scope() as s:
        return s.get(model, pk).status


def test_as_is_docs_are_reviewed_then_published_to_confluence(svc, users, documented):
    assert len(documented) >= 10
    with session_scope() as s:
        docs = s.scalars(select(models.ServiceDocument)).all()
    assert all(d.status == "PUBLISHED" for d in docs)  # approved -> published to Confluence
    assert list((get_settings().workspace_dir / "confluence").glob("*.html"))


def test_st01_requirement_to_impact_with_sources(svc, users, documented):
    ba = users["BUSINESS_ANALYST"]
    req = svc.orchestrator.create_requirement(
        ba, "Purpose code", "Add a mandatory purpose code field to outgoing pacs.008 messages."
    )
    res = svc.orchestrator.run_impact_analysis(ba, req)
    assert _status(models.ImpactAnalysis, res.id) == "PENDING_REVIEW"
    with session_scope() as s:
        refs = s.scalars(select(models.ApprovalRequest)).all()
        ia = s.get(models.ImpactAnalysis, res.id)
    assert any(r.source_refs for r in refs)  # sources + scores stored for the reviewer
    assert "Pacs008MessageBuilder" in ia.affected_services


def test_st03_next_stage_blocked_while_pending(svc, users, documented):
    ba = users["BUSINESS_ANALYST"]
    req = svc.orchestrator.create_requirement(ba, "x", "Add purpose code to pacs.008 messages")
    res = svc.orchestrator.run_impact_analysis(ba, req)
    for _ in range(2):  # "page refresh": the request is simply repeated
        with pytest.raises(GateError):
            svc.orchestrator.generate_story(ba, res.id)
    with session_scope() as s:
        assert s.scalars(select(models.UserStory)).first() is None


def test_full_chain_to_signoff_and_st02_code_adoption(svc, users, documented):
    o = svc.orchestrator
    ba, tl, dev, qa = (
        users[r] for r in ("BUSINESS_ANALYST", "TECHNICAL_LEAD", "DEVELOPER", "QA_LEAD")
    )
    req = o.create_requirement(
        ba, "Purpose code", "Add a mandatory purpose code field to outgoing pacs.008 messages."
    )
    imp = o.run_impact_analysis(ba, req)
    o.review(tl, "IMPACT_ANALYSIS", imp.id, "APPROVED")

    story = o.generate_story(ba, imp.id)
    o.review(ba, "USER_STORY", story.id, "APPROVED")
    with session_scope() as s:
        assert s.get(models.UserStory, story.id).ado_work_item_id  # IT-02: work item id saved

    code = o.generate_code(dev, story.id)
    assert code.ids
    # ST-02: not adopted before approval
    with pytest.raises(GateError):
        o.adopt_code(dev, story.id)
    assert not (get_settings().workspace_dir / "branches" / f"story-{story.id}").exists()
    for cid in code.ids:
        o.review(dev, "CODE_CHANGE", cid, "APPROVED")
    location = o.adopt_code(dev, story.id)
    assert (get_settings().workspace_dir / "branches" / f"story-{story.id}").exists()
    assert location
    assert _status(models.CodeChange, code.ids[0]) == "PUBLISHED"

    tests = o.generate_tests(qa, story.id)
    assert len(tests.ids) >= 4
    with pytest.raises(GateError):  # tests not approved yet
        o.run_tests(qa, story.id)
    for tid in tests.ids:
        o.review(qa, "TEST_SCENARIO", tid, "APPROVED")
    first = o.run_tests(qa, story.id)
    assert any(r["status"] == "FAIL" for r in first)  # mock runner: boundary defect on run 1
    with pytest.raises(GateError):
        o.sign_off(qa, story.id)
    o.run_tests(qa, story.id)  # run 2 passes
    with session_scope() as s:
        manual = [t.test_id for t in s.scalars(select(models.TestScenario)) if not t.automated]
    for tid in manual:
        o.record_manual_result(qa, tid, "PASS", "Business accepted")
    run_id = o.sign_off(qa, story.id)
    assert run_id.startswith("TR-")
    assert all(_status(models.TestScenario, t) == "PUBLISHED" for t in tests.ids)


def test_wrong_role_cannot_review_or_trigger(svc, users, documented):
    ba, dev = users["BUSINESS_ANALYST"], users["DEVELOPER"]
    req = svc.orchestrator.create_requirement(ba, "x", "Add purpose code to pacs.008")
    imp = svc.orchestrator.run_impact_analysis(ba, req)
    with pytest.raises(AccessDeniedError):  # a BA is not the checker of impact analyses
        svc.orchestrator.review(ba, "IMPACT_ANALYSIS", imp.id, "APPROVED")
    with pytest.raises(AccessDeniedError):
        svc.orchestrator.generate_code(
            dev, 1
        ) if False else svc.orchestrator.generate_documentation(dev)


def test_changes_requested_regenerates_with_version_bump(svc, users, documented):
    ba, tl = users["BUSINESS_ANALYST"], users["TECHNICAL_LEAD"]
    req = svc.orchestrator.create_requirement(ba, "x", "Add purpose code to pacs.008 messages")
    imp = svc.orchestrator.run_impact_analysis(ba, req)
    with pytest.raises(ValueError):  # comment is mandatory
        svc.orchestrator.review(tl, "IMPACT_ANALYSIS", imp.id, "CHANGES_REQUESTED", "")
    svc.orchestrator.review(tl, "IMPACT_ANALYSIS", imp.id, "CHANGES_REQUESTED", "Add MT103 check")
    res = svc.orchestrator.regenerate(ba, "IMPACT_ANALYSIS", imp.id)
    with session_scope() as s:
        row = s.get(models.ImpactAnalysis, res.id)
    assert row.version_no == 2 and row.status == "PENDING_REVIEW"


def test_rejected_artifact_is_final(svc, users, documented):
    ba, tl = users["BUSINESS_ANALYST"], users["TECHNICAL_LEAD"]
    req = svc.orchestrator.create_requirement(ba, "x", "Add purpose code to pacs.008 messages")
    imp = svc.orchestrator.run_impact_analysis(ba, req)
    svc.orchestrator.review(tl, "IMPACT_ANALYSIS", imp.id, "REJECTED", "Out of scope")
    with pytest.raises(InvalidTransitionError):
        svc.orchestrator.review(tl, "IMPACT_ANALYSIS", imp.id, "APPROVED")
    with pytest.raises(GateError):
        svc.orchestrator.generate_story(ba, imp.id)
