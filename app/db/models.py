"""The 16 tables of the design (3NF) plus a small `notification` table.

All foreign keys are ON DELETE RESTRICT. Status columns carry CHECK constraints.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STATUSES = (
    "DRAFT",
    "PENDING_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "REJECTED",
    "PUBLISHED",
    "SUPERSEDED",
)
ROLES = ("BUSINESS_ANALYST", "TECHNICAL_LEAD", "DEVELOPER", "QA_LEAD", "ADMIN")


def _in(col: str, values) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def fk(target: str, nullable: bool = False):
    return mapped_column(
        Integer, ForeignKey(target, ondelete="RESTRICT"), nullable=nullable, index=True
    )


def now_col():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def upd_col():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint(_in("role", ROLES), name="ck_users_role"),)


class ServiceDocument(Base):
    __tablename__ = "service_document"
    doc_id: Mapped[int] = mapped_column(primary_key=True)
    market: Mapped[str] = mapped_column(String(30))
    product: Mapped[str] = mapped_column(String(50))
    service_name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding = mapped_column(Vector(384))
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(25), default="DRAFT", index=True)
    created_by: Mapped[int | None] = fk("users.user_id", True)
    reviewed_by: Mapped[int | None] = fk("users.user_id", True)
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = upd_col()
    __table_args__ = (
        CheckConstraint(_in("status", STATUSES), name="ck_service_document_status"),
        Index("ix_service_document_market_product", "market", "product"),
        Index(
            "ix_service_document_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Release(Base):
    __tablename__ = "release"
    release_id: Mapped[int] = mapped_column(primary_key=True)
    ado_release_ref: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    update_status: Mapped[str] = mapped_column(String(20), default="DETECTED", index=True)
    __table_args__ = (
        CheckConstraint(
            _in("update_status", ("DETECTED", "PROCESSING", "DOCS_UPDATED", "FAILED")),
            name="ck_release_update_status",
        ),
    )


class DocumentVersion(Base):
    __tablename__ = "document_version"
    version_id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = fk("service_document.doc_id")
    release_id: Mapped[int | None] = fk("release.release_id", True)
    version_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    change_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = now_col()


class Guideline(Base):
    __tablename__ = "guideline"
    guideline_id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(150))
    content: Mapped[str] = mapped_column(Text)


class BusinessRequirement(Base):
    __tablename__ = "business_requirement"
    req_id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    req_text: Mapped[str] = mapped_column(Text)
    attachment_path: Mapped[str | None] = mapped_column(String(300))
    market: Mapped[str] = mapped_column(String(30))
    product: Mapped[str] = mapped_column(String(50))
    key_entities = mapped_column(JSONB, default=list)
    created_by: Mapped[int | None] = fk("users.user_id", True)
    created_at: Mapped[datetime] = now_col()


class ImpactAnalysis(Base):
    __tablename__ = "impact_analysis"
    analysis_id: Mapped[int] = mapped_column(primary_key=True)
    req_id: Mapped[int] = fk("business_requirement.req_id")
    affected_services = mapped_column(JSONB, default=list)
    dependencies = mapped_column(JSONB, default=list)
    complexity: Mapped[str] = mapped_column(String(10))
    risk: Mapped[str] = mapped_column(String(10))
    effort_days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    testing_strategy: Mapped[str] = mapped_column(Text)
    unknown_services = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(25), default="DRAFT", index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = fk("users.user_id", True)
    reviewed_by: Mapped[int | None] = fk("users.user_id", True)
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = upd_col()
    __table_args__ = (
        CheckConstraint(_in("status", STATUSES), name="ck_impact_analysis_status"),
        CheckConstraint(_in("complexity", ("Low", "Medium", "High")), name="ck_impact_complexity"),
        CheckConstraint(_in("risk", ("Low", "Medium", "High")), name="ck_impact_risk"),
    )


class RetrievalLog(Base):
    __tablename__ = "retrieval_log"
    log_id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int | None] = fk("impact_analysis.analysis_id", True)
    doc_id: Mapped[int | None] = fk("service_document.doc_id", True)
    agent_name: Mapped[str] = mapped_column(String(60))
    query_text: Mapped[str] = mapped_column(Text)
    similarity_score: Mapped[float] = mapped_column(Numeric(6, 4))
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = now_col()


class UserStory(Base):
    __tablename__ = "user_story"
    story_id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = fk("impact_analysis.analysis_id")
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text)
    acceptance_criteria = mapped_column(JSONB, default=list)
    invest_check = mapped_column(JSONB, default=dict)
    ado_work_item_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(25), default="DRAFT", index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = fk("users.user_id", True)
    reviewed_by: Mapped[int | None] = fk("users.user_id", True)
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = upd_col()
    __table_args__ = (CheckConstraint(_in("status", STATUSES), name="ck_user_story_status"),)


class CodeChange(Base):
    __tablename__ = "code_change"
    change_id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = fk("user_story.story_id")
    file_path: Mapped[str] = mapped_column(String(300))
    original_content: Mapped[str] = mapped_column(Text)
    new_content: Mapped[str] = mapped_column(Text)
    unified_diff: Mapped[str] = mapped_column(Text)
    adopted_path: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(25), default="DRAFT", index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = fk("users.user_id", True)
    reviewed_by: Mapped[int | None] = fk("users.user_id", True)
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = upd_col()
    __table_args__ = (CheckConstraint(_in("status", STATUSES), name="ck_code_change_status"),)


class TestScenario(Base):
    __tablename__ = "test_scenario"
    __test__ = False  # not a pytest class
    test_id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = fk("user_story.story_id")
    title: Mapped[str] = mapped_column(String(250), default="")
    phase: Mapped[str] = mapped_column(String(15))
    test_type: Mapped[str] = mapped_column(String(15))
    priority: Mapped[str] = mapped_column(String(10))
    automated: Mapped[bool] = mapped_column(Boolean, default=False)
    steps = mapped_column(JSONB, default=list)
    expected_result: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(25), default="DRAFT", index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = fk("users.user_id", True)
    reviewed_by: Mapped[int | None] = fk("users.user_id", True)
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = upd_col()
    __table_args__ = (
        CheckConstraint(_in("status", STATUSES), name="ck_test_scenario_status"),
        CheckConstraint(_in("phase", ("SIT", "UAT", "REGRESSION")), name="ck_test_phase"),
        CheckConstraint(
            _in("test_type", ("FUNCTIONAL", "NEGATIVE", "BOUNDARY", "INTEGRATION")),
            name="ck_test_type",
        ),
        CheckConstraint(_in("priority", ("HIGH", "MEDIUM", "LOW")), name="ck_test_priority"),
    )


class TestResult(Base):
    __tablename__ = "test_result"
    __test__ = False
    result_id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = fk("test_scenario.test_id")
    run_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(10))
    log: Mapped[str] = mapped_column(Text, default="")
    defect_ref: Mapped[str | None] = mapped_column(String(60))
    executed_by: Mapped[int | None] = fk("users.user_id", True)
    signed_off_by: Mapped[int | None] = fk("users.user_id", True)
    executed_at: Mapped[datetime] = now_col()
    __table_args__ = (
        CheckConstraint(
            _in("status", ("PASS", "FAIL", "BLOCKED", "NOT_RUN")), name="ck_result_status"
        ),
    )


class ReleaseChange(Base):
    __tablename__ = "release_change"
    change_id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = fk("release.release_id")
    work_item_id: Mapped[str | None] = mapped_column(String(40))
    commit_id: Mapped[str | None] = mapped_column(String(60))
    file_path: Mapped[str] = mapped_column(String(300))
    code_diff: Mapped[str] = mapped_column(Text, default="")


class ApprovalRequest(Base):
    __tablename__ = "approval_request"
    approval_id: Mapped[int] = mapped_column(primary_key=True)
    artifact_type: Mapped[str] = mapped_column(String(40))
    artifact_id: Mapped[int] = mapped_column(Integer)
    submitted_by: Mapped[int | None] = fk("users.user_id", True)
    reviewer_id: Mapped[int | None] = fk("users.user_id", True)
    decision: Mapped[str] = mapped_column(String(25), default="PENDING", index=True)
    comments: Mapped[str | None] = mapped_column(Text)
    source_refs = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = now_col()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            _in("decision", ("PENDING", "APPROVED", "CHANGES_REQUESTED", "REJECTED")),
            name="ck_approval_decision",
        ),
        Index("ix_approval_artifact", "artifact_type", "artifact_id"),
    )


class AuditLog(Base):
    """Append-only: a DB trigger blocks UPDATE and DELETE."""

    __tablename__ = "audit_log"
    log_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = fk("users.user_id", True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60), index=True)
    artifact_type: Mapped[str | None] = mapped_column(String(40))
    artifact_id: Mapped[int | None] = mapped_column(Integer)
    details = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = now_col()


class IntegrationConfig(Base):
    __tablename__ = "integration_config"
    config_id: Mapped[int] = mapped_column(primary_key=True)
    system_name: Mapped[str] = mapped_column(String(20), unique=True)
    base_url: Mapped[str | None] = mapped_column(String(300))
    project_or_space: Mapped[str | None] = mapped_column(String(100))
    secret_ref: Mapped[str | None] = mapped_column(String(80))  # NAME of an env var only
    settings = mapped_column(JSONB, default=dict)
    __table_args__ = (
        CheckConstraint(
            _in("system_name", ("ADO", "CONFLUENCE", "LLM")), name="ck_integration_system"
        ),
    )


class Notification(Base):
    """In-app notifications (Observer). Extra table beyond the 16 core tables."""

    __tablename__ = "notification"
    notification_id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(30), index=True)
    message: Mapped[str] = mapped_column(Text)
    event: Mapped[str] = mapped_column(String(40))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = now_col()
