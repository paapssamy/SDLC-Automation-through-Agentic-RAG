"""LLMClient interface (Strategy pattern).

Every concrete client implements only `_complete`; `generate` is the public entry point and
ALWAYS masks sensitive data first, so no provider can receive raw account numbers.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.services.masking import mask_sensitive

log = logging.getLogger(__name__)


class LLMClient(ABC):
    """Strategy: Groq, Azure OpenAI and Mock clients are interchangeable."""

    name = "base"
    last_masked_count = 0

    def generate(self, prompt: str, system: str | None = None) -> str:
        masked = mask_sensitive(prompt)
        self.last_masked_count = masked.count
        return self._complete(masked.text, system)

    @abstractmethod
    def _complete(self, prompt: str, system: str | None) -> str: ...
