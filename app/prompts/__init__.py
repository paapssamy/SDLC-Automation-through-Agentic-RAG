"""Versioned prompt templates (LangChain PromptTemplate, jinja2 syntax)."""

from __future__ import annotations

from pathlib import Path

from langchain_core.prompts import PromptTemplate

PROMPT_DIR = Path(__file__).parent
PROMPT_VERSION = "1.0"


def render(name: str, **variables: object) -> str:
    """Load `<name>.txt` and fill it with `variables`."""
    template = (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")
    return PromptTemplate.from_template(template, template_format="jinja2").format(**variables)
