"""Masking of sensitive data before ANY text is sent to an LLM (SR security rule)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    ("PHONE", re.compile(r"(?<!\w)\+\d[\d\s-]{7,14}\d")),
    ("ACCOUNT", re.compile(r"\b\d{8,20}\b")),
    # BIC-like customer reference: 8 or 11 uppercase letters/digits starting with 6 letters
    ("BIC", re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")),
]


@dataclass
class MaskResult:
    text: str
    count: int


def mask_sensitive(text: str) -> MaskResult:
    """Replace account numbers, IBANs, emails, phone numbers by placeholders."""
    total = 0
    # BIC is applied only to tokens that look like codes (avoid masking ordinary words)
    for name, pattern in _PATTERNS:
        if name == "BIC":

            def repl(m: re.Match[str]) -> str:
                tok = m.group(0)
                # Plain uppercase words (e.g. "PAYMENTS") stay; codes with a digit or 11 chars go
                if any(c.isdigit() for c in tok) or (len(tok) == 11 and tok not in _KEEP):
                    return "[BIC]"
                return tok

            new, n = _sub_count(pattern, repl, text)
            text = new
            total += n
            continue
        text, n = pattern.subn(f"[{name}]", text)
        total += n
    if total:
        log.info("masking: %d sensitive value(s) masked before LLM call", total)
    return MaskResult(text, total)


_KEEP = {"PAYMENTS", "VALIDATE", "SERVICES", "CHARGES", "MESSAGES", "REQUIRED"}


def _sub_count(pattern, repl, text):
    count = 0

    def wrapper(m):
        nonlocal count
        out = repl(m)
        if out != m.group(0):
            count += 1
        return out

    return pattern.sub(wrapper, text), count
