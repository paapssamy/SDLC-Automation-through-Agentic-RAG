"""Module 3.9 – Review Queue: maker-checker approvals for the logged-in role."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st  # noqa: E402

from app.services import queries  # noqa: E402
from app.ui.common import guarded, render_artifact, require_login, services  # noqa: E402

st.set_page_config(page_title="Review Queue", page_icon="✅", layout="wide")
user = require_login()
svc = services()
st.title("✅ Review Queue")
st.caption("Every artifact waits here until a human checker approves it (maker–checker).")

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

pending = svc.approvals.pending_for_role(user.role)
if not pending:
    st.success("Nothing is waiting for your review.")
    st.stop()

st.write(f"{len(pending)} item(s) waiting for **{user.role}**")
for p in pending:
    with st.expander(f"{p['label']} #{p['artifact_id']}", expanded=len(pending) == 1):
        render_artifact(queries.artifact_detail(p["artifact_type"], p["artifact_id"]))
        key = f"{p['approval_id']}"
        comment = st.text_area("Comment (required to request changes or reject)", key=f"c{key}")
        a, b, c = st.columns(3)
        for col, label, decision in (
            (a, "✅ Approve", "APPROVED"),
            (b, "✏️ Request changes", "CHANGES_REQUESTED"),
            (c, "⛔ Reject", "REJECTED"),
        ):
            if col.button(label, key=f"{decision}{key}"):

                def _decide(decision=decision, p=p, comment=comment):
                    svc.orchestrator.review(
                        user, p["artifact_type"], p["artifact_id"], decision, comment
                    )
                    return True

                if guarded(_decide):  # on errors the message stays visible (no rerun)
                    st.session_state["flash"] = (
                        f"{p['label']} #{p['artifact_id']}: {decision.replace('_', ' ').title()}"
                    )
                    st.rerun()
