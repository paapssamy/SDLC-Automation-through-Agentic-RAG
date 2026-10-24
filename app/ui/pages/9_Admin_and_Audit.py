"""Module 3.9 – Administration (users, integration settings without secrets) and audit log."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.errors import AccessDeniedError  # noqa: E402
from app.services import admin_service  # noqa: E402
from app.ui.common import ROLE_LABELS, guarded, require_login  # noqa: E402

st.set_page_config(page_title="Admin and Audit", page_icon="🛡️", layout="wide")
user = require_login()
st.title("🛡️ Administration and Audit")

try:  # RBAC is enforced in the service layer, not by hiding the page
    users = admin_service.list_users(user)
except AccessDeniedError:
    st.error("🚫 Access denied – this page is for Administrators only.")
    st.stop()

t1, t2, t3 = st.tabs(["Users and roles", "Integrations", "Audit log"])
with t1:
    st.dataframe(pd.DataFrame(users), hide_index=True, width="stretch")
    with st.form("newuser"):
        st.markdown("**Create user**")
        c = st.columns(4)
        uname = c[0].text_input("Username")
        full = c[1].text_input("Full name")
        role = c[2].selectbox("Role", list(ROLE_LABELS))
        pw = c[3].text_input("Password", type="password")
        if st.form_submit_button("Create"):
            guarded(admin_service.create_user, user, uname, full, role, pw, success="User created.")
    with st.form("chrole"):
        st.markdown("**Change role / activate**")
        c = st.columns(3)
        target = c[0].selectbox("User", users, format_func=lambda u: u["username"])
        nrole = c[1].selectbox("New role", list(ROLE_LABELS), key="nr")
        active = c[2].checkbox("Active", True)
        if st.form_submit_button("Update"):
            guarded(
                admin_service.set_user_role,
                user,
                target["user_id"],
                nrole,
                active,
                success="Updated.",
            )
with t2:
    st.caption("Secrets are never stored here – only the NAME of the environment variable.")
    for cfg in admin_service.list_integrations(user):
        with st.form(f"int{cfg['system']}"):
            st.markdown(f"**{cfg['system']}**  \nsettings: `{cfg['settings']}`")
            c = st.columns(3)
            url = c[0].text_input("Base URL", cfg["base_url"] or "", key=f"u{cfg['system']}")
            proj = c[1].text_input(
                "Project / space", cfg["project_or_space"] or "", key=f"p{cfg['system']}"
            )
            ref = c[2].text_input(
                "Secret env var name", cfg["secret_ref"] or "", key=f"s{cfg['system']}"
            )
            if st.form_submit_button("Save"):
                guarded(
                    admin_service.update_integration,
                    user,
                    cfg["system"],
                    url or None,
                    proj or None,
                    ref or None,
                    success="Saved.",
                )
with t3:
    c = st.columns(3)
    actor = c[0].text_input("Actor contains / equals")
    action = c[1].text_input("Action (exact)")
    atype = c[2].text_input("Artifact type (exact)")
    logs = admin_service.audit_logs(user, actor or None, action or None, atype or None)
    st.caption(f"{len(logs)} entries (append-only – cannot be edited or deleted)")
    if logs:
        df = pd.DataFrame(logs)
        df["details"] = df["details"].astype(str)
        st.dataframe(df, hide_index=True, width="stretch")
