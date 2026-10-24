"""UT-01, UT-02, UT-05, UT-06 plus runner / diff / schema unit tests."""

import json

import pytest

from app.agents.base_agent import BaseAgent  # noqa: F401
from app.agents.code_generation_agent import CodeGenerationAgent, CodeTask, make_unified_diff
from app.agents.impact_analysis_agent import ImpactAnalysisAgent, ImpactTask
from app.agents.java_parser_agent import group_into_services, parse_folder, parse_java_source
from app.agents.schemas import CodeFiles, StoryDraft
from app.errors import GenerationError, InvalidTransitionError, ValidationFailedError
from app.integrations.test_runner import LocalCommandRunner, MockRunner
from app.llm.mock_client import MockLLMClient
from app.llm.structured import extract_json
from app.rag.retriever import Retriever
from app.services.approval_service import ApprovalService
from app.services.artifacts import check_transition

TWO_CLASSES_ONE_INTERFACE = """
package demo.pay;
import java.util.List;
public interface Notifier { void send(String msg); }
class Alpha { int count; public void run() {} public int size(int a, String b) { return a; } }
class Beta implements Notifier { public void send(String msg) {} }
"""

NESTED = """
package demo.pay;
public class Outer {
    private String name;
    public static class Inner { public void hello() {} }
    public void outerMethod() {}
}
"""


def test_ut01_two_classes_and_one_interface():
    infos = parse_java_source(TWO_CLASSES_ONE_INTERFACE)
    kinds = {i.name: i.kind for i in infos}
    assert kinds == {"Notifier": "interface", "Alpha": "class", "Beta": "class"}
    alpha = next(i for i in infos if i.name == "Alpha")
    assert "run()" in alpha.methods and "size(int, String)" in alpha.methods
    assert alpha.fields == ["int count"]
    assert next(i for i in infos if i.name == "Beta").implements == ["Notifier"]


def test_ut02_nested_class_included():
    infos = parse_java_source(NESTED)
    inner = next(i for i in infos if i.name == "Inner")
    assert inner.parent == "Outer" and inner.is_nested and "hello()" in inner.methods


def test_sample_app_has_nested_class_interface_and_groups():
    classes = parse_folder(
        __import__("app.config", fromlist=["x"]).get_settings().sample_data_dir
        / "java-payments-app"
    )
    assert len([c for c in classes if not c.is_nested]) >= 12
    assert any(c.is_nested for c in classes) and any(c.kind == "interface" for c in classes)
    assert {"PaymentService", "Pacs008MessageBuilder"} <= {
        g.name for g in group_into_services(classes)
    }


VALID_REPORT = {
    "affected_services": ["Pacs008MessageBuilder"],
    "dependencies": [],
    "complexity": "Low",
    "risk": "Low",
    "effort_days": 2,
    "testing_strategy": "SIT",
}


def _agent(llm, db):
    return ImpactAnalysisAgent(llm, Retriever(), ApprovalService())


def test_ut05_text_around_json_is_cleaned(db, kb):
    wrapped = (
        "Sure! Here is the report:\n```json\n" + json.dumps(VALID_REPORT) + "\n```\nHope it helps"
    )
    agent = _agent(MockLLMClient(), db)
    ctx = Retriever().get_context("pacs.008", agent_name="t")
    result = agent.validate(wrapped, ctx)
    assert result.report.complexity == "Low"


def test_ut05_invalid_json_is_retried_then_valid_returned(db, kb):
    llm = MockLLMClient(
        responses=["not json at all", json.dumps({"complexity": "Huge"}), json.dumps(VALID_REPORT)]
    )
    agent = _agent(llm, db)
    agent._prompt = "TASK: impact_report"
    ctx = Retriever().get_context("pacs.008", agent_name="t")
    result = agent.validate("garbage", ctx)
    assert result.report.affected_services == ["Pacs008MessageBuilder"]
    assert len(llm.calls) == 3  # three retries after the first invalid output
    assert "PREVIOUS ATTEMPT WAS INVALID" in llm.calls[1] and "Validation error" in llm.calls[2]


def test_ut05_generation_error_after_three_attempts(db, kb):
    llm = MockLLMClient(responses=["bad", "bad", "bad"])
    agent = _agent(llm, db)
    agent._prompt = "TASK: impact_report"
    with pytest.raises(GenerationError):
        agent.validate("bad", Retriever().get_context("x", agent_name="t"))


def test_grounding_check_moves_unknown_services(db, kb):
    report = {**VALID_REPORT, "affected_services": ["Pacs008MessageBuilder", "GhostService"]}
    agent = _agent(MockLLMClient(), db)
    ctx = Retriever().get_context("pacs.008 message builder", agent_name="t")
    res = agent.validate(json.dumps(report), ctx)
    assert res.unknown_services == ["GhostService"]
    assert res.report.affected_services == ["Pacs008MessageBuilder"]


def test_ut06_invalid_status_transition():
    with pytest.raises(InvalidTransitionError):
        check_transition("DRAFT", "APPROVED")
    with pytest.raises(InvalidTransitionError):
        check_transition("REJECTED", "DRAFT")
    check_transition("DRAFT", "PENDING_REVIEW")
    check_transition("PUBLISHED", "SUPERSEDED")


def test_extract_json_handles_arrays_and_prose():
    assert json.loads(extract_json("x [1, 2] y")) == [1, 2]
    with pytest.raises(ValueError):
        extract_json("no braces")


def test_unified_diff_and_code_validation(db):
    old = "class A {\n  void a() {}\n}\n"
    new = "class A {\n  void a() {}\n  void b() {}\n}\n"
    assert "+  void b() {}" in make_unified_diff("A.java", old, new)
    task = CodeTask(None, 1, originals={"A.java": old})
    ok = CodeGenerationAgent._check(
        CodeFiles.model_validate({"files": [{"path": "A.java", "content": new}]}), task
    )
    assert ok[0].diff
    for bad in (
        {"path": "Missing.java", "content": new},
        {"path": "A.java", "content": old},
        {"path": "A.java", "content": "class A { void ("},
    ):
        with pytest.raises(ValidationFailedError):
            CodeGenerationAgent._check(CodeFiles.model_validate({"files": [bad]}), task)


def test_story_schema_requires_all_invest_letters():
    with pytest.raises(ValueError):
        StoryDraft.model_validate(
            {
                "title": "t",
                "description": "d",
                "acceptance_criteria": ["g"],
                "invest_check": {"I": {"pass": True, "reason": "x"}},
            }
        )


def test_mock_runner_is_deterministic():
    sc = [
        {"test_id": 1, "title": "t", "test_type": "BOUNDARY"},
        {"test_id": 2, "title": "u", "test_type": "NEGATIVE"},
    ]
    r1, r2 = MockRunner().run(sc, 1), MockRunner().run(sc, 2)
    assert (r1[1].status, r1[2].status, r2[1].status) == ("FAIL", "PASS", "PASS")


def test_local_command_runner_blocked_without_environment(tmp_path):
    out = LocalCommandRunner("mvn -q test", tmp_path / "missing").run(
        [{"test_id": 1, "title": "t", "test_type": "FUNCTIONAL"}], 1
    )
    assert out[1].status == "BLOCKED"


def test_local_command_runner_runs_a_real_command(tmp_path):
    (tmp_path / "f.txt").write_text("x")
    import sys

    out = LocalCommandRunner(f'"{sys.executable}" -c "print(1)"', tmp_path).run(
        [{"test_id": 1, "title": "t", "test_type": "FUNCTIONAL"}], 1
    )
    assert out[1].status == "PASS"


def test_impact_task_defaults():
    t = ImpactTask(None, 1, "text")
    assert t.market == "SG" and t.key_entities == []
