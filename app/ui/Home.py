"""Streamlit entry point: login + role dashboard (workflow pipeline, pending reviews, notifications)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services import queries  # noqa: E402
from app.services.auth import authenticate  # noqa: E402
from app.services.workflow_orchestrator import WorkflowOrchestrator  # noqa: E402
from app.ui.common import ROLE_LABELS, STATUS_COLORS, badge, current_user, services  # noqa: E402

st.set_page_config(page_title="SDLC Agentic RAG", page_icon="🏦", layout="wide")
st.title("🏦 SDLC Automation through Agentic RAG")
st.caption("Banking payments application – ten role-based agents, human approval at every stage")

svc = services()
cfg = get_settings()
if cfg.app_mode == "production" and not svc.scheduler.running:
    svc.scheduler.start()

user = current_user()
if user is None:
    st.subheader("Log in")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Log in"):
            u = authenticate(username.strip(), password)
            if u:
                st.session_state["user"] = u
                st.rerun()
            else:
                st.error("Invalid username or password")
    st.info("Demo users: ba, techlead, dev, qa, admin  (password in README)")
    st.stop()

with st.sidebar:
    st.markdown(f"**{user.full_name}**  \n{ROLE_LABELS[user.role]}")
    st.caption(
        f"Mode: {cfg.app_mode} · LLM: {svc.llm.name} · ADO: {cfg.ado_mode} · "
        f"Confluence: {cfg.confluence_mode}"
    )
    if st.button("Log out"):
        st.session_state.pop("user")
        st.rerun()

st.subheader(f"Welcome, {user.full_name} – {ROLE_LABELS[user.role]}")

st.markdown("### Workflow pipeline")
counts = WorkflowOrchestrator.pipeline_counts()
cols = st.columns(len(counts))
for col, (stage, by_status) in zip(cols, counts.items(), strict=False):
    with col:
        st.markdown(f"**{stage}**")
        if not by_status:
            st.caption("nothing yet")
        for status, n in by_status.items():
            st.markdown(f"{badge(status)} &nbsp; **{n}**", unsafe_allow_html=True)
st.caption(
    "Legend: "
    + " ".join(f"<span style='color:{c}'>■</span> {s}" for s, c in STATUS_COLORS.items()),
    unsafe_allow_html=True,
)

left, right = st.columns(2)
with left:
    st.markdown("### My pending reviews")
    pending = svc.approvals.pending_for_role(user.role)
    if pending:
        st.dataframe(
            pd.DataFrame(pending)[["label", "artifact_id", "created_at"]],
            hide_index=True,
            width="stretch",
        )
        st.page_link("pages/8_Review_Queue.py", label="Open Review Queue →")
    else:
        st.success("Nothing waiting for your review.")
with right:
    st.markdown("### Notifications")
    notes = queries.notifications(user.role)
    if notes:
        for n in notes:
            st.write(f"🔔 {n['message']}  \n:gray[{n['time']:%Y-%m-%d %H:%M}]")
    else:
        st.caption("No notifications.")
