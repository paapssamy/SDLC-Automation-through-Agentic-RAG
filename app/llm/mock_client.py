"""Deterministic mock LLM for tests and the offline demo.

It reads the `TASK:` line and the `## SECTION` blocks of our own prompt templates and builds a
sensible answer from them, so the whole pipeline can be demonstrated without any API key.
Tests may also pass `responses=[...]` to script exact outputs (e.g. invalid JSON for UT-05).
"""

from __future__ import annotations

import json
import re

from app.llm.client import LLMClient

_VOCAB = [
    "pacs.008",
    "pacs.002",
    "MT103",
    "purpose code",
    "sanctions",
    "screening",
    "cut-off",
    "cutoff",
    "charges",
    "OUR",
    "SHA",
    "BEN",
    "LEI",
    "SGD",
    "USD",
    "EUR",
    "high-value",
    "mandatory field",
    "country list",
    "FX",
    "validation",
    "notification",
]


_GENERIC = {
    "add",
    "the",
    "and",
    "field",
    "message",
    "messages",
    "mandatory",
    "new",
    "with",
    "for",
    "must",
    "that",
    "all",
    "from",
    "are",
    "will",
    "payments",
    "payment",
    "outgoing",
}


def section(prompt: str, name: str) -> str:
    """Return the text of `## NAME` up to the next `## ` header."""
    m = re.search(rf"^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)", prompt, re.S | re.M)
    return m.group(1).strip() if m else ""


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9.]+", text.lower()) if len(w) > 2}


class MockLLMClient(LLMClient):
    name = "mock"

    def __init__(self, responses: list[str] | None = None):
        self._queue = list(responses or [])
        self.calls: list[str] = []

    def _complete(self, prompt: str, system: str | None) -> str:
        self.calls.append(prompt)
        if self._queue:
            return self._queue.pop(0)
        m = re.search(r"^TASK:\s*(\w+)", prompt, re.M)
        task = m.group(1) if m else "unknown"
        handler = getattr(self, f"_{task}", None)
        if handler is None:
            return "OK"
        return handler(prompt)

    # ---- tasks -------------------------------------------------------------------------
    def _document_service(self, prompt: str) -> str:
        name = section(prompt, "SERVICE")
        structure = section(prompt, "STRUCTURE")
        bullets = "\n".join(f"- {ln.strip()}" for ln in structure.splitlines() if ln.strip())
        deps = sorted(set(re.findall(r"depends on: ([^|\n]+)", structure)))
        return (
            f"# {name}\n\n## Purpose\n"
            f"The {name} service is part of the payments application and implements the "
            f"business functions listed below.\n\n## Key Components\n{bullets}\n\n"
            f"## Business Rules\nBehaviour is defined by the methods above; changes require "
            f"approval before release.\n\n## Dependencies\n{'; '.join(deps) or 'None recorded'}\n"
        )

    def _extract_entities(self, prompt: str) -> str:
        req = section(prompt, "REQUIREMENT")
        found = [v for v in _VOCAB if v.lower() in req.lower()]
        found += re.findall(r"\b[A-Za-z]+\.\d{3}\b|\bMT\d{3}\b", req)
        if not found:
            found = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", req)][:4]
        return json.dumps({"entities": list(dict.fromkeys(found))})

    def _impact_report(self, prompt: str) -> str:
        entities = [e.strip().lower() for e in section(prompt, "ENTITIES").split(",") if e.strip()]
        rq = _words(section(prompt, "REQUIREMENT") + " " + " ".join(entities)) - _GENERIC
        services: list[tuple[int, str]] = []
        for line in section(prompt, "RETRIEVED SERVICES").splitlines():
            m = re.match(r"-\s*([\w.]+)\s*\(", line.strip())
            if m:
                score = 3 * sum(1 for e in entities if e in line.lower()) + len(rq & _words(line))
                services.append((score, m.group(1)))
        services.sort(key=lambda t: -t[0])
        best = services[0][0] if services else 0
        affected = [n for sc, n in services if sc > 0 and sc >= 0.6 * best][:3]
        if not affected and services:
            affected = [services[0][1]]
        n = len(affected)
        return json.dumps(
            {
                "affected_services": affected,
                "dependencies": ["PaymentRepository"] if affected else [],
                "complexity": "High" if n >= 3 else "Medium" if n == 2 else "Low",
                "risk": "Medium" if n >= 2 else "Low",
                "effort_days": float(2 * max(n, 1) + 1),
                "testing_strategy": "Unit tests for changed classes, SIT for message flow, "
                "regression of payment initiation and validation.",
            }
        )

    def _user_story(self, prompt: str) -> str:
        req = section(prompt, "REQUIREMENT")
        first = req.splitlines()[0] if req else "the change"
        goal = first.rstrip(".")
        crit = [
            f"Given a valid payment, When the change is applied, Then {goal.lower()} is satisfied.",
            "Given an invalid input, When the payment is submitted, Then it is rejected with a "
            "clear error code.",
            "Given an existing payment flow, When the change is deployed, Then current behaviour "
            "is unchanged (regression).",
        ]
        invest = {
            k: {"pass": True, "reason": r}
            for k, r in {
                "I": "Can be delivered without other stories.",
                "N": "Implementation details can be discussed.",
                "V": "Meets the business requirement.",
                "E": "Scope is limited to the affected services.",
                "S": "Fits within one sprint.",
                "T": "Acceptance criteria are testable.",
            }.items()
        }
        return json.dumps(
            {
                "title": goal[:120],
                "description": f"As a payments operations user, I want {goal.lower()}, "
                "so that the bank stays compliant and processing is correct.",
                "acceptance_criteria": crit,
                "invest_check": invest,
            }
        )

    def _code_generation(self, prompt: str) -> str:
        files_block = section(prompt, "FILES")
        story = section(prompt, "USER STORY")
        title = story.splitlines()[0] if story else "change"
        method = "apply" + "".join(w.capitalize() for w in re.findall(r"[A-Za-z0-9]+", title)[:5])
        out = []
        for m in re.finditer(r"=== FILE: (.+?) ===\n(.*?)\n=== END FILE ===", files_block, re.S):
            path, content = m.group(1).strip(), m.group(2)
            idx = content.rstrip().rfind("}")
            addition = (
                f"\n    /** Story change: {title[:80]} */\n"
                f"    public boolean {method}() {{\n        return true;\n    }}\n"
            )
            out.append({"path": path, "content": content[:idx] + addition + content[idx:]})
            break  # one file is enough for the demo
        return json.dumps({"files": out})

    def _test_cases(self, prompt: str) -> str:
        story = section(prompt, "USER STORY")
        title = story.splitlines()[0] if story else "the change"
        mk = lambda t, ph, ty, pr, au, steps, exp: {  # noqa: E731
            "title": t,
            "phase": ph,
            "test_type": ty,
            "priority": pr,
            "automated": au,
            "steps": steps,
            "expected_result": exp,
        }
        return json.dumps(
            {
                "scenarios": [
                    mk(
                        f"Valid payment passes: {title[:60]}",
                        "SIT",
                        "FUNCTIONAL",
                        "HIGH",
                        True,
                        ["Create a valid payment", "Submit"],
                        "Payment accepted",
                    ),
                    mk(
                        "Invalid input is rejected",
                        "SIT",
                        "NEGATIVE",
                        "HIGH",
                        True,
                        ["Create payment with invalid value", "Submit"],
                        "Rejected with error code",
                    ),
                    mk(
                        "Boundary value accepted",
                        "SIT",
                        "BOUNDARY",
                        "MEDIUM",
                        True,
                        ["Use the boundary value", "Submit"],
                        "Handled correctly",
                    ),
                    mk(
                        "End-to-end message flow",
                        "SIT",
                        "INTEGRATION",
                        "HIGH",
                        True,
                        ["Initiate payment", "Check outgoing message"],
                        "Message is correct",
                    ),
                    mk(
                        "Business sign-off of the change",
                        "UAT",
                        "FUNCTIONAL",
                        "MEDIUM",
                        False,
                        ["Walk through the scenario with business"],
                        "Business accepts",
                    ),
                    mk(
                        "Regression: payment initiation unchanged",
                        "REGRESSION",
                        "FUNCTIONAL",
                        "MEDIUM",
                        True,
                        ["Run existing payment initiation suite"],
                        "All existing tests pass",
                    ),
                ]
            }
        )

    def _doc_update(self, prompt: str) -> str:
        current = section(prompt, "CURRENT DOCUMENTATION")
        changes = section(prompt, "CODE CHANGES")
        added = [
            ln[1:].strip()
            for ln in changes.splitlines()
            if ln.startswith("+") and not ln.startswith("+++") and ln[1:].strip()
        ]
        methods = re.findall(r"(\w+)\s*\(", " ".join(added))
        names = ", ".join(dict.fromkeys(m for m in methods if m not in {"if", "for", "return"}))
        note = f"\n\n## Recent Change\nUpdated by release: {names or 'code modified'}.\n"
        return current.rstrip() + note
