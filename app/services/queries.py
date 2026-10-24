"""Read-only queries for the UI (keeps ORM code out of the Streamlit pages)."""

from __future__ import annotations

from sqlalchemy import select

from app.db import models
from app.db.base import session_scope
from app.db.repositories import DocumentRepository, NotificationRepository
from app.services.artifacts import ARTIFACTS


def list_documents() -> list[dict]:
    with session_scope() as s:
        return [
            {
                "doc_id": d.doc_id,
                "service": d.service_name,
                "market": d.market,
                "product": d.product,
                "status": d.status,
                "version": d.current_version,
                "hash": d.content_hash[:10],
                "updated": d.updated_at,
            }
            for d in DocumentRepository.all(s)
        ]


def get_document(doc_id: int) -> dict:
    with session_scope() as s:
        d = s.get(models.ServiceDocument, doc_id)
        versions = [
            {
                "version": v.version_no,
                "release_id": v.release_id,
                "summary": v.change_summary,
                "content": v.content,
                "created": v.created_at,
            }
            for v in DocumentRepository.versions(s, doc_id)
        ]
        return {
            "doc_id": d.doc_id,
            "service": d.service_name,
            "content": d.content,
            "status": d.status,
            "version": d.current_version,
            "versions": versions,
        }


def list_requirements() -> list[dict]:
    out = []
    with session_scope() as s:
        for r in s.scalars(
            select(models.BusinessRequirement).order_by(models.BusinessRequirement.req_id.desc())
        ):
            a = s.scalars(
                select(models.ImpactAnalysis)
                .where(models.ImpactAnalysis.req_id == r.req_id)
                .order_by(models.ImpactAnalysis.analysis_id.desc())
            ).first()
            out.append(
                {
                    "req_id": r.req_id,
                    "title": r.title,
                    "text": r.req_text,
                    "market": r.market,
                    "product": r.product,
                    "entities": r.key_entities or [],
                    "analysis_id": a.analysis_id if a else None,
                    "analysis_status": a.status if a else None,
                }
            )
    return out


def list_analyses() -> list[dict]:
    with session_scope() as s:
        return [
            {
                "analysis_id": a.analysis_id,
                "req_id": a.req_id,
                "status": a.status,
                "version": a.version_no,
                "services": a.affected_services,
            }
            for a in s.scalars(
                select(models.ImpactAnalysis).order_by(models.ImpactAnalysis.analysis_id.desc())
            )
        ]


def list_stories() -> list[dict]:
    with session_scope() as s:
        return [
            {
                "story_id": x.story_id,
                "title": x.title,
                "status": x.status,
                "version": x.version_no,
                "work_item": x.ado_work_item_id,
                "analysis_id": x.analysis_id,
            }
            for x in s.scalars(select(models.UserStory).order_by(models.UserStory.story_id.desc()))
        ]


def list_code_changes(story_id: int | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(models.CodeChange).order_by(models.CodeChange.change_id.desc())
        if story_id:
            q = q.where(models.CodeChange.story_id == story_id)
        return [
            {
                "change_id": c.change_id,
                "story_id": c.story_id,
                "file": c.file_path,
                "status": c.status,
                "version": c.version_no,
                "diff": c.unified_diff,
                "adopted_path": c.adopted_path,
            }
            for c in s.scalars(q)
        ]


def list_tests(story_id: int) -> list[dict]:
    with session_scope() as s:
        return [
            {
                "test_id": t.test_id,
                "title": t.title,
                "phase": t.phase,
                "type": t.test_type,
                "priority": t.priority,
                "automated": t.automated,
                "steps": t.steps,
                "expected": t.expected_result,
                "status": t.status,
            }
            for t in s.scalars(
                select(models.TestScenario)
                .where(models.TestScenario.story_id == story_id)
                .order_by(models.TestScenario.test_id)
            )
        ]


def list_releases() -> list[dict]:
    with session_scope() as s:
        out = []
        for r in s.scalars(select(models.Release).order_by(models.Release.release_id)):
            n = len(
                s.scalars(
                    select(models.ReleaseChange).where(
                        models.ReleaseChange.release_id == r.release_id
                    )
                ).all()
            )
            out.append(
                {
                    "release_id": r.release_id,
                    "ref": r.ado_release_ref,
                    "name": r.name,
                    "completed_at": r.completed_at,
                    "status": r.update_status,
                    "changes": n,
                }
            )
        return out


def latest_sources(artifact_type: str, artifact_id: int) -> list[dict]:
    with session_scope() as s:
        req = s.scalars(
            select(models.ApprovalRequest)
            .where(
                models.ApprovalRequest.artifact_type == artifact_type,
                models.ApprovalRequest.artifact_id == artifact_id,
            )
            .order_by(models.ApprovalRequest.approval_id.desc())
        ).first()
        return list(req.source_refs or []) if req else []


def review_history(artifact_type: str, artifact_id: int) -> list[dict]:
    with session_scope() as s:
        return [
            {"decision": r.decision, "comments": r.comments, "decided_at": r.decided_at}
            for r in s.scalars(
                select(models.ApprovalRequest)
                .where(
                    models.ApprovalRequest.artifact_type == artifact_type,
                    models.ApprovalRequest.artifact_id == artifact_id,
                )
                .order_by(models.ApprovalRequest.approval_id)
            )
        ]


def artifact_detail(artifact_type: str, artifact_id: int) -> dict:
    """Everything a reviewer needs to see, as plain data."""
    kind = ARTIFACTS[artifact_type]
    with session_scope() as s:
        a = s.get(kind.model, artifact_id)
        d: dict = {
            "type": artifact_type,
            "id": artifact_id,
            "label": kind.label,
            "status": getattr(a, "status", None),
        }
        if artifact_type == "IMPACT_ANALYSIS":
            req = s.get(models.BusinessRequirement, a.req_id)
            d.update(
                requirement=req.req_text,
                entities=req.key_entities or [],
                affected_services=a.affected_services,
                dependencies=a.dependencies,
                complexity=a.complexity,
                risk=a.risk,
                effort_days=float(a.effort_days),
                testing_strategy=a.testing_strategy,
                unknown_services=a.unknown_services,
                version=a.version_no,
            )
        elif artifact_type == "USER_STORY":
            d.update(
                title=a.title,
                description=a.description,
                criteria=a.acceptance_criteria,
                invest=a.invest_check,
                version=a.version_no,
                work_item=a.ado_work_item_id,
            )
        elif artifact_type == "CODE_CHANGE":
            d.update(file=a.file_path, diff=a.unified_diff, version=a.version_no)
        elif artifact_type == "TEST_SCENARIO":
            d.update(
                title=a.title,
                phase=a.phase,
                test_type=a.test_type,
                priority=a.priority,
                automated=a.automated,
                steps=a.steps,
                expected=a.expected_result,
            )
        elif artifact_type in ("SERVICE_DOCUMENT", "DOC_UPDATE"):
            versions = DocumentRepository.versions(s, a.doc_id)
            d.update(
                service=a.service_name,
                content=a.content,
                version=a.current_version,
                previous=versions[-2].content if len(versions) > 1 else "",
            )
    d["sources"] = latest_sources(artifact_type, artifact_id)
    d["history"] = review_history(artifact_type, artifact_id)
    return d


def notifications(role: str, limit: int = 15) -> list[dict]:
    with session_scope() as s:
        return [
            {"message": n.message, "time": n.created_at, "event": n.event}
            for n in NotificationRepository.for_role(s, role, limit)
        ]


def edit_test_case(test_id: int, fields: dict, actor: str, user_id: int) -> None:
    """QA Lead edits a test case while it is under review (audited)."""
    from app.db.repositories import AuditRepository

    allowed = {"title", "priority", "steps", "expected_result", "automated", "phase", "test_type"}
    with session_scope() as s:
        t = s.get(models.TestScenario, test_id)
        if t.status not in ("PENDING_REVIEW", "CHANGES_REQUESTED", "DRAFT"):
            raise ValueError(f"Test case is {t.status} and can no longer be edited")
        for k, v in fields.items():
            if k in allowed:
                setattr(t, k, v)
        AuditRepository.add(
            s,
            actor,
            "TEST_CASE_EDITED",
            "TEST_SCENARIO",
            test_id,
            {k: str(v)[:200] for k, v in fields.items() if k in allowed},
            user_id=user_id,
        )
