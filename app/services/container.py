"""Wires clients, agents and services together (simple dependency container)."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy import select

from app.agents.ado_repos_connector import AdoReposConnector
from app.agents.code_generation_agent import CodeGenerationAgent
from app.agents.confluence_sync_agent import ConfluenceSyncAgent
from app.agents.impact_analysis_agent import ImpactAnalysisAgent
from app.agents.incremental_doc_updater import IncrementalDocUpdater
from app.agents.java_parser_agent import JavaParserAgent
from app.agents.release_monitor_agent import ReleaseMonitorAgent
from app.agents.story_generator_agent import StoryGeneratorAgent
from app.agents.test_execution_agent import TestExecutionAgent
from app.agents.test_generator_agent import TestGeneratorAgent
from app.config import Settings, get_settings
from app.db import models
from app.db.base import session_scope
from app.db.repositories import AuditRepository
from app.integrations.ado_client import AdoClient, get_ado_client
from app.integrations.confluence_client import ConfluenceClient, get_confluence_client
from app.integrations.test_runner import TestRunnerAdapter, get_runner
from app.llm.client import LLMClient
from app.llm.factory import get_llm
from app.rag.embedding_service import get_embedder
from app.rag.retriever import Retriever
from app.services.approval_service import ApprovalService
from app.services.notification_service import EventBus, NotificationService
from app.services.scheduler import ReleaseScheduler
from app.services.workflow_orchestrator import WorkflowOrchestrator

log = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    llm: LLMClient
    ado: AdoClient
    confluence: ConfluenceClient
    approvals: ApprovalService
    bus: EventBus
    notifications: NotificationService
    retriever: Retriever
    orchestrator: WorkflowOrchestrator
    monitor: ReleaseMonitorAgent
    updater: IncrementalDocUpdater
    scheduler: ReleaseScheduler
    confluence_sync: ConfluenceSyncAgent
    exec_agent: TestExecutionAgent
    repos: AdoReposConnector


def build_services(
    llm: LLMClient | None = None,
    ado: AdoClient | None = None,
    confluence: ConfluenceClient | None = None,
    runner: TestRunnerAdapter | None = None,
    settings: Settings | None = None,
) -> Services:
    cfg = settings or get_settings()
    llm = llm or get_llm(cfg)
    ado = ado or get_ado_client(cfg)
    confluence = confluence or get_confluence_client(cfg)
    runner = runner or get_runner(cfg)

    bus = EventBus()
    notifications = NotificationService(bus)
    approvals = ApprovalService(bus)
    retriever = Retriever(settings=cfg)
    repos = AdoReposConnector(ado)
    sync = ConfluenceSyncAgent(confluence)

    doc_agent = JavaParserAgent(llm, retriever, approvals)
    impact = ImpactAnalysisAgent(llm, retriever, approvals)
    story = StoryGeneratorAgent(llm, retriever, approvals)
    code = CodeGenerationAgent(llm, retriever, approvals, repos)
    tests = TestGeneratorAgent(llm, retriever, approvals)
    execa = TestExecutionAgent(runner, ado, approvals)
    updater = IncrementalDocUpdater(llm, retriever, approvals)
    monitor = ReleaseMonitorAgent(ado, updater, bus)
    scheduler = ReleaseScheduler(monitor, cfg.release_poll_minutes)

    # ---- post-decision hooks (run after the approval is committed) -------------------------
    def story_approved(story_id: int, reviewer) -> None:
        """IT-02: create the ADO work item and store its id."""
        with session_scope() as s:
            st = s.get(models.UserStory, story_id)
            title, desc, crit = st.title, st.description, list(st.acceptance_criteria)
        wid = ado.create_work_item(title, desc, crit)
        with session_scope() as s:
            s.get(models.UserStory, story_id).ado_work_item_id = wid
            AuditRepository.add(
                s,
                "AdoClient",
                "ADO_WORK_ITEM_CREATED",
                "USER_STORY",
                story_id,
                {"work_item_id": wid},
                user_id=reviewer.user_id,
            )

    def doc_approved(doc_id: int, reviewer) -> None:
        """Publish approved documentation to Confluence; supersede older published versions."""
        sync.publish_document(doc_id)
        with session_scope() as s:
            d = s.get(models.ServiceDocument, doc_id)
            old = list(
                s.scalars(
                    select(models.ServiceDocument).where(
                        models.ServiceDocument.service_name == d.service_name,
                        models.ServiceDocument.market == d.market,
                        models.ServiceDocument.product == d.product,
                        models.ServiceDocument.status == "PUBLISHED",
                        models.ServiceDocument.doc_id != doc_id,
                    )
                )
            )
            old_ids = [o.doc_id for o in old]
        approvals.publish("SERVICE_DOCUMENT", doc_id, "ConfluenceSyncAgent", reviewer.user_id)
        for oid in old_ids:
            approvals.supersede("SERVICE_DOCUMENT", oid)

    def doc_update_approved(doc_id: int, reviewer) -> None:
        with session_scope() as s:
            v = s.get(models.ServiceDocument, doc_id).current_version
        sync.publish_document(
            doc_id, f"Release update – version {v} approved by {reviewer.username}"
        )

    def doc_update_rejected(doc_id: int, reviewer) -> None:
        revert_document(doc_id, reviewer.username)

    approvals.register_hook("USER_STORY", story_approved)
    approvals.register_hook("SERVICE_DOCUMENT", doc_approved)
    approvals.register_hook("DOC_UPDATE", doc_update_approved)
    approvals.register_hook("DOC_UPDATE", doc_update_rejected, ("REJECTED", "CHANGES_REQUESTED"))

    orch = WorkflowOrchestrator(approvals, doc_agent, impact, story, code, tests, execa, repos)
    return Services(
        cfg,
        llm,
        ado,
        confluence,
        approvals,
        bus,
        notifications,
        retriever,
        orch,
        monitor,
        updater,
        scheduler,
        sync,
        execa,
        repos,
    )


def revert_document(doc_id: int, actor: str) -> int:
    """Rejected release update: restore the previous text as a NEW version (history is kept)."""
    with session_scope() as s:
        doc = s.get(models.ServiceDocument, doc_id)
        versions = list(
            s.scalars(
                select(models.DocumentVersion)
                .where(models.DocumentVersion.doc_id == doc_id)
                .order_by(models.DocumentVersion.version_no)
            )
        )
        if len(versions) < 2:
            return doc.current_version
        prev = versions[-2]
        doc.current_version += 1
        doc.content, doc.content_hash = (
            prev.content,
            hashlib.sha256(prev.content.encode()).hexdigest(),
        )
        doc.embedding = get_embedder().embed(f"{doc.service_name}\n{prev.content}")
        s.add(
            models.DocumentVersion(
                doc_id=doc_id,
                release_id=None,
                version_no=doc.current_version,
                content=prev.content,
                change_summary=f"Reverted to version {prev.version_no} (update rejected by {actor})",
            )
        )
        AuditRepository.add(
            s, actor, "DOC_REVERTED", "SERVICE_DOCUMENT", doc_id, {"to_version": prev.version_no}
        )
        return doc.current_version


_services: Services | None = None


def get_services() -> Services:
    """Process-wide instance (used by the Streamlit UI)."""
    global _services
    if _services is None:
        _services = build_services()
        get_embedder()  # load the embedding model once
    return _services
