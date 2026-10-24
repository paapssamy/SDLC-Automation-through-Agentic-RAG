"""Agent 9 – ADO Repos Connector (modules 3.5 / 3.8).

Not an LLM agent: it fetches source files from the repository and pushes an approved change to
a new branch. It still records an audit entry for every action.
"""

from __future__ import annotations

from app.db.base import session_scope
from app.db.repositories import AuditRepository
from app.integrations.ado_client import AdoClient


class AdoReposConnector:
    name = "AdoReposConnector"

    def __init__(self, ado: AdoClient):
        self.ado = ado

    def _audit(
        self,
        action: str,
        details: dict,
        artifact_type: str | None = None,
        artifact_id: int | None = None,
        user_id: int | None = None,
    ) -> None:
        with session_scope() as s:
            AuditRepository.add(
                s, self.name, action, artifact_type, artifact_id, details, user_id=user_id
            )

    def fetch_class_files(self, class_names: list[str], limit: int = 3) -> dict[str, str]:
        """Source files whose file name matches one of the class names (path -> content)."""
        wanted = {f"{c}.java" for c in class_names}
        files = {}
        for path in self.ado.list_repo_files():
            if path.rsplit("/", 1)[-1] in wanted:
                files[path] = self.ado.get_file(path)
                if len(files) >= limit:
                    break
        self._audit("FETCH_SOURCE_FILES", {"requested": class_names, "found": list(files)})
        return files

    def adopt(
        self,
        story_id: int,
        files: dict[str, str],
        user_id: int | None = None,
        change_ids: list[int] | None = None,
    ) -> str:
        """Push approved changes to branch `story-<id>` (mock: workspace/branches/story-<id>/)."""
        location = self.ado.push_branch(f"story-{story_id}", files)
        self._audit(
            "ADOPT_CODE",
            {
                "branch": f"story-{story_id}",
                "files": list(files),
                "location": location,
                "change_ids": change_ids or [],
            },
            "USER_STORY",
            story_id,
            user_id,
        )
        return location
