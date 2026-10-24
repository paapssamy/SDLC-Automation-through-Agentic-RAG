"""Module 3.7 – Test Execution (QA Lead): automated run, manual results, sign-off, ADO upload."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.services import queries  # noqa: E402
from app.ui.common import guarded, require_login, services  # noqa: E402

st.set_page_config(page_title="Test Execution", page_icon="▶️", layout="wide")
user = require_login()
svc = services()
st.title("▶️ Test Execution")
st.caption("Only APPROVED test cases can run. Runner: " + type(svc.exec_agent.runner).__name__)

stories = queries.list_stories()
if not stories:
    st.info("No user stories yet.")
    st.stop()
story = st.selectbox(
    "User story", stories, format_func=lambda s: f"#{s['story_id']} {s['title'][:70]}"
)
sid = story["story_id"]

c1, c2 = st.columns(2)
if c1.button("Run approved automated cases", type="primary"):
    with st.spinner("Running tests…"):
        res = guarded(svc.orchestrator.run_tests, user, sid)
    if res:
        failed = sum(1 for r in res if r["status"] != "PASS")
        (st.warning if failed else st.success)(
            f"{len(res)} case(s) executed, {failed} not passing."
        )
if c2.button("QA sign-off & upload results to ADO"):
    run = guarded(svc.orchestrator.sign_off, user, sid)
    if run:
        st.success(f"Signed off. Results uploaded to ADO Test Plans as {run}.")

results = svc.exec_agent.latest_results(sid)
if results:
    df = pd.DataFrame(results)
    st.dataframe(
        df[
            [
                "test_id",
                "title",
                "phase",
                "test_type",
                "automated",
                "result",
                "run_no",
                "defect_ref",
                "signed_off",
                "status",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
    manual = [r for r in results if not r["automated"] and r["status"] == "APPROVED"]
    if manual:
        st.subheader("Record a manual result")
        with st.form("manual"):
            m = st.selectbox(
                "Manual case", manual, format_func=lambda x: f"#{x['test_id']} {x['title']}"
            )
            status = st.radio("Result", ["PASS", "FAIL", "BLOCKED"], horizontal=True)
            notes = st.text_area("Notes")
            defect = st.text_input("Defect reference (optional)")
            if st.form_submit_button("Save result"):
                guarded(
                    svc.orchestrator.record_manual_result,
                    user,
                    m["test_id"],
                    status,
                    notes,
                    defect or None,
                    success="Result recorded.",
                )
    with st.expander("Execution logs"):
        for r in results:
            st.markdown(f"**#{r['test_id']} {r['title']}** – {r['result']}")
            st.code(r["log"] or "-")
else:
    st.info("No approved test cases for this story yet (approve them in the Review Queue).")
