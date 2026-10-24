"""Azure OpenAI client (used only when configured; same interface as Groq)."""

from __future__ import annotations

import logging
import time

from app.llm.client import LLMClient

log = logging.getLogger(__name__)


class AzureOpenAIClient(LLMClient):
    name = "azure"

    def __init__(self, endpoint: str, api_key: str, deployment: str, retries: int = 3):
        if not (endpoint and api_key and deployment):
            raise ValueError("AZURE_OPENAI_ENDPOINT / API_KEY / DEPLOYMENT must be set")
        from openai import AzureOpenAI

        self._client = AzureOpenAI(
            azure_endpoint=endpoint, api_key=api_key, api_version="2024-06-01"
        )
        self.deployment = deployment
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
                    model=self.deployment, messages=messages, temperature=0.2
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                last = exc
                log.warning("Azure OpenAI call failed (attempt %d): %s", attempt + 1, exc)
                time.sleep(2**attempt)
        raise RuntimeError(f"Azure OpenAI request failed after {self.retries} attempts: {last}")
