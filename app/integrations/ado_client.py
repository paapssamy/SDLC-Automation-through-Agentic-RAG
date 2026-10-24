"""AdoClient interface (Adapter) + MockAdoClient (default) + LiveAdoClient (Azure DevOps REST 7.1).

The mock reads fixtures from sample_data/mock_ado and the Java sample repository, so the whole
demo runs without any company account. Secrets (PAT) come only from the environment.
"""

from __future__ import annotations

import base64
import json
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings, get_settings


@dataclass
class ReleaseChangeInfo:
    work_item_id: str
    commit_id: str
    file_path: str
    code_diff: str
    class_name: str = ""


@dataclass
class ReleaseInfo:
    ref: str
    name: str
    completed_at: str
    changes: list[ReleaseChangeInfo] = field(default_factory=list)


class AdoClient(ABC):
    """Adapter: the application talks to this interface only."""

    @abstractmethod
    def create_work_item(
        self, title: str, description: str, acceptance_criteria: list[str]
    ) -> str: ...

    @abstractmethod
    def list_completed_releases(self) -> list[ReleaseInfo]:
        """Completed releases ordered by completion time (oldest first)."""

    @abstractmethod
    def list_repo_files(self) -> list[str]: ...

    @abstractmethod
    def get_file(self, path: str) -> str: ...

    @abstractmethod
    def push_branch(self, branch: str, files: dict[str, str]) -> str:
        """Create a branch containing `files` (path -> content). Returns a location/URL."""

    @abstractmethod
    def upload_test_results(self, plan_name: str, results: list[dict]) -> str: ...


class MockAdoClient(AdoClient):
    def __init__(self, settings: Settings | None = None, releases_file: Path | None = None):
        self.settings = settings or get_settings()
        self.repo = self.settings.sample_data_dir / "java-payments-app"
        self.releases_file = (
            releases_file or self.settings.sample_data_dir / "mock_ado" / "releases.json"
        )
        self.state_dir = self.settings.workspace_dir / "mock_ado"
        self._extra_releases: list[ReleaseInfo] = []

    # -- work items ---------------------------------------------------------------------
    def create_work_item(self, title, description, acceptance_criteria):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        f = self.state_dir / "work_items.json"
        items = json.loads(f.read_text()) if f.exists() else []
        wid = str(5000 + len(items) + 1)
        items.append(
            {
                "id": wid,
                "title": title,
                "description": description,
                "acceptance_criteria": acceptance_criteria,
            }
        )
        f.write_text(json.dumps(items, indent=2))
        return wid

    # -- releases ---------------------------------------------------------------------------
    def add_release(self, release: ReleaseInfo) -> None:
        """Test helper: simulate a new completed release."""
        self._extra_releases.append(release)

    def list_completed_releases(self):
        data = json.loads(self.releases_file.read_text(encoding="utf-8"))["releases"]
        out = [
            ReleaseInfo(
                r["id"],
                r["name"],
                r["completed_at"],
                [
                    ReleaseChangeInfo(
                        c["work_item_id"],
                        c["commit_id"],
                        c["file_path"],
                        c["code_diff"],
                        c.get("class_name", ""),
                    )
                    for c in r["changes"]
                ],
            )
            for r in data
        ]
        out += self._extra_releases
        return sorted(out, key=lambda r: r.completed_at)

    # -- repos --------------------------------------------------------------------------------
    def list_repo_files(self):
        return sorted(
            str(p.relative_to(self.repo)).replace("\\", "/") for p in self.repo.rglob("*.java")
        )

    def get_file(self, path):
        return (self.repo / path).read_text(encoding="utf-8")

    def push_branch(self, branch, files):
        dest = self.settings.workspace_dir / "branches" / branch
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.repo, dest)
        for path, content in files.items():
            target = dest / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return str(dest)

    def upload_test_results(self, plan_name, results):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        f = self.state_dir / "test_runs.json"
        runs = json.loads(f.read_text()) if f.exists() else []
        run_id = f"TR-{len(runs) + 1}"
        runs.append({"id": run_id, "plan": plan_name, "results": results})
        f.write_text(json.dumps(runs, indent=2))
        return run_id


class LiveAdoClient(AdoClient):
    """Azure DevOps REST API 7.1. Needs ADO_ORG_URL, ADO_PROJECT and ADO_PAT in the environment."""

    API = "api-version=7.1"

    def __init__(self, settings: Settings | None = None, repo_name: str | None = None):
        import requests

        s = settings or get_settings()
        if not (s.ado_org_url and s.ado_project and s.ado_pat):
            raise ValueError("ADO_ORG_URL, ADO_PROJECT and ADO_PAT must be set for live mode")
        self.base = s.ado_org_url.rstrip("/")
        self.project = s.ado_project
        self.repo = repo_name or s.ado_project
        self._http = requests.Session()
        token = base64.b64encode(f":{s.ado_pat}".encode()).decode()
        self._http.headers.update({"Authorization": f"Basic {token}"})

    def _url(self, path: str) -> str:
        sep = "&" if "?" in path else "?"
        return f"{self.base}/{self.project}/_apis/{path}{sep}{self.API}"

    def create_work_item(self, title, description, acceptance_criteria):
        ops = [
            {"op": "add", "path": "/fields/System.Title", "value": title},
            {"op": "add", "path": "/fields/System.Description", "value": description},
            {
                "op": "add",
                "path": "/fields/Microsoft.VSTS.Common.AcceptanceCriteria",
                "value": "<br>".join(acceptance_criteria),
            },
        ]
        r = self._http.post(
            self._url("wit/workitems/$User%20Story"),
            json=ops,
            headers={"Content-Type": "application/json-patch+json"},
            timeout=30,
        )
        r.raise_for_status()
        return str(r.json()["id"])

    def list_completed_releases(self):
        r = self._http.get(
            self._url("release/releases?statusFilter=active&$expand=environments"), timeout=30
        )
        r.raise_for_status()
        out = []
        for rel in r.json().get("value", []):
            out.append(
                ReleaseInfo(str(rel["id"]), rel.get("name", ""), rel.get("modifiedOn", ""), [])
            )
        return sorted(out, key=lambda x: x.completed_at)

    def list_repo_files(self):
        r = self._http.get(
            self._url(f"git/repositories/{self.repo}/items?recursionLevel=Full"), timeout=30
        )
        r.raise_for_status()
        return [i["path"].lstrip("/") for i in r.json()["value"] if i["path"].endswith(".java")]

    def get_file(self, path):
        r = self._http.get(
            self._url(f"git/repositories/{self.repo}/items?path=/{path}"), timeout=30
        )
        r.raise_for_status()
        return r.text

    def push_branch(self, branch, files):
        ref = self._http.get(
            self._url(f"git/repositories/{self.repo}/refs?filter=heads/main"), timeout=30
        )
        ref.raise_for_status()
        old_id = ref.json()["value"][0]["objectId"]
        changes = [
            {
                "changeType": "edit",
                "item": {"path": f"/{p}"},
                "newContent": {"content": c, "contentType": "rawtext"},
            }
            for p, c in files.items()
        ]
        body = {
            "refUpdates": [{"name": f"refs/heads/{branch}", "oldObjectId": "0" * 40}],
            "commits": [
                {
                    "comment": f"Generated change for {branch}",
                    "changes": changes,
                    "parents": [old_id],
                }
            ],
        }
        r = self._http.post(
            self._url(f"git/repositories/{self.repo}/pushes"), json=body, timeout=60
        )
        r.raise_for_status()
        return f"{self.base}/{self.project}/_git/{self.repo}?version=GB{branch}"

    def upload_test_results(self, plan_name, results):
        body = {"name": plan_name, "state": "InProgress"}
        r = self._http.post(self._url("test/runs"), json=body, timeout=30)
        r.raise_for_status()
        return str(r.json()["id"])


def get_ado_client(settings: Settings | None = None) -> AdoClient:
    s = settings or get_settings()
    return LiveAdoClient(s) if s.ado_mode == "live" else MockAdoClient(s)
