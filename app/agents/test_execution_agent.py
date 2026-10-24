"""Agent 6 – Test Execution Agent (module 3.7).

Runs APPROVED automated cases through a TestRunnerAdapter, records manual results entered by
the QA Lead, supports QA sign-off and uploads results to ADO Test Plans. Not an LLM agent, but
every action is audited.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db import models
from app.db.base import session_scope
from app.db.repositories import AuditRepository
from app.errors import GateError
from app.integrations.ado_client import AdoClient
from app.integrations.test_runner import TestRunnerAdapter
from app.services.approval_service import ApprovalService
from app.services.auth import CurrentUser, require_role


class TestExecutionAgent:
    __test__ = False
    name = "TestExecutionAgent"

    def __init__(self, runner: TestRunnerAdapter, ado: AdoClient, approvals: ApprovalService):
        self.runner, self.ado, self.approvals = runner, ado, approvals

    # -- helpers --------------------------------------------------------------------------------
    @staticmethod
    def _scenarios(session, story_id: int, statuses=("APPROVED",)):
        return list(
            session.scalars(
                select(models.TestScenario)
                .where(
                    models.TestScenario.story_id == story_id,
                    models.TestScenario.status.in_(statuses),
                )
                .order_by(models.TestScenario.test_id)
            )
        )

    @staticmethod
    def _next_run(session, test_id: int) -> int:
        n = session.scalar(
            select(func.max(models.TestResult.run_no)).where(models.TestResult.test_id == test_id)
        )
        return (n or 0) + 1

    # -- automated ----------------------------------------------------------------------------
    def run_automated(self, story_id: int, user: CurrentUser) -> list[dict]:
        require_role(user, "QA_LEAD")
        with session_scope() as s:
            scen = [x for x in self._scenarios(s, story_id) if x.automated]
            if not scen:
                raise GateError("No APPROVED automated test cases for this story")
            run_no = max(self._next_run(s, x.test_id) for x in scen)
            payload = [
                {"test_id": x.test_id, "title": x.title, "test_type": x.test_type} for x in scen
            ]
        outcomes = self.runner.run(payload, run_no)
        saved = []
        with session_scope() as s:
            for p in payload:
                o = outcomes[p["test_id"]]
                row = models.TestResult(
                    test_id=p["test_id"],
                    run_no=self._next_run(s, p["test_id"]),
                    status=o.status,
                    log=o.log,
                    executed_by=user.user_id,
                    defect_ref="DEF-101" if o.status == "FAIL" else None,
                )
                s.add(row)
                s.flush()
                saved.append({"test_id": p["test_id"], "run_no": row.run_no, "status": o.status})
            AuditRepository.add(
                s,
                self.name,
                "TESTS_EXECUTED",
                "USER_STORY",
                story_id,
                {"count": len(saved), "failed": sum(1 for r in saved if r["status"] != "PASS")},
                user_id=user.user_id,
            )
        return saved

    # -- manual -------------------------------------------------------------------------------
    def record_manual(
        self,
        test_id: int,
        status: str,
        notes: str,
        user: CurrentUser,
        defect_ref: str | None = None,
    ) -> None:
        require_role(user, "QA_LEAD")
        if status not in ("PASS", "FAIL", "BLOCKED"):
            raise ValueError("status must be PASS, FAIL or BLOCKED")
        with session_scope() as s:
            sc = s.get(models.TestScenario, test_id)
            if sc is None or sc.status != "APPROVED":
                raise GateError("Test case must be APPROVED before results can be recorded")
            s.add(
                models.TestResult(
                    test_id=test_id,
                    run_no=self._next_run(s, test_id),
                    status=status,
                    log=notes,
                    defect_ref=defect_ref,
                    executed_by=user.user_id,
                )
            )
            AuditRepository.add(
                s,
                user.username,
                "MANUAL_RESULT_RECORDED",
                "TEST_SCENARIO",
                test_id,
                {"status": status},
                user_id=user.user_id,
            )

    # -- reporting / sign-off ----------------------------------------------------------------
    def latest_results(self, story_id: int) -> list[dict]:
        out = []
        with session_scope() as s:
            for sc in self._scenarios(s, story_id, ("APPROVED", "PUBLISHED")):
                last = s.scalars(
                    select(models.TestResult)
                    .where(models.TestResult.test_id == sc.test_id)
                    .order_by(models.TestResult.run_no.desc())
                ).first()
                out.append(
                    {
                        "test_id": sc.test_id,
                        "title": sc.title,
                        "automated": sc.automated,
                        "test_type": sc.test_type,
                        "phase": sc.phase,
                        "status": sc.status,
                        "result": last.status if last else "NOT_RUN",
                        "run_no": last.run_no if last else 0,
                        "log": last.log if last else "",
                        "defect_ref": last.defect_ref if last else None,
                        "signed_off": bool(last and last.signed_off_by),
                    }
                )
        return out

    def sign_off(self, story_id: int, user: CurrentUser) -> str:
        """QA sign-off: every approved case needs a latest result of PASS. Then upload to ADO."""
        require_role(user, "QA_LEAD")
        results = self.latest_results(story_id)
        if not results:
            raise GateError("No approved test cases to sign off")
        bad = [r for r in results if r["result"] != "PASS"]
        if bad:
            raise GateError(
                f"Cannot sign off: {len(bad)} case(s) are not PASS "
                f"({', '.join(str(r['test_id']) for r in bad)})"
            )
        run_id = self.ado.upload_test_results(
            f"Story-{story_id}",
            [
                {"test_id": r["test_id"], "title": r["title"], "outcome": r["result"]}
                for r in results
            ],
        )
        with session_scope() as s:
            for r in results:
                last = s.scalars(
                    select(models.TestResult)
                    .where(models.TestResult.test_id == r["test_id"])
                    .order_by(models.TestResult.run_no.desc())
                ).first()
                last.signed_off_by = user.user_id
        for r in results:
            self.approvals.publish("TEST_SCENARIO", r["test_id"], user.username, user.user_id)
        with session_scope() as s:
            AuditRepository.add(
                s,
                user.username,
                "QA_SIGN_OFF",
                "USER_STORY",
                story_id,
                {"ado_test_run": run_id, "cases": len(results)},
                user_id=user.user_id,
            )
        return run_id
