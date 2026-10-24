"""Module 3.5 – Code Generation (Developer). Strictest gate: adoption only after approval."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st  # noqa: E402

from app.services import queries  # noqa: E402
from app.ui.common import badge, colored_diff, guarded, require_login, services  # noqa: E402

st.set_page_config(page_title="Code Changes", page_icon="💻", layout="wide")
user = require_login()
svc = services()
st.title("💻 Code Changes")
st.caption(
    "File-wise unified diff. The Developer approves in the Review Queue, then adopts "
    "the change into a branch."
)

stories = queries.list_stories()
if not stories:
    st.info("No user stories yet.")
    st.stop()

story = st.selectbox(
    "User story",
    stories,
    format_func=lambda s: f"#{s['story_id']} {s['title'][:70]} – {s['status']}",
)
st.markdown(badge(story["status"]), unsafe_allow_html=True)
c1, c2 = st.columns(2)
if c1.button("Generate code change", type="primary"):
    with st.spinner("Fetching source files and generating code…"):
        res = guarded(svc.orchestrator.generate_code, user, story["story_id"])
    if res:
        st.success(f"{len(res.ids)} file change(s) submitted for Developer review.")
if c2.button("Adopt approved changes into repository branch"):
    loc = guarded(svc.orchestrator.adopt_code, user, story["story_id"])
    if loc:
        st.success(f"Adopted → {loc}")

for c in queries.list_code_changes(story["story_id"]):
    with st.expander(
        f"#{c['change_id']} {c['file']} — {c['status']} (v{c['version']})", expanded=True
    ):
        st.markdown(badge(c["status"]), unsafe_allow_html=True)
        colored_diff(c["diff"])
        if c["adopted_path"]:
            st.info(f"Adopted at {c['adopted_path']}")
        if c["status"] == "CHANGES_REQUESTED" and st.button(
            "Regenerate", key=f"rg{c['change_id']}"
        ):
            if guarded(svc.orchestrator.regenerate, user, "CODE_CHANGE", c["change_id"]):
                st.rerun()
