"""Repositories: small data-access classes, one per aggregate.

The audit repository is deliberately append-only (no update/delete methods); the database
trigger enforces the same rule.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models


class AuditRepository:
    """Append-only audit trail."""

    @staticmethod
    def add(
        session: Session,
        actor: str,
        action: str,
        artifact_type: str | None = None,
        artifact_id: int | None = None,
        details: dict | None = None,
        user_id: int | None = None,
    ) -> models.AuditLog:
        row = models.AuditLog(
            user_id=user_id,
            actor=actor,
            action=action,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            details=details or {},
        )
        session.add(row)
        return row

    @staticmethod
    def query(
        session: Session,
        actor: str | None = None,
        action: str | None = None,
        artifact_type: str | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[models.AuditLog]:
        q = select(models.AuditLog)
        if actor:
            q = q.where(models.AuditLog.actor == actor)
        if action:
            q = q.where(models.AuditLog.action == action)
        if artifact_type:
            q = q.where(models.AuditLog.artifact_type == artifact_type)
        if since:
            q = q.where(models.AuditLog.created_at >= since)
        return list(session.scalars(q.order_by(models.AuditLog.log_id.desc()).limit(limit)))


class UserRepository:
    @staticmethod
    def by_username(session: Session, username: str) -> models.User | None:
        return session.scalars(select(models.User).where(models.User.username == username)).first()

    @staticmethod
    def by_role(session: Session, role: str) -> list[models.User]:
        return list(session.scalars(select(models.User).where(models.User.role == role)))

    @staticmethod
    def all(session: Session) -> list[models.User]:
        return list(session.scalars(select(models.User).order_by(models.User.user_id)))


class DocumentRepository:
    @staticmethod
    def all(session: Session) -> list[models.ServiceDocument]:
        return list(
            session.scalars(
                select(models.ServiceDocument).order_by(models.ServiceDocument.service_name)
            )
        )

    @staticmethod
    def by_name(session: Session, name: str, market: str, product: str):
        return session.scalars(
            select(models.ServiceDocument)
            .where(
                models.ServiceDocument.service_name == name,
                models.ServiceDocument.market == market,
                models.ServiceDocument.product == product,
            )
            .order_by(models.ServiceDocument.doc_id.desc())
        ).first()

    @staticmethod
    def versions(session: Session, doc_id: int) -> list[models.DocumentVersion]:
        return list(
            session.scalars(
                select(models.DocumentVersion)
                .where(models.DocumentVersion.doc_id == doc_id)
                .order_by(models.DocumentVersion.version_no)
            )
        )


class NotificationRepository:
    @staticmethod
    def add(session: Session, role: str, event: str, message: str) -> None:
        session.add(models.Notification(role=role, event=event, message=message))

    @staticmethod
    def for_role(session: Session, role: str, limit: int = 30) -> list[models.Notification]:
        return list(
            session.scalars(
                select(models.Notification)
                .where(models.Notification.role == role)
                .order_by(models.Notification.notification_id.desc())
                .limit(limit)
            )
        )


class IntegrationRepository:
    @staticmethod
    def get(session: Session, system: str) -> models.IntegrationConfig | None:
        return session.scalars(
            select(models.IntegrationConfig).where(models.IntegrationConfig.system_name == system)
        ).first()


def status_counts(session: Session, model) -> dict[str, int]:
    rows = session.execute(select(model.status, func.count()).group_by(model.status)).all()
    return {r[0]: r[1] for r in rows}
