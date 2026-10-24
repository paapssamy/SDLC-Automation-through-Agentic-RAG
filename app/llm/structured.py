"""Helpers for structured (JSON) LLM output: cleaning, Pydantic validation and retry."""

from __future__ import annotations

import json
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.errors import GenerationError
from app.llm.client import LLMClient

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def extract_json(raw: str) -> str:
    """Strip any text (or ``` fences) around the first JSON object/array in `raw`."""
    starts = [i for i in (raw.find("{"), raw.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found in LLM output")
    start = min(starts)
    closer = "}" if raw[start] == "{" else "]"
    end = raw.rfind(closer)
    if end <= start:
        raise ValueError("unterminated JSON in LLM output")
    return raw[start : end + 1]


def generate_validated(llm: LLMClient, prompt: str, model: type[T], max_retries: int = 3) -> T:
    """Call the LLM and validate with Pydantic. On failure append the error and retry (max 3)."""
    current = prompt
    last_error = ""
    for attempt in range(1, max_retries + 2):
        raw = llm.generate(current)
        try:
            return model.model_validate(json.loads(extract_json(raw)))
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)
            log.warning(
                "LLM output invalid (attempt %d/%d): %s", attempt, max_retries + 1, last_error[:200]
            )
            current = (
                f"{prompt}\n\n## PREVIOUS ATTEMPT WAS INVALID\n"
                f"Validation error: {last_error}\nReturn ONLY valid JSON that matches the schema."
            )
    raise GenerationError(f"LLM output invalid after {max_retries} attempts: {last_error[:300]}")
