"""Module 3.1 – As-Is Documentation (Technical Lead generates, Technical Lead reviews)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services import queries  # noqa: E402
from app.ui.common import guarded, require_login, services  # noqa: E402

st.set_page_config(page_title="As-Is Documentation", page_icon="📚", layout="wide")
user = require_login()
svc = services()
st.title("📚 As-Is Documentation")
st.caption("Java source → functional documentation per service. Reviewed by the Technical Lead.")

default = str(get_settings().sample_data_dir / "java-payments-app")
folder = st.text_input("Java source folder", default)
if st.button("Generate documentation", type="primary"):
    with st.spinner("Parsing Java and writing documentation…"):
        res = guarded(svc.orchestrator.generate_documentation, user, folder)
    if res is not None:
        st.success(
            f"{len(res)} documentation section(s) submitted for review "
            "(services that were already documented are skipped)."
        )

docs = queries.list_documents()
st.markdown("### Knowledge base sections")
if docs:
    st.dataframe(pd.DataFrame(docs).drop(columns=["doc_id"]), hide_index=True, width="stretch")
    pick = st.selectbox(
        "View a section", docs, format_func=lambda d: f"{d['service']} (v{d['version']})"
    )
    if pick:
        d = queries.get_document(pick["doc_id"])
        st.markdown(d["content"])
        with st.expander("Version history"):
            for v in d["versions"]:
                st.markdown(f"**v{v['version']}** – {v['summary']}")
else:
    st.info("No documentation yet. Log in as the Technical Lead and click Generate.")
