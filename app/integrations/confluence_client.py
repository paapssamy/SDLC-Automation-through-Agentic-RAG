"""ConfluenceClient interface (Adapter) + Mock (writes HTML files) + Live (REST API)."""

from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod

from app.config import Settings, get_settings


def markdown_to_html(md: str) -> str:
    """Very small Markdown -> HTML converter (headings, bullets, paragraphs)."""
    out, in_list = [], False
    for line in md.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{html.escape(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{html.escape(m.group(2))}</h{n}>")
        elif line.strip():
            out.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


class ConfluenceClient(ABC):
    @abstractmethod
    def publish_page(self, title: str, body_html: str, version_comment: str) -> str:
        """Create or update the page. Returns its location (path or URL)."""


class MockConfluenceClient(ConfluenceClient):
    """Writes HTML files to workspace/confluence/ (one file per page, versions appended)."""

    def __init__(self, settings: Settings | None = None):
        self.dir = (settings or get_settings()).workspace_dir / "confluence"

    def publish_page(self, title, body_html, version_comment):
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / (re.sub(r"[^\w.-]+", "_", title) + ".html")
        version = 1
        if path.exists():
            m = re.search(r"data-version=\"(\d+)\"", path.read_text(encoding="utf-8"))
            version = int(m.group(1)) + 1 if m else 2
        path.write_text(
            f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f'</head><body data-version="{version}"><h1>{html.escape(title)}</h1>'
            f"<p><em>Version {version}: {html.escape(version_comment)}</em></p>\n{body_html}"
            f"</body></html>",
            encoding="utf-8",
        )
        return str(path)


class LiveConfluenceClient(ConfluenceClient):
    def __init__(self, settings: Settings | None = None):
        import requests

        s = settings or get_settings()
        if not (
            s.confluence_base_url
            and s.confluence_space
            and s.confluence_user
            and s.confluence_api_token
        ):
            raise ValueError(
                "CONFLUENCE_BASE_URL / SPACE / USER / API_TOKEN must be set for live mode"
            )
        self.base = s.confluence_base_url.rstrip("/")
        self.space = s.confluence_space
        self._http = requests.Session()
        self._http.auth = (s.confluence_user, s.confluence_api_token)

    def publish_page(self, title, body_html, version_comment):
        q = self._http.get(
            f"{self.base}/rest/api/content",
            params={"title": title, "spaceKey": self.space, "expand": "version"},
            timeout=30,
        )
        q.raise_for_status()
        results = q.json().get("results", [])
        body = {
            "type": "page",
            "title": title,
            "space": {"key": self.space},
            "body": {"storage": {"value": body_html, "representation": "storage"}},
        }
        if results:
            page = results[0]
            body["version"] = {"number": page["version"]["number"] + 1, "message": version_comment}
            r = self._http.put(f"{self.base}/rest/api/content/{page['id']}", json=body, timeout=30)
        else:
            body["version"] = {"message": version_comment}
            r = self._http.post(f"{self.base}/rest/api/content", json=body, timeout=30)
        r.raise_for_status()
        return f"{self.base}{r.json().get('_links', {}).get('webui', '')}"


def get_confluence_client(settings: Settings | None = None) -> ConfluenceClient:
    s = settings or get_settings()
    return LiveConfluenceClient(s) if s.confluence_mode == "live" else MockConfluenceClient(s)
