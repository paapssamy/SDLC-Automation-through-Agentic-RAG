"""Login and role-based access control (RBAC). Enforced in the service layer."""

from __future__ import annotations

from dataclasses import dataclass

import bcrypt

from app.db.base import session_scope
from app.db.repositories import AuditRepository, UserRepository
from app.errors import AccessDeniedError


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str
    full_name: str
    role: str


def authenticate(username: str, password: str) -> CurrentUser | None:
    with session_scope() as s:
        u = UserRepository.by_username(s, username)
        ok = bool(u and u.is_active and bcrypt.checkpw(password.encode(), u.password_hash.encode()))
        AuditRepository.add(
            s, username, "LOGIN_SUCCESS" if ok else "LOGIN_FAILED", user_id=u.user_id if u else None
        )
        if not ok or u is None:
            return None
        return CurrentUser(u.user_id, u.username, u.full_name, u.role)


def require_role(user: CurrentUser | None, *roles: str) -> None:
    """Raise AccessDeniedError unless `user` has one of `roles`."""
    if user is None or user.role not in roles:
        who = user.username if user else "anonymous"
        raise AccessDeniedError(f"Access denied for {who}: requires {' or '.join(roles)}")


def audit_denied(user: CurrentUser | None, what: str) -> None:
    with session_scope() as s:
        AuditRepository.add(
            s,
            user.username if user else "anonymous",
            "ACCESS_DENIED",
            details={"what": what},
            user_id=user.user_id if user else None,
        )
