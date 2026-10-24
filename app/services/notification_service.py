"""Notifications (Observer pattern): a tiny event bus with a subscriber that stores in-app messages."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable

from app.db.base import session_scope
from app.db.repositories import NotificationRepository

log = logging.getLogger(__name__)

SUBMITTED = "ARTIFACT_SUBMITTED"
DECIDED = "ARTIFACT_DECIDED"
RELEASE_UPDATED = "RELEASE_UPDATED"


class EventBus:
    """Observer: handlers subscribe to an event name; publish() calls them all."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[dict], None]]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable[[dict], None]) -> None:
        self._handlers[event].append(handler)

    def publish(self, event: str, payload: dict) -> None:
        for h in self._handlers[event]:
            try:
                h(payload)
            except Exception:  # a failing observer must never break the workflow
                log.exception("notification handler failed for %s", event)


class NotificationService:
    """Stores an in-app notification for the role that must act next."""

    def __init__(self, bus: EventBus) -> None:
        bus.subscribe(SUBMITTED, self._on_submitted)
        bus.subscribe(DECIDED, self._on_decided)
        bus.subscribe(RELEASE_UPDATED, self._on_release)

    def _store(self, role: str, event: str, message: str) -> None:
        with session_scope() as s:
            NotificationRepository.add(s, role, event, message)

    def _on_submitted(self, p: dict) -> None:
        self._store(
            p["checker_role"],
            SUBMITTED,
            f"{p['label']} #{p['artifact_id']} is waiting for your review",
        )

    def _on_decided(self, p: dict) -> None:
        self._store(
            p["maker_role"],
            DECIDED,
            f"{p['label']} #{p['artifact_id']} was {p['decision']} by {p['reviewer']}",
        )

    def _on_release(self, p: dict) -> None:
        self._store(
            "TECHNICAL_LEAD",
            RELEASE_UPDATED,
            f"Release {p['release']} updated {p['sections']} documentation section(s)",
        )
