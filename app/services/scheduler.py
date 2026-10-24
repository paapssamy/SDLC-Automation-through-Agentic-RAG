"""APScheduler job that polls ADO for completed releases (module 3.8)."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.agents.release_monitor_agent import ReleaseMonitorAgent

log = logging.getLogger(__name__)


class ReleaseScheduler:
    def __init__(self, monitor: ReleaseMonitorAgent, minutes: int = 5):
        self.monitor, self.minutes = monitor, minutes
        self._sched: BackgroundScheduler | None = None

    def catch_up(self) -> list[dict]:
        """Replay releases missed during downtime (oldest first). Called at start-up."""
        return self.monitor.poll()

    def start(self, catch_up: bool = True) -> None:
        if self._sched and self._sched.running:
            return
        if catch_up:
            try:
                self.catch_up()
            except Exception:
                log.exception("catch-up poll failed")
        self._sched = BackgroundScheduler(daemon=True)
        self._sched.add_job(
            self._safe_poll,
            "interval",
            minutes=self.minutes,
            id="release_poll",
            max_instances=1,
            coalesce=True,
        )
        self._sched.start()

    def _safe_poll(self) -> None:
        try:
            self.monitor.poll()
        except Exception:
            log.exception("scheduled poll failed")

    def run_now(self) -> list[dict]:
        return self.monitor.poll()

    def stop(self) -> None:
        if self._sched and self._sched.running:
            self._sched.shutdown(wait=False)

    @property
    def running(self) -> bool:
        return bool(self._sched and self._sched.running)
