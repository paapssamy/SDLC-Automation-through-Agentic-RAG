"""Module 3.6 – Test Case Generation (QA Lead generates, reviews and may edit)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.services import queries  # noqa: E402
from app.ui.common import guarded, require_login, services  # noqa: E402

st.set_page_config(page_title="Test Cases", page_icon="🧪", layout="wide")
user = require_login()
svc = services()
st.title("🧪 Test Cases")

stories = queries.list_stories()
if not stories:
    st.info("No user stories yet.")
    st.stop()
story = st.selectbox(
    "User story",
    stories,
    format_func=lambda s: f"#{s['story_id']} {s['title'][:70]} – {s['status']}",
)
if st.button("Generate test cases & submit for review", type="primary"):
    with st.spinner("Writing test scenarios…"):
        res = guarded(svc.orchestrator.generate_tests, user, story["story_id"])
    if res:
        st.success(f"{len(res.ids)} test case(s) submitted for QA Lead review.")

tests = queries.list_tests(story["story_id"])
if tests:
    st.dataframe(
        pd.DataFrame(tests).drop(columns=["steps", "expected"]), hide_index=True, width="stretch"
    )
    st.subheader("Edit a test case")
    t = st.selectbox("Test case", tests, format_func=lambda x: f"#{x['test_id']} {x['title'][:70]}")
    with st.form(f"edit{t['test_id']}"):
        title = st.text_input("Title", t["title"])
        prio = st.selectbox(
            "Priority",
            ["HIGH", "MEDIUM", "LOW"],
            index=["HIGH", "MEDIUM", "LOW"].index(t["priority"]),
        )
        steps = st.text_area("Steps (one per line)", "\n".join(t["steps"]))
        expected = st.text_area("Expected result", t["expected"])
        if st.form_submit_button("Save changes"):
            from app.services.auth import require_role

            def _save():
                require_role(user, "QA_LEAD")
                queries.edit_test_case(
                    t["test_id"],
                    {
                        "title": title,
                        "priority": prio,
                        "expected_result": expected,
                        "steps": [x for x in steps.splitlines() if x.strip()],
                    },
                    user.username,
                    user.user_id,
                )

            guarded(_save, success="Saved (audited).")
