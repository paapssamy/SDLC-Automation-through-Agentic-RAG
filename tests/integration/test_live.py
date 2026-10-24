"""Live-system tests (real Azure DevOps / Confluence / Groq). Skipped unless explicitly enabled:

pytest -m live          (needs the matching variables in .env)
"""

import os

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def _require_live():
    if os.getenv("RUN_LIVE_TESTS") != "1":
        pytest.skip("set RUN_LIVE_TESTS=1 and real credentials to run live tests")


def test_live_ado_lists_releases():
    from app.config import reset_settings
    from app.integrations.ado_client import LiveAdoClient

    reset_settings()
    assert isinstance(LiveAdoClient().list_completed_releases(), list)


def test_live_groq_returns_text():
    from app.config import reset_settings
    from app.llm.groq_client import GroqClient

    reset_settings()
    from app.config import get_settings

    s = get_settings()
    assert GroqClient(s.groq_api_key, s.groq_model).generate("Reply with the word OK.")
