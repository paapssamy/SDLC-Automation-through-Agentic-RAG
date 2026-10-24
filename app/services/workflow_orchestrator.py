"""WorkflowOrchestrator – starts the next agent ONLY when the previous artifact is APPROVED.

The gate is checked here, on the server side, by reading the status from the database. It never
depends on a button state or on Streamlit session state, so a page refresh or a hand-made call
cannot skip a review (ST-03). Agents never call each other; data passes through the database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from app.agents.ado_repos_connector import AdoReposConnector
from app.agents.code_generation_agent import CodeGenerationAgent, CodeTask
from app.agents.impact_analysis_agent import ImpactAnalysisAgent, ImpactTask
from app.agents.java_parser_agent import JavaParserAgent
from app.agents.story_generator_agent import StoryGeneratorAgent, StoryTask
from app.agents.test_execution_agent import TestExecutionAgent
from app.agents.test_generator_agent import TestGeneratorAgent, TestGenTask
from app.config import get_settings
from app.db import models
from app.db.base import session_scope
from app.db.repositories import AuditRepository
from app.errors import GateError
from app.services.approval_service import ApprovalService, SubmitResult
from app.services.artifacts import ARTIFACTS
from app.services.auth import CurrentUser, require_role


class WorkflowOrchestrator:
    def __init__(
        self,
        approvals: ApprovalService,
        doc_agent: JavaParserAgent,
        impact_agent: ImpactAnalysisAgent,
        story_agent: StoryGeneratorAgent,
        code_agent: CodeGenerationAgent,
        test_agent: TestGeneratorAgent,
        exec_agent: TestExecutionAgent,
        repos: AdoReposConnector,
    ):
        self.approvals = approvals
        self.doc_agent, self.impact_agent = doc_agent, impact_agent
        self.story_agent, self.code_agent = story_agent, code_agent
        self.test_agent, self.exec_agent, self.repos = test_agent, exec_agent, repos

    # ------------------------------------------------------------------ the gate
    @staticmethod
    def status_of(artifact_type: str, artifact_id: int) -> str:
        kind = ARTIFACTS[artifact_type]
        with session_scope() as s:
            row = s.get(kind.model, artifact_id)
            if row is None:
                raise GateError(f"{kind.label} #{artifact_id} does not exist")
            return row.status

    def require_approved(self, artifact_type: str, artifact_id: int) -> None:
        """Server-side gate: the previous artifact must be APPROVED in the database."""
        status = self.status_of(artifact_type, artifact_id)
        if status != "APPROVED":
            with session_scope() as s:
                AuditRepository.add(
                    s,
                    "WorkflowOrchestrator",
                    "GATE_BLOCKED",
                    artifact_type,
                    artifact_id,
                    {"status": status},
                )
            label = ARTIFACTS[artifact_type].label
            raise GateError(f"{label} #{artifact_id} is {status}; it must be APPROVED first")

    # ------------------------------------------------------------------ stage 1: as-is docs
    def generate_documentation(self, user: CurrentUser, folder: str | Path | None = None):
        require_role(user, "TECHNICAL_LEAD")
        folder = Path(folder) if folder else get_settings().sample_data_dir / "java-payments-app"
        return self.doc_agent.document_folder(folder, user.user_id)

    # ------------------------------------------------------------------ stage 2: requirement + impact
    def create_requirement(
        self,
        user: CurrentUser,
        title: str,
        text: str,
        market: str = "SG",
        product: str = "PAYMENTS",
        attachment_path: str | None = None,
    ) -> int:
        require_role(user, "BUSINESS_ANALYST")
        if not text.strip():
            raise ValueError("Requirement text is required")
        with session_scope() as s:
            req = models.BusinessRequirement(
                title=title.strip() or text.strip()[:60],
                req_text=text.strip(),
                market=market,
                product=product,
                attachment_path=attachment_path,
                created_by=user.user_id,
            )
            s.add(req)
            s.flush()
            AuditRepository.add(
                s,
                user.username,
                "REQUIREMENT_CREATED",
                "REQUIREMENT",
                req.req_id,
                {"title": req.title},
                user_id=user.user_id,
            )
            return req.req_id

    def run_impact_analysis(self, user: CurrentUser, req_id: int) -> SubmitResult:
        require_role(user, "BUSINESS_ANALYST")
        with session_scope() as s:
            req = s.get(models.BusinessRequirement, req_id)
            if req is None:
                raise GateError(f"Requirement #{req_id} does not exist")
            task = ImpactTask(user.user_id, req_id, req.req_text, req.market, req.product)
        return self.impact_agent.run(task)

    # ------------------------------------------------------------------ stage 3: story
    def generate_story(self, user: CurrentUser, analysis_id: int) -> SubmitResult:
        require_role(user, "BUSINESS_ANALYST")
        self.require_approved("IMPACT_ANALYSIS", analysis_id)
        return self.story_agent.run(StoryTask(user.user_id, analysis_id))

    # ------------------------------------------------------------------ stage 4: code
    def generate_code(self, user: CurrentUser, story_id: int, feedback: str = "") -> SubmitResult:
        require_role(user, "DEVELOPER")
        self.require_approved("USER_STORY", story_id)
        return self.code_agent.run(CodeTask(user.user_id, story_id, feedback))

    def adopt_code(self, user: CurrentUser, story_id: int) -> str:
        """Adopt into the repository (branch) – only when EVERY code change is APPROVED."""
        require_role(user, "DEVELOPER")
        with session_scope() as s:
            rows = list(
                s.scalars(
                    select(models.CodeChange)
                    .where(
                        models.CodeChange.story_id == story_id,
                        models.CodeChange.status != "REJECTED",
                        models.CodeChange.status != "SUPERSEDED",
                    )
                    .order_by(models.CodeChange.change_id)
                )
            )
            if not rows:
                raise GateError("There are no code changes to adopt")
            blocked = [r for r in rows if r.status != "APPROVED"]
            if blocked:
                AuditRepository.add(
                    s,
                    "WorkflowOrchestrator",
                    "GATE_BLOCKED",
                    "CODE_CHANGE",
                    blocked[0].change_id,
                    {"status": blocked[0].status},
                )
        if blocked:
            raise GateError(
                f"Code change #{blocked[0].change_id} is {blocked[0].status}; "
                "all changes must be APPROVED before adoption"
            )
        files = {r.file_path: r.new_content for r in rows}
        location = self.repos.adopt(story_id, files, user.user_id, [r.change_id for r in rows])
        for r in rows:
            with session_scope() as s:
                s.get(models.CodeChange, r.change_id).adopted_path = location
            self.approvals.publish("CODE_CHANGE", r.change_id, user.username, user.user_id)
        return location

    # ------------------------------------------------------------------ stage 5: tests
    def generate_tests(self, user: CurrentUser, story_id: int) -> SubmitResult:
        require_role(user, "QA_LEAD")
        self.require_approved("USER_STORY", story_id)
        return self.test_agent.run(TestGenTask(user.user_id, story_id))

    def run_tests(self, user: CurrentUser, story_id: int) -> list[dict]:
        require_role(user, "QA_LEAD")
        self.require_approved("USER_STORY", story_id)
        return self.exec_agent.run_automated(story_id, user)

    def record_manual_result(self, user, test_id, status, notes, defect_ref=None) -> None:
        self.exec_agent.record_manual(test_id, status, notes, user, defect_ref)

    def sign_off(self, user: CurrentUser, story_id: int) -> str:
        return self.exec_agent.sign_off(story_id, user)

    # ------------------------------------------------------------------ review + regeneration
    def review(
        self,
        user: CurrentUser,
        artifact_type: str,
        artifact_id: int,
        decision: str,
        comments: str = "",
    ) -> None:
        self.approvals.decide(artifact_type, artifact_id, user, decision, comments)

    def regenerate(
        self, user: CurrentUser, artifact_type: str, artifact_id: int, feedback: str = ""
    ) -> SubmitResult:
        """CHANGES_REQUESTED -> DRAFT (version + 1) -> new generation -> PENDING_REVIEW."""
        if self.status_of(artifact_type, artifact_id) != "CHANGES_REQUESTED":
            raise GateError("Only artifacts with CHANGES_REQUESTED can be regenerated")
        if feedback == "":
            with session_scope() as s:
                req = s.scalars(
                    select(models.ApprovalRequest)
                    .where(
                        models.ApprovalRequest.artifact_type == artifact_type,
                        models.ApprovalRequest.artifact_id == artifact_id,
                        models.ApprovalRequest.decision == "CHANGES_REQUESTED",
                    )
                    .order_by(models.ApprovalRequest.approval_id.desc())
                ).first()
                feedback = (req.comments or "") if req else ""
        if artifact_type == "IMPACT_ANALYSIS":
            require_role(user, "BUSINESS_ANALYST")
            with session_scope() as s:
                a = s.get(models.ImpactAnalysis, artifact_id)
                req = s.get(models.BusinessRequirement, a.req_id)
                task = ImpactTask(
                    user.user_id,
                    req.req_id,
                    req.req_text,
                    req.market,
                    req.product,
                    feedback,
                    artifact_id,
                )
            return self.impact_agent.run(task)
        if artifact_type == "USER_STORY":
            require_role(user, "BUSINESS_ANALYST")
            with session_scope() as s:
                analysis_id = s.get(models.UserStory, artifact_id).analysis_id
            self.require_approved("IMPACT_ANALYSIS", analysis_id)
            return self.story_agent.run(StoryTask(user.user_id, analysis_id, feedback, artifact_id))
        if artifact_type == "CODE_CHANGE":
            require_role(user, "DEVELOPER")
            with session_scope() as s:
                story_id = s.get(models.CodeChange, artifact_id).story_id
            self.require_approved("USER_STORY", story_id)
            return self.code_agent.run(CodeTask(user.user_id, story_id, feedback))
        raise GateError(f"{artifact_type} cannot be regenerated; edit or re-run its stage")

    # ------------------------------------------------------------------ dashboard
    @staticmethod
    def pipeline_counts() -> dict[str, dict[str, int]]:
        """Stage name -> {status: count}, for the Home dashboard."""
        stages = {
            "As-is documentation": models.ServiceDocument,
            "Impact analysis": models.ImpactAnalysis,
            "User story": models.UserStory,
            "Code change": models.CodeChange,
            "Test case": models.TestScenario,
        }
        out = {}
        with session_scope() as s:
            for name, model in stages.items():
                rows = s.execute(select(model.status, func.count()).group_by(model.status)).all()
                out[name] = {r[0]: r[1] for r in rows}
        return out
