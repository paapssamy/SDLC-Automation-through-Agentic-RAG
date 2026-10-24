"""Module 3.3 – Requirement and Impact Analysis (Business Analyst submits, Technical Lead approves)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services import queries  # noqa: E402
from app.ui.common import badge, guarded, render_artifact, require_login, services  # noqa: E402

st.set_page_config(page_title="Requirement and Impact", page_icon="🧭", layout="wide")
user = require_login()
svc = services()
st.title("🧭 Requirement and Impact Analysis")

samples = sorted((get_settings().sample_data_dir / "requirements").glob("*.md"))
with st.form("req"):
    st.subheader("New business requirement")
    choice = st.selectbox("Load a sample requirement (optional)", ["—"] + [p.name for p in samples])
    title = st.text_input("Title")
    default_text = ""
    if choice != "—":
        default_text = (get_settings().sample_data_dir / "requirements" / choice).read_text("utf-8")
    text = st.text_area("Requirement text", value=default_text, height=140)
    c1, c2 = st.columns(2)
    market = c1.text_input("Market", "SG")
    product = c2.text_input("Product", "PAYMENTS")
    upload = st.file_uploader("Attachment (optional)")
    go = st.form_submit_button("Generate impact analysis & submit for review", type="primary")

if go:
    attachment = None
    if upload is not None:
        d = get_settings().workspace_dir / "attachments"
        d.mkdir(parents=True, exist_ok=True)
        (d / upload.name).write_bytes(upload.getvalue())
        attachment = str(d / upload.name)
    req_id = guarded(
        svc.orchestrator.create_requirement,
        user,
        title or choice,
        text,
        market,
        product,
        attachment,
    )
    if req_id:
        with st.spinner("Extracting entities, retrieving services, writing the impact report…"):
            res = guarded(svc.orchestrator.run_impact_analysis, user, req_id)
        if res:
            st.success(f"Impact analysis #{res.id} is PENDING_REVIEW (Technical Lead).")
            render_artifact(queries.artifact_detail("IMPACT_ANALYSIS", res.id))

st.divider()
st.subheader("Requirements and analyses")
for r in queries.list_requirements():
    with st.expander(f"#{r['req_id']} {r['title']} — analysis: {r['analysis_status'] or 'none'}"):
        st.write(r["text"])
        if r["analysis_id"]:
            render_artifact(queries.artifact_detail("IMPACT_ANALYSIS", r["analysis_id"]))
            if r["analysis_status"] == "CHANGES_REQUESTED":
                st.markdown(badge("CHANGES_REQUESTED"), unsafe_allow_html=True)
                if st.button("Regenerate with reviewer feedback", key=f"rg{r['analysis_id']}"):
                    res = guarded(
                        svc.orchestrator.regenerate,
                        user,
                        "IMPACT_ANALYSIS",
                        r["analysis_id"],
                        success="Regenerated as a new version.",
                    )
                    if res:
                        st.rerun()
        elif st.button("Run impact analysis", key=f"run{r['req_id']}"):
            guarded(svc.orchestrator.run_impact_analysis, user, r["req_id"])
            st.rerun()
