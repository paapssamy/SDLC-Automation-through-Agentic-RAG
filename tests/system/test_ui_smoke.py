"""Smoke test: every Streamlit page renders for every role without an exception (AppTest)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.config import ROOT
from app.services.container import build_services

UI = ROOT / "app" / "ui"
PAGES = sorted((UI / "pages").glob("*.py"))


@pytest.fixture()
def seeded(db, users):
    """Knowledge base + one requirement flowing through review, so pages have content."""
    svc = build_services()
    tl, ba = users["TECHNICAL_LEAD"], users["BUSINESS_ANALYST"]
    for r in svc.orchestrator.generate_documentation(tl):
        svc.orchestrator.review(tl, "SERVICE_DOCUMENT", r.id, "APPROVED")
    req = svc.orchestrator.create_requirement(ba, "Purpose", "Add purpose code to pacs.008")
    svc.orchestrator.run_impact_analysis(ba, req)
    svc.monitor.poll()
    return svc


def _run(path: Path, user):
    at = AppTest.from_file(str(path), default_timeout=60)
    at.session_state["user"] = user
    return at.run()


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
@pytest.mark.parametrize(
    "role", ["BUSINESS_ANALYST", "TECHNICAL_LEAD", "DEVELOPER", "QA_LEAD", "ADMIN"]
)
def test_page_renders_for_role(seeded, users, page, role):
    at = _run(page, users[role])
    assert not at.exception, [e.value for e in at.exception]


def test_home_login_flow(seeded):
    at = AppTest.from_file(str(UI / "Home.py"), default_timeout=60).run()
    assert not at.exception
    at.text_input[0].set_value("ba")
    at.text_input[1].set_value("Demo@123")
    at.button[0].click()
    at.run()
    assert not at.exception and at.session_state["user"].role == "BUSINESS_ANALYST"


def test_admin_page_denies_business_analyst(seeded, users):
    at = _run(UI / "pages" / "9_Admin_and_Audit.py", users["BUSINESS_ANALYST"])
    assert any("Access denied" in e.value for e in at.error)
    at = _run(UI / "pages" / "9_Admin_and_Audit.py", users["ADMIN"])
    assert not at.error
