"""TestRunnerAdapter (Adapter pattern) with a deterministic MockRunner and a LocalCommandRunner."""

from __future__ import annotations

import shlex
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings


@dataclass
class RunOutcome:
    status: str  # PASS | FAIL | BLOCKED
    log: str


class TestRunnerAdapter(ABC):
    __test__ = False  # not a pytest class

    @abstractmethod
    def run(self, scenarios: list[dict], run_no: int) -> dict[int, RunOutcome]:
        """Run the automated scenarios; returns {test_id: outcome}."""


class MockRunner(TestRunnerAdapter):
    """Deterministic demo behaviour: BOUNDARY tests expose a 'defect' on run 1 and pass on re-run."""

    def run(self, scenarios, run_no):
        out = {}
        for s in scenarios:
            if s["test_type"] == "BOUNDARY" and run_no == 1:
                out[s["test_id"]] = RunOutcome(
                    "FAIL",
                    f"[mock] {s['title']}: expected boundary value to be accepted, "
                    "got rejection (simulated defect DEF-101)",
                )
            else:
                out[s["test_id"]] = RunOutcome(
                    "PASS", f"[mock] {s['title']}: all assertions passed"
                )
        return out


class LocalCommandRunner(TestRunnerAdapter):
    """Runs a configured command (e.g. `mvn -q test`) once in the test environment folder."""

    def __init__(self, command: str, cwd: Path, timeout: int = 600):
        self.command, self.cwd, self.timeout = command, Path(cwd), timeout

    def run(self, scenarios, run_no):
        if not self.cwd.exists() or not any(self.cwd.iterdir()):
            msg = f"Test environment folder {self.cwd} is missing or empty"
            return {s["test_id"]: RunOutcome("BLOCKED", msg) for s in scenarios}
        try:
            proc = subprocess.run(
                shlex.split(self.command),
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            status = "PASS" if proc.returncode == 0 else "FAIL"
            log = (proc.stdout + "\n" + proc.stderr)[-4000:]
        except FileNotFoundError:
            status, log = "BLOCKED", f"Command not found: {self.command} (is Maven installed?)"
        except subprocess.TimeoutExpired:
            status, log = "FAIL", f"Command timed out after {self.timeout}s"
        return {s["test_id"]: RunOutcome(status, log) for s in scenarios}


def get_runner(settings: Settings | None = None) -> TestRunnerAdapter:
    s = settings or get_settings()
    if s.test_runner == "local_command":
        return LocalCommandRunner(s.test_runner_command, s.workspace_dir / "test_env")
    return MockRunner()
