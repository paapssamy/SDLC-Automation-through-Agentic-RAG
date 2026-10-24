"""Module 3.8 – Release Monitoring and living documentation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.services import queries  # noqa: E402
from app.services.auth import require_role  # noqa: E402
from app.ui.common import colored_diff, guarded, require_login, services  # noqa: E402

st.set_page_config(page_title="Releases and Docs", page_icon="🚀", layout="wide")
user = require_login()
svc = services()
st.title("🚀 Releases and Living Documentation")
st.caption(
    f"ADO polling every {svc.settings.release_poll_minutes} min · last processed release: "
    f"**{svc.monitor.last_processed() or 'none'}** · scheduler "
    f"{'running' if svc.scheduler.running else 'stopped'}"
)


def _run_now():
    require_role(user, "TECHNICAL_LEAD")
    return svc.scheduler.run_now()


c1, c2 = st.columns(2)
if c1.button("Run now (poll ADO)", type="primary"):
    with st.spinner("Fetching releases and updating affected sections…"):
        out = guarded(_run_now)
    if out is not None:
        st.success(
            "Processed: "
            + (
                ", ".join(
                    f"{o['release']} → {o['status']} ({o['sections']} section(s))" for o in out
                )
                or "no new releases"
            )
        )
if c2.button("Start background scheduler"):
    guarded(
        lambda: svc.scheduler.start(catch_up=True),
        success="Scheduler started (missed releases are replayed first).",
    )

rels = queries.list_releases()
st.subheader("Releases")
if rels:
    st.dataframe(pd.DataFrame(rels), hide_index=True, width="stretch")
else:
    st.info("No releases processed yet.")

st.subheader("Documentation versions")
docs = [d for d in queries.list_documents() if d["version"] > 1]
if not docs:
    st.caption("No section has been updated by a release yet.")
for d in docs:
    full = queries.get_document(d["doc_id"])
    with st.expander(f"{d['service']} – v{d['version']} ({d['status']})"):
        vs = full["versions"]
        if len(vs) >= 2:
            import difflib

            colored_diff(
                "\n".join(
                    difflib.unified_diff(
                        vs[-2]["content"].splitlines(),
                        vs[-1]["content"].splitlines(),
                        f"v{vs[-2]['version']}",
                        f"v{vs[-1]['version']}",
                        lineterm="",
                    )
                )
            )
        for v in vs:
            st.caption(f"v{v['version']}: {v['summary']}")
st.info(
    "Technical Lead confirms each release update in the Review Queue; approved updates are "
    "published to Confluence (mock: workspace/confluence/)."
)
