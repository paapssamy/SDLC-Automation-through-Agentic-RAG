"""Run the whole test suite with coverage and write docs/test_report.md.

python scripts/make_test_report.py
"""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURITY_NAMES = (
    "test_sg0",
    "test_login_and_password_hashing",
    "test_artifacts_are_never_deleted",
    "test_wrong_role_cannot",
    "test_admin_page_denies",
)

DEFECTS = [
    (
        "DEF-01",
        "Phase 2",
        "Mock impact analysis picked an unrelated service (ChargesCalculator) for the "
        "pacs.008 requirement",
        "Generated documentation lacked the class descriptions; parser now keeps the "
        "first Javadoc sentence and the mock weights entity matches",
        "Fixed",
    ),
    (
        "DEF-02",
        "Phase 2",
        "Service for package `payment` was named PaymentRequest (most getters) instead of PaymentService",
        "Anchor-class heuristic now prefers role suffixes (Service, Builder, Validator …)",
        "Fixed",
    ),
    (
        "DEF-03",
        "Phase 2",
        "UT-05: 'max 3 retries' was implemented as 3 attempts in total",
        "First try + up to 3 retries; message and test updated",
        "Fixed",
    ),
    (
        "DEF-04",
        "Phase 1",
        "Embedding model load hung when huggingface.co could not be reached",
        "Local cache is tried first (local_files_only=True), download only if missing",
        "Fixed",
    ),
    (
        "DEF-05",
        "Phase 5",
        "Streamlit 'magic' tried to display a one-line conditional expression; "
        "use_container_width is deprecated",
        "Replaced by an if/else block and width='stretch'",
        "Fixed",
    ),
    (
        "DEF-06",
        "Phase 0",
        "Host port 5432 (and 5433) already used by other local containers",
        "Project database is published on host port 5460",
        "Fixed",
    ),
]


def level(classname: str, name: str) -> str:
    if any(name.startswith(p) for p in SECURITY_NAMES):
        return "Security and governance"
    if ".unit." in f".{classname}":
        return "Unit"
    if ".integration." in f".{classname}":
        return "Integration"
    return "System"


def main() -> int:
    xml_path, cov_path = ROOT / "junit.xml", ROOT / "coverage.json"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-o",
        "addopts=",
        "-q",
        f"--junitxml={xml_path}",
        "--cov=app",
        f"--cov-report=json:{cov_path}",
        "--cov-report=term",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    print(proc.stdout[-1500:])

    stats: dict[str, dict[str, int]] = {}
    ids: list[tuple[str, str, str]] = []
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        lv = level(case.get("classname", ""), case.get("name", ""))
        st = stats.setdefault(lv, {"total": 0, "passed": 0, "failed": 0, "skipped": 0})
        st["total"] += 1
        if case.find("failure") is not None or case.find("error") is not None:
            st["failed"] += 1
            res = "FAIL"
        elif case.find("skipped") is not None:
            st["skipped"] += 1
            res = "SKIP"
        else:
            st["passed"] += 1
            res = "PASS"
        ids.append((case.get("name", ""), lv, res))

    cov = json.loads(cov_path.read_text())
    files = {
        k: v for k, v in cov["files"].items() if not k.replace("\\", "/").startswith("app/ui/")
    }
    stmts = sum(v["summary"]["num_statements"] for v in files.values())
    covered = sum(v["summary"]["covered_lines"] for v in files.values())
    pct = 100 * covered / stmts if stmts else 0

    order = ["Unit", "Integration", "System", "Security and governance"]
    tot = {
        k: sum(stats.get(lv, {}).get(k, 0) for lv in order)
        for k in ("total", "passed", "failed", "skipped")
    }
    lines = [
        "# Test Report",
        "",
        f"Generated on {date.today()} by `scripts/make_test_report.py` "
        "(LLM = mock, embeddings = hash, ADO/Confluence = mock, separate test database).",
        "",
        "## Summary per level",
        "",
        "| Level | Executed | Passed | Failed | Skipped |",
        "|---|---:|---:|---:|---:|",
    ]
    for lv in order:
        s = stats.get(lv, {"total": 0, "passed": 0, "failed": 0, "skipped": 0})
        lines.append(f"| {lv} | {s['total']} | {s['passed']} | {s['failed']} | {s['skipped']} |")
    lines.append(
        f"| **Total** | **{tot['total']}** | **{tot['passed']}** | **{tot['failed']}** | "
        f"**{tot['skipped']}** |"
    )
    lines += [
        "",
        f"**Line coverage of `app/` (excluding `app/ui`): {pct:.1f}%** "
        f"({covered} of {stmts} statements; target ≥ 80%).",
        "",
        "Pages under `app/ui` are exercised by `tests/system/test_ui_smoke.py` "
        "(every page × every role renders without error) but are excluded from the coverage figure.",
        "",
        "## Required test IDs",
        "",
        "| ID | Test function(s) | Result |",
        "|---|---|---|",
    ]
    wanted = {
        "UT-01": "test_ut01",
        "UT-02": "test_ut02",
        "UT-03": "test_ut03",
        "UT-04": "test_ut04",
        "UT-05": "test_ut05",
        "UT-06": "test_ut06",
        "UT-07": "test_ut07",
        "IT-01": "test_it01",
        "IT-02": "test_full_chain_to_signoff",
        "IT-03": "test_it03",
        "IT-04": "test_it04",
        "ST-01": "test_st01",
        "ST-02": "test_full_chain_to_signoff",
        "ST-03": "test_st03",
        "SG-01": "test_sg01",
        "SG-02": "test_sg02",
        "SG-03": "test_sg03",
    }
    for tid, prefix in wanted.items():
        hit = [(n, r) for n, _, r in ids if n.startswith(prefix)]
        ok = "PASS" if hit and all(r == "PASS" for _, r in hit) else "FAIL / missing"
        lines.append(f"| {tid} | {', '.join(n for n, _ in hit) or '-'} | {ok} |")
    lines += [
        "",
        "## Defect table",
        "",
        "| ID | Found in | Description | Resolution | Status |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in DEFECTS]
    lines += [
        "",
        "Tests marked `@pytest.mark.live` (real ADO / Confluence / Groq) are not part of this run.",
        "",
    ]
    (ROOT / "docs" / "test_report.md").write_text("\n".join(lines), encoding="utf-8")
    for f in (xml_path, cov_path):
        f.unlink(missing_ok=True)
    print(
        f"docs/test_report.md written: {tot['passed']}/{tot['total']} passed, coverage {pct:.1f}%"
    )
    return 0 if tot["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
