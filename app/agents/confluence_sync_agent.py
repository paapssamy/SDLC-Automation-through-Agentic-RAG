"""Agent 10 – Confluence Sync Agent (module 3.9).

Publishes approved documentation to Confluence (mock: HTML files in workspace/confluence/).
Not an LLM agent; every publish is audited.
"""

from __future__ import annotations

from app.db import models
from app.db.base import session_scope
from app.db.repositories import AuditRepository
from app.integrations.confluence_client import ConfluenceClient, markdown_to_html


class ConfluenceSyncAgent:
    name = "ConfluenceSyncAgent"

    def __init__(self, client: ConfluenceClient):
        self.client = client

    def publish_document(self, doc_id: int, version_comment: str = "") -> str:
        with session_scope() as s:
            doc = s.get(models.ServiceDocument, doc_id)
            title, content, version = doc.service_name, doc.content, doc.current_version
        comment = version_comment or f"Version {version} approved"
        location = self.client.publish_page(title, markdown_to_html(content), comment)
        with session_scope() as s:
            AuditRepository.add(
                s,
                self.name,
                "CONFLUENCE_PUBLISHED",
                "SERVICE_DOCUMENT",
                doc_id,
                {"page": title, "version": version, "location": location, "comment": comment},
            )
        return location
