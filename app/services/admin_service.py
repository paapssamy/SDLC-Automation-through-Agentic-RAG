"""Administration: users/roles, integration settings (no secrets) and audit-log viewer."""

from __future__ import annotations

import re
from datetime import datetime

from app.db import models
from app.db.base import session_scope
from app.db.init_db import hash_password
from app.db.repositories import AuditRepository, IntegrationRepository, UserRepository
from app.services.auth import CurrentUser, audit_denied, require_role

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,60}$")


def _admin(user: CurrentUser | None) -> None:
    try:
        require_role(user, "ADMIN")
    except Exception:
        audit_denied(user, "administration")
        raise


def list_users(user: CurrentUser) -> list[dict]:
    _admin(user)
    with session_scope() as s:
        return [
            {
                "user_id": u.user_id,
                "username": u.username,
                "full_name": u.full_name,
                "role": u.role,
                "is_active": u.is_active,
            }
            for u in UserRepository.all(s)
        ]


def create_user(user: CurrentUser, username: str, full_name: str, role: str, password: str) -> int:
    _admin(user)
    with session_scope() as s:
        u = models.User(
            username=username,
            full_name=full_name,
            email=f"{username}@demo.local",
            role=role,
            password_hash=hash_password(password),
        )
        s.add(u)
        s.flush()
        AuditRepository.add(
            s,
            user.username,
            "USER_CREATED",
            "USER",
            u.user_id,
            {"username": username, "role": role},
            user_id=user.user_id,
        )
        return u.user_id


def set_user_role(user: CurrentUser, target_id: int, role: str, active: bool = True) -> None:
    _admin(user)
    with session_scope() as s:
        u = s.get(models.User, target_id)
        u.role, u.is_active = role, active
        AuditRepository.add(
            s,
            user.username,
            "USER_UPDATED",
            "USER",
            target_id,
            {"role": role, "active": active},
            user_id=user.user_id,
        )


def list_integrations(user: CurrentUser) -> list[dict]:
    _admin(user)
    with session_scope() as s:
        return [
            {
                "system": c.system_name,
                "base_url": c.base_url,
                "project_or_space": c.project_or_space,
                "secret_ref": c.secret_ref,
                "settings": c.settings,
            }
            for c in s.query(models.IntegrationConfig).order_by(models.IntegrationConfig.config_id)
        ]


def update_integration(
    user: CurrentUser,
    system: str,
    base_url: str | None,
    project_or_space: str | None,
    secret_ref: str | None,
) -> None:
    """`secret_ref` must be the NAME of an environment variable – never the secret itself."""
    _admin(user)
    if secret_ref and not _ENV_NAME.match(secret_ref):
        raise ValueError(
            "secret_ref must be an environment variable NAME (e.g. ADO_PAT), never the secret value"
        )
    with session_scope() as s:
        cfg = IntegrationRepository.get(s, system)
        cfg.base_url, cfg.project_or_space, cfg.secret_ref = base_url, project_or_space, secret_ref
        AuditRepository.add(
            s,
            user.username,
            "INTEGRATION_UPDATED",
            "INTEGRATION",
            cfg.config_id,
            {"system": system},
            user_id=user.user_id,
        )


def audit_logs(
    user: CurrentUser,
    actor: str | None = None,
    action: str | None = None,
    artifact_type: str | None = None,
    since: datetime | None = None,
    limit: int = 500,
) -> list[dict]:
    _admin(user)
    with session_scope() as s:
        rows = AuditRepository.query(s, actor, action, artifact_type, since, limit)
        return [
            {
                "log_id": r.log_id,
                "time": r.created_at,
                "actor": r.actor,
                "action": r.action,
                "artifact_type": r.artifact_type,
                "artifact_id": r.artifact_id,
                "details": r.details,
            }
            for r in rows
        ]
