"""Groq (Llama 3.1 8B) client with simple retry/back-off."""

from __future__ import annotations

import logging
import time

from app.llm.client import LLMClient

log = logging.getLogger(__name__)


class GroqClient(LLMClient):
    name = "groq"

    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant", retries: int = 3):
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set (put it in .env)")
        from groq import Groq

        self._client = Groq(api_key=api_key)
        self.model = model
        self.retries = retries

    def _complete(self, prompt: str, system: str | None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model, messages=messages, temperature=0.2, max_tokens=3000
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:  # network / rate limit
                last = exc
                log.warning("Groq call failed (attempt %d): %s", attempt + 1, exc)
                time.sleep(2**attempt)
        raise RuntimeError(f"Groq request failed after {self.retries} attempts: {last}")
