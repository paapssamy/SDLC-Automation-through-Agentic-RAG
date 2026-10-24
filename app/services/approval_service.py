"""ApprovalService – Maker-Checker (dual control) with the artifact State machine.

* The maker (an agent) saves an artifact; it goes to PENDING_REVIEW.
* Only a user with the checker role of that artifact type can approve / request changes / reject.
* Artifact + approval_request + audit_log rows are written in ONE transaction.
* Artifacts are never deleted.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.db.base import session_scope
from app.db.repositories import AuditRepository
from app.errors import InvalidTransitionError
from app.services import notification_service as ev
from app.services.artifacts import ARTIFACTS, artifact_id, check_transition, transition
from app.services.auth import CurrentUser, require_role

log = logging.getLogger(__name__)

MAKER_ROLE = {
    "SERVICE_DOCUMENT": "TECHNICAL_LEAD",
    "IMPACT_ANALYSIS": "BUSINESS_ANALYST",
    "USER_STORY": "BUSINESS_ANALYST",
    "CODE_CHANGE": "DEVELOPER",
    "TEST_SCENARIO": "QA_LEAD",
    "DOC_UPDATE": "TECHNICAL_LEAD",
}
DECISIONS = ("APPROVED", "CHANGES_REQUESTED", "REJECTED")


@dataclass
class SubmitResult:
    artifact_type: str
    ids: list[int]
    approval_ids: list[int] = field(default_factory=list)

    @property
    def id(self) -> int:
        return self.ids[0]


class ApprovalService:
    def __init__(self, bus: ev.EventBus | None = None) -> None:
        self.bus = bus or ev.EventBus()
        # post-approval hooks run AFTER the approval is committed (e.g. create ADO work item)
        self._hooks: dict[str, list[tuple[Callable[[int, CurrentUser], None], tuple]]] = {}

    def register_hook(
        self,
        artifact_type: str,
        fn: Callable[[int, CurrentUser], None],
        decisions: tuple = ("APPROVED",),
    ) -> None:
        self._hooks.setdefault(artifact_type, []).append((fn, decisions))

    # ------------------------------------------------------------------ maker side
    def submit(
        self,
        artifact_type: str,
        result,
        context,
        persist: Callable[[Session], object | list],
        created_by: int | None = None,
        actor: str = "agent",
    ) -> SubmitResult:
        """Save the artifact(s) built by `persist`, move DRAFT -> PENDING_REVIEW, open approval."""
        kind = ARTIFACTS[artifact_type]
        refs = context.source_refs if hasattr(context, "source_refs") else list(context or [])
        with session_scope() as s:
            rows = persist(s)
            rows = rows if isinstance(rows, list) else [rows]
            s.flush()
            ids, approvals = [], []
            for row in rows:
                if kind.has_status:
                    if row.status != "DRAFT":
                        row.status = "DRAFT"
                    transition(row, "PENDING_REVIEW")
                aid = artifact_id(row)
                req = models.ApprovalRequest(
                    artifact_type=artifact_type,
                    artifact_id=aid,
                    submitted_by=created_by,
                    decision="PENDING",
                    source_refs=refs,
                )
                s.add(req)
                s.flush()
                AuditRepository.add(
                    s,
                    actor,
                    "SUBMITTED_FOR_REVIEW",
                    artifact_type,
                    aid,
                    {
                        "approval_id": req.approval_id,
                        "sources": len(refs),
                        "used_fallback": getattr(context, "used_fallback", False),
                    },
                    user_id=created_by,
                )
                ids.append(aid)
                approvals.append(req.approval_id)
        for aid in ids:
            self.bus.publish(
                ev.SUBMITTED,
                {"checker_role": kind.checker_role, "label": kind.label, "artifact_id": aid},
            )
        return SubmitResult(artifact_type, ids, approvals)

    def reopen(self, session: Session, artifact, actor: str, feedback: str = "") -> None:
        """CHANGES_REQUESTED -> DRAFT with version_no + 1 (before regeneration)."""
        transition(artifact, "DRAFT")
        attr = "version_no" if hasattr(artifact, "version_no") else "current_version"
        setattr(artifact, attr, (getattr(artifact, attr) or 1) + 1)
        AuditRepository.add(
            session,
            actor,
            "REGENERATION_STARTED",
            type(artifact).__name__,
            artifact_id(artifact),
            {"feedback": feedback[:500], "version_no": getattr(artifact, attr)},
        )

    # ------------------------------------------------------------------ checker side
    def decide(
        self,
        artifact_type: str,
        art_id: int,
        reviewer: CurrentUser,
        decision: str,
        comments: str = "",
    ) -> None:
        kind = ARTIFACTS[artifact_type]
        require_role(reviewer, kind.checker_role)
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        if decision != "APPROVED" and not comments.strip():
            raise ValueError("A comment is required to request changes or reject")
        with session_scope() as s:
            art = s.get(kind.model, art_id)
            if art is None:
                raise LookupError(f"{artifact_type} #{art_id} not found")
            if kind.has_status:
                transition(art, decision)  # raises InvalidTransitionError if not PENDING_REVIEW
                art.reviewed_by = reviewer.user_id
            req = s.scalars(
                select(models.ApprovalRequest)
                .where(
                    models.ApprovalRequest.artifact_type == artifact_type,
                    models.ApprovalRequest.artifact_id == art_id,
                    models.ApprovalRequest.decision == "PENDING",
                )
                .order_by(models.ApprovalRequest.approval_id.desc())
            ).first()
            if req is None:
                raise InvalidTransitionError(f"{artifact_type} #{art_id} has no pending review")
            req.decision, req.reviewer_id, req.comments = decision, reviewer.user_id, comments
            req.decided_at = datetime.now(UTC)
            AuditRepository.add(
                s,
                reviewer.username,
                f"REVIEW_{decision}",
                artifact_type,
                art_id,
                {"comments": comments, "approval_id": req.approval_id},
                user_id=reviewer.user_id,
            )
        self.bus.publish(
            ev.DECIDED,
            {
                "maker_role": MAKER_ROLE[artifact_type],
                "label": kind.label,
                "artifact_id": art_id,
                "decision": decision,
                "reviewer": reviewer.username,
            },
        )
        for hook, decisions in self._hooks.get(artifact_type, []):
            if decision not in decisions:
                continue
            try:
                hook(art_id, reviewer)
            except Exception as exc:
                log.exception("post-decision hook failed")
                with session_scope() as s:
                    AuditRepository.add(
                        s,
                        "system",
                        "POST_DECISION_HOOK_FAILED",
                        artifact_type,
                        art_id,
                        {"error": str(exc)[:300]},
                    )

    def publish(
        self, artifact_type: str, art_id: int, actor: str = "system", user_id: int | None = None
    ) -> None:
        """APPROVED -> PUBLISHED; the previous PUBLISHED version of the same document is superseded."""
        kind = ARTIFACTS[artifact_type]
        with session_scope() as s:
            art = s.get(kind.model, art_id)
            transition(art, "PUBLISHED")
            AuditRepository.add(s, actor, "PUBLISHED", artifact_type, art_id, user_id=user_id)

    def supersede(self, artifact_type: str, art_id: int, actor: str = "system") -> None:
        kind = ARTIFACTS[artifact_type]
        with session_scope() as s:
            art = s.get(kind.model, art_id)
            transition(art, "SUPERSEDED")
            AuditRepository.add(s, actor, "SUPERSEDED", artifact_type, art_id)

    # ------------------------------------------------------------------ queries
    def pending_for_role(self, role: str) -> list[dict]:
        """Every PENDING_REVIEW artifact whose checker role is `role` (Review Queue)."""
        out = []
        with session_scope() as s:
            reqs = s.scalars(
                select(models.ApprovalRequest)
                .where(models.ApprovalRequest.decision == "PENDING")
                .order_by(models.ApprovalRequest.approval_id)
            ).all()
            for r in reqs:
                kind = ARTIFACTS.get(r.artifact_type)
                if kind and kind.checker_role == role:
                    out.append(
                        {
                            "approval_id": r.approval_id,
                            "artifact_type": r.artifact_type,
                            "artifact_id": r.artifact_id,
                            "source_refs": r.source_refs,
                            "created_at": r.created_at,
                            "label": kind.label,
                        }
                    )
        return out

    @staticmethod
    def validate_check(old: str, new: str) -> None:
        check_transition(old, new)
