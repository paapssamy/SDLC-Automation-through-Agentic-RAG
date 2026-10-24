"""Artifact registry and the State pattern for artifact status transitions.

Allowed transitions (anything else raises InvalidTransitionError):
    DRAFT -> PENDING_REVIEW
    PENDING_REVIEW -> APPROVED | CHANGES_REQUESTED | REJECTED
    CHANGES_REQUESTED -> DRAFT          (regenerate, version_no + 1)
    APPROVED -> PUBLISHED
    PUBLISHED -> SUPERSEDED
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db import models
from app.errors import InvalidTransitionError

ALLOWED: dict[str, set[str]] = {
    "DRAFT": {"PENDING_REVIEW"},
    "PENDING_REVIEW": {"APPROVED", "CHANGES_REQUESTED", "REJECTED"},
    "CHANGES_REQUESTED": {"DRAFT"},
    "APPROVED": {"PUBLISHED"},
    "REJECTED": set(),
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def check_transition(old: str, new: str) -> None:
    if new not in ALLOWED.get(old, set()):
        raise InvalidTransitionError(f"Transition {old} -> {new} is not allowed")


def transition(artifact, new_status: str) -> None:
    """State pattern: validate and apply a status change on an artifact row."""
    check_transition(artifact.status, new_status)
    artifact.status = new_status


@dataclass(frozen=True)
class ArtifactKind:
    model: type
    pk: str
    checker_role: str
    label: str
    has_status: bool = True


ARTIFACTS: dict[str, ArtifactKind] = {
    "SERVICE_DOCUMENT": ArtifactKind(
        models.ServiceDocument, "doc_id", "TECHNICAL_LEAD", "As-is documentation"
    ),
    "IMPACT_ANALYSIS": ArtifactKind(
        models.ImpactAnalysis, "analysis_id", "TECHNICAL_LEAD", "Impact analysis"
    ),
    "USER_STORY": ArtifactKind(models.UserStory, "story_id", "BUSINESS_ANALYST", "User story"),
    "CODE_CHANGE": ArtifactKind(models.CodeChange, "change_id", "DEVELOPER", "Code change"),
    "TEST_SCENARIO": ArtifactKind(models.TestScenario, "test_id", "QA_LEAD", "Test case"),
    # Living-documentation update after a release: content is already versioned in the KB; the
    # Technical Lead confirms it before it is published to Confluence (no status column).
    "DOC_UPDATE": ArtifactKind(
        models.ServiceDocument, "doc_id", "TECHNICAL_LEAD", "Release doc update", has_status=False
    ),
}


def artifact_id(artifact) -> int:
    for kind in ARTIFACTS.values():
        if isinstance(artifact, kind.model):
            return getattr(artifact, kind.pk)
    raise TypeError(type(artifact))
