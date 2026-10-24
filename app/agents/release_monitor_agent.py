"""Agent 7 – Release Monitor Agent (module 3.8).

Polls ADO for completed releases, stores them (`release`, `release_change`), asks the
Incremental Doc Updater to refresh affected documentation and remembers
`last_processed_release_id` in integration_config. After downtime every missed release is
replayed in completion order (NFR-07). Not an LLM agent; every step is audited.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.agents.incremental_doc_updater import IncrementalDocUpdater
from app.db import models
from app.db.base import session_scope
from app.db.repositories import AuditRepository, IntegrationRepository
from app.integrations.ado_client import AdoClient
from app.services import notification_service as ev

log = logging.getLogger(__name__)


class ReleaseMonitorAgent:
    name = "ReleaseMonitorAgent"

    def __init__(self, ado: AdoClient, updater: IncrementalDocUpdater, bus: ev.EventBus):
        self.ado, self.updater, self.bus = ado, updater, bus

    # -- state -------------------------------------------------------------------------------
    @staticmethod
    def last_processed() -> str | None:
        with session_scope() as s:
            cfg = IntegrationRepository.get(s, "ADO")
            return (cfg.settings or {}).get("last_processed_release_id") if cfg else None

    @staticmethod
    def _set_last_processed(ref: str) -> None:
        with session_scope() as s:
            cfg = IntegrationRepository.get(s, "ADO")
            if cfg is None:
                cfg = models.IntegrationConfig(system_name="ADO", settings={})
                s.add(cfg)
            cfg.settings = {**(cfg.settings or {}), "last_processed_release_id": ref}
            flag_modified(cfg, "settings")

    # -- polling -----------------------------------------------------------------------------
    def poll(self, user_id: int | None = None) -> list[dict]:
        """Process every release newer than last_processed_release_id, oldest first."""
        releases = self.ado.list_completed_releases()
        last = self.last_processed()
        refs = [r.ref for r in releases]
        pending = releases[refs.index(last) + 1 :] if last in refs else releases
        summaries = []
        for rel in pending:
            summaries.append(self._process(rel, user_id))
            if summaries[-1]["status"] == "FAILED":
                break  # keep order: retry this release on the next poll
        return summaries

    def _process(self, rel, user_id: int | None) -> dict:
        with session_scope() as s:
            row = s.scalars(
                select(models.Release).where(models.Release.ado_release_ref == rel.ref)
            ).first()
            if row is None:
                row = models.Release(
                    ado_release_ref=rel.ref,
                    name=rel.name,
                    completed_at=datetime.fromisoformat(rel.completed_at)
                    if rel.completed_at
                    else None,
                    update_status="DETECTED",
                )
                s.add(row)
                s.flush()
                for c in rel.changes:
                    s.add(
                        models.ReleaseChange(
                            release_id=row.release_id,
                            work_item_id=c.work_item_id,
                            commit_id=c.commit_id,
                            file_path=c.file_path,
                            code_diff=c.code_diff,
                        )
                    )
                AuditRepository.add(
                    s,
                    self.name,
                    "RELEASE_DETECTED",
                    "RELEASE",
                    row.release_id,
                    {"ref": rel.ref, "changes": len(rel.changes)},
                )
            release_id = row.release_id
            if row.update_status == "DOCS_UPDATED":
                self._set_last_processed(rel.ref)
                return {
                    "release": rel.ref,
                    "status": "DOCS_UPDATED",
                    "sections": 0,
                    "skipped": True,
                }
            row.update_status = "PROCESSING"
        try:
            result = self.updater.update_release(release_id, user_id)
            status = "DOCS_UPDATED"
        except Exception as exc:
            log.exception("release %s failed", rel.ref)
            result, status = {"updated": [], "error": str(exc)[:300]}, "FAILED"
        with session_scope() as s:
            s.get(models.Release, release_id).update_status = status
            AuditRepository.add(
                s,
                self.name,
                f"RELEASE_{status}",
                "RELEASE",
                release_id,
                {"ref": rel.ref, **{k: v for k, v in result.items()}},
            )
        if status == "DOCS_UPDATED":
            self._set_last_processed(rel.ref)
            self.bus.publish(
                ev.RELEASE_UPDATED, {"release": rel.ref, "sections": len(result["updated"])}
            )
        return {
            "release": rel.ref,
            "status": status,
            "sections": len(result.get("updated", [])),
            "detail": result,
        }
