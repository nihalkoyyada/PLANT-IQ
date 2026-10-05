"""Provider factory with strict environment-based configuration (NFR-5)."""

from __future__ import annotations

import os
from typing import List, Optional
import httpx

from app.llm.anthropic import (
    AnthropicProvider,
    DEFAULT_ANTHROPIC_MODEL,
)
from app.llm.base import BaseProvider
from app.llm.exceptions import ProviderAuthenticationError, ProviderError
from app.llm.hooks import UsageRecorder
from app.llm.openai_compatible import (
    DEFAULT_OPENAI_COMPATIBLE_URL,
    DEFAULT_OPENAI_MODEL,
    OpenAICompatibleProvider,
)


def get_llm_provider(
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    usage_recorders: Optional[List[UsageRecorder]] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> BaseProvider:
    """Instantiate and return the configured LLM provider.

    Environment variables (strictly enforced, NFR-5):
    - `LLM_PROVIDER`: 'anthropic' or 'openai_compatible' / 'vllm'
    - `ANTHROPIC_API_KEY`: Required when provider is anthropic
    - `LLM_MODEL`: Model name override
    - `LLM_BASE_URL`: Base API endpoint URL override

    Args:
        provider_name: Override for LLM_PROVIDER env var.
        model: Override for LLM_MODEL env var.
        base_url: Override for LLM_BASE_URL env var.
        api_key: Override for API key env var.
        usage_recorders: Optional usage recorders to register.
        client: Optional httpx.AsyncClient for testing/mocked transports.

    Returns:
        BaseProvider instance (AnthropicProvider or OpenAICompatibleProvider).
    """
    resolved_provider = (
        provider_name or os.getenv("LLM_PROVIDER") or "anthropic"
    ).lower().strip()

    if resolved_provider == "anthropic":
        resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ProviderAuthenticationError(
                "ANTHROPIC_API_KEY environment variable is missing or empty.",
                provider="Anthropic",
            )
        resolved_model = model or os.getenv("LLM_MODEL") or DEFAULT_ANTHROPIC_MODEL
        resolved_url = base_url or os.getenv("LLM_BASE_URL")

        return AnthropicProvider(
            api_key=resolved_key,
            model=resolved_model,
            base_url=resolved_url,
            usage_recorders=usage_recorders,
            client=client,
        )

    if resolved_provider in ("openai_compatible", "vllm", "openai"):
        resolved_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or DEFAULT_OPENAI_COMPATIBLE_URL
        )
        resolved_model = model or os.getenv("LLM_MODEL") or DEFAULT_OPENAI_MODEL
        resolved_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")

        return OpenAICompatibleProvider(
            base_url=resolved_url,
            api_key=resolved_key,
            model=resolved_model,
            usage_recorders=usage_recorders,
            client=client,
        )

    raise ProviderError(
        f"Unsupported LLM_PROVIDER '{resolved_provider}'. Expected 'anthropic' or 'openai_compatible'.",
        provider=resolved_provider,
    )

