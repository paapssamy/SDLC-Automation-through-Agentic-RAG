"""Build the LLM client chosen by LLM_PROVIDER."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.llm.client import LLMClient


def get_llm(settings: Settings | None = None) -> LLMClient:
    s = settings or get_settings()
    if s.llm_provider == "groq":
        from app.llm.groq_client import GroqClient

        return GroqClient(s.groq_api_key, s.groq_model)
    if s.llm_provider == "azure":
        from app.llm.azure_openai_client import AzureOpenAIClient

        return AzureOpenAIClient(s.azure_endpoint, s.azure_api_key, s.azure_deployment)
    from app.llm.mock_client import MockLLMClient

    return MockLLMClient()
