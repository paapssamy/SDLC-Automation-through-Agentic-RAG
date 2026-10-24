"""Shared Streamlit helpers: login state, service access, badges, error handling.

The UI only calls services; the approval gate and RBAC live in the service layer.
"""

from __future__ import annotations

import html
from collections.abc import Callable

import pandas as pd
import streamlit as st

from app.errors import (
    AccessDeniedError,
    GateError,
    GenerationError,
    InvalidTransitionError,
    ValidationFailedError,
)
from app.services.auth import CurrentUser
from app.services.container import Services, get_services

STATUS_COLORS = {
    "DRAFT": "#6b7280",
    "PENDING_REVIEW": "#d97706",
    "CHANGES_REQUESTED": "#7c3aed",
    "APPROVED": "#16a34a",
    "REJECTED": "#dc2626",
    "PUBLISHED": "#0369a1",
    "SUPERSEDED": "#9ca3af",
}
ROLE_LABELS = {
    "BUSINESS_ANALYST": "Business Analyst",
    "TECHNICAL_LEAD": "Technical Lead",
    "DEVELOPER": "Developer",
    "QA_LEAD": "QA Lead",
    "ADMIN": "Administrator",
}


@st.cache_resource(show_spinner="Loading models and services…")
def services() -> Services:
    return get_services()


def badge(status: str | None) -> str:
    color = STATUS_COLORS.get(status or "", "#6b7280")
    return (
        f"<span style='background:{color};color:#fff;padding:2px 10px;border-radius:12px;"
        f"font-size:0.8em;font-weight:600'>{html.escape(status or '-')}</span>"
    )


def current_user() -> CurrentUser | None:
    return st.session_state.get("user")


def require_login() -> CurrentUser:
    """Show the sidebar user box; stop the page if nobody is logged in."""
    user = current_user()
    if user is None:
        st.warning("Please log in on the Home page first.")
        st.stop()
    with st.sidebar:
        st.markdown(f"**{user.full_name}**  \n{ROLE_LABELS[user.role]}")
        if st.button("Log out", key="logout"):
            st.session_state.pop("user", None)
            st.rerun()
    return user


def guarded(fn: Callable, *args, success: str | None = None, **kwargs):
    """Run a service call and show friendly messages for the expected error types."""
    try:
        result = fn(*args, **kwargs)
        if success:
            st.success(success)
        return result
    except AccessDeniedError as e:
        st.error(f"🚫 {e}")
    except GateError as e:
        st.error(f"⛔ Stage blocked: {e}")
    except (GenerationError, ValidationFailedError) as e:
        st.error(f"Generation failed: {e}")
    except InvalidTransitionError as e:
        st.error(f"Not allowed: {e}")
    except ValueError as e:
        st.error(str(e))
    except Exception as e:  # unexpected – show, do not crash the page
        st.exception(e)
    return None


def show_sources(sources: list[dict]) -> None:
    """Source references with similarity scores (shown on every review screen)."""
    if not sources:
        st.caption("No sources recorded.")
        return
    df = pd.DataFrame(sources)
    if "baseline" in df and df["baseline"].any():
        st.warning(
            "⚠️ Low similarity – baseline core product specifications were added as "
            "fallback context."
        )
    cols = [c for c in ("service_name", "version", "score", "baseline", "doc_id") if c in df]
    st.dataframe(df[cols], hide_index=True, width="stretch")


def colored_diff(diff: str) -> None:
    lines = []
    for ln in diff.splitlines():
        esc = html.escape(ln)
        if ln.startswith("+") and not ln.startswith("+++"):
            lines.append(f"<div style='background:#dcfce7;color:#14532d'>{esc}</div>")
        elif ln.startswith("-") and not ln.startswith("---"):
            lines.append(f"<div style='background:#fee2e2;color:#7f1d1d'>{esc}</div>")
        elif ln.startswith("@@"):
            lines.append(f"<div style='background:#e0f2fe;color:#075985'>{esc}</div>")
        else:
            lines.append(f"<div>{esc}</div>")
    st.markdown(
        "<div style='font-family:monospace;font-size:0.85em;white-space:pre-wrap;"
        "border:1px solid #e5e7eb;padding:8px;border-radius:6px'>" + "".join(lines) + "</div>",
        unsafe_allow_html=True,
    )


def render_artifact(d: dict) -> None:
    """Human-readable view of any artifact for review screens."""
    t = d["type"]
    st.markdown(f"#### {d['label']} #{d['id']} {badge(d.get('status'))}", unsafe_allow_html=True)
    if t == "IMPACT_ANALYSIS":
        st.markdown(f"**Requirement:** {d['requirement']}")
        st.markdown("**Key entities:** " + (", ".join(d["entities"]) or "-"))
        st.markdown("**Affected services:** " + (", ".join(d["affected_services"]) or "-"))
        if d["unknown_services"]:
            st.markdown(
                "<div style='color:#dc2626;font-weight:700'>⚠ Not found in the knowledge "
                "base (possible hallucination): "
                + html.escape(", ".join(d["unknown_services"]))
                + "</div>",
                unsafe_allow_html=True,
            )
        c1, c2, c3 = st.columns(3)
        c1.metric("Complexity", d["complexity"])
        c2.metric("Risk", d["risk"])
        c3.metric("Effort (days)", d["effort_days"])
        st.markdown("**Dependencies:** " + (", ".join(d["dependencies"]) or "-"))
        st.markdown(f"**Testing strategy:** {d['testing_strategy']}")
    elif t == "USER_STORY":
        st.markdown(f"**{d['title']}**")
        st.write(d["description"])
        st.markdown("**Acceptance criteria**")
        for c in d["criteria"]:
            st.markdown(f"- {c}")
        inv = d["invest"] or {}
        st.markdown(
            "**INVEST check:** "
            + " ".join(f"{'✅' if inv.get(k, {}).get('pass') else '❌'}{k}" for k in "INVEST")
        )
        with st.expander("INVEST reasons"):
            for k in "INVEST":
                st.write(f"{k}: {inv.get(k, {}).get('reason', '')}")
        if d.get("work_item"):
            st.info(f"ADO work item: {d['work_item']}")
    elif t == "CODE_CHANGE":
        st.markdown(f"**File:** `{d['file']}` (version {d['version']})")
        colored_diff(d["diff"])
    elif t == "TEST_SCENARIO":
        st.markdown(
            f"**{d['title']}** — {d['phase']} / {d['test_type']} / {d['priority']} / "
            f"{'automated' if d['automated'] else 'manual'}"
        )
        for i, step in enumerate(d["steps"], 1):
            st.markdown(f"{i}. {step}")
        st.markdown(f"**Expected:** {d['expected']}")
    else:  # SERVICE_DOCUMENT / DOC_UPDATE
        st.markdown(f"**Service:** {d['service']} (version {d['version']})")
        if t == "DOC_UPDATE" and d.get("previous"):
            import difflib

            colored_diff(
                "\n".join(
                    difflib.unified_diff(
                        d["previous"].splitlines(),
                        d["content"].splitlines(),
                        "previous",
                        "updated",
                        lineterm="",
                    )
                )
            )
        else:
            st.markdown(d["content"])
    st.markdown("**Context sources and similarity scores**")
    show_sources(d.get("sources", []))
    if d.get("history"):
        with st.expander("Review history"):
            for h in d["history"]:
                st.write(f"{h['decision']} — {h['comments'] or ''}")
