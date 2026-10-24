"""Module 3.4 – User Story (Business Analyst). Generated only from an APPROVED analysis."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st  # noqa: E402

from app.services import queries  # noqa: E402
from app.ui.common import badge, guarded, render_artifact, require_login, services  # noqa: E402

st.set_page_config(page_title="User Stories", page_icon="📝", layout="wide")
user = require_login()
svc = services()
st.title("📝 User Stories")
st.caption(
    "The server checks that the impact analysis is APPROVED – the button alone never decides."
)

analyses = queries.list_analyses()
if not analyses:
    st.info("No impact analyses yet. Create one on the Requirement and Impact page.")
else:
    pick = st.selectbox(
        "Impact analysis",
        analyses,
        format_func=lambda a: (
            f"#{a['analysis_id']} (req {a['req_id']}) – {a['status']} – "
            f"{', '.join(a['services'][:2])}"
        ),
    )
    st.markdown(badge(pick["status"]), unsafe_allow_html=True)
    if st.button("Generate user story & submit for review", type="primary"):
        with st.spinner("Writing the story and INVEST check…"):
            res = guarded(svc.orchestrator.generate_story, user, pick["analysis_id"])
        if res:
            st.success(f"User story #{res.id} is PENDING_REVIEW (Business Analyst).")

st.divider()
st.subheader("Stories")
for s in queries.list_stories():
    with st.expander(
        f"#{s['story_id']} {s['title']} — {s['status']}"
        + (f" — ADO {s['work_item']}" if s["work_item"] else "")
    ):
        render_artifact(queries.artifact_detail("USER_STORY", s["story_id"]))
        if s["status"] == "CHANGES_REQUESTED" and st.button("Regenerate", key=f"rg{s['story_id']}"):
            if guarded(svc.orchestrator.regenerate, user, "USER_STORY", s["story_id"]):
                st.rerun()
