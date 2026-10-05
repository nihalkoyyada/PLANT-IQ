"""Base Provider Protocol and abstract implementation with retry resilience."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from datetime import datetime, timezone
import random
import time
from typing import Any, AsyncIterator, Callable, Coroutine, Dict, List, Optional, TypeVar
import httpx

from app.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimited,
    ProviderRefused,
    ProviderServiceUnavailable,
    ProviderTimeout,
)
from app.llm.hooks import UsageRecorder
from app.llm.types import Message, ProviderResponse, StreamDelta, ToolDefinition, Usage

T = TypeVar("T")


class BaseProvider(ABC):
    """Abstract Base Class for LLM Providers.

    Enforces uniform ProviderResponse contracts, configurable per-request timeouts,
    streaming deltas, and automated exponential backoff with jitter on retryable errors.
    """

    def __init__(
        self,
        model: str,
        default_timeout_s: float = 60.0,
        max_retries: int = 3,
        initial_backoff_s: float = 0.5,
        backoff_multiplier: float = 2.0,
        usage_recorders: Optional[List[UsageRecorder]] = None,
    ) -> None:
        self.model = model
        self.default_timeout_s = default_timeout_s
        self.max_retries = max_retries
        self.initial_backoff_s = initial_backoff_s
        self.backoff_multiplier = backoff_multiplier
        self.usage_recorders: List[UsageRecorder] = usage_recorders or []

    def add_usage_recorder(self, recorder: UsageRecorder) -> None:
        """Register a usage recorder hook for token accounting."""
        self.usage_recorders.append(recorder)

    def _notify_usage(
        self,
        usage: Usage,
        model: str,
        latency_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Notify all registered usage recorders."""
        for recorder in self.usage_recorders:
            try:
                recorder.record(usage, model, latency_ms, metadata)
            except Exception:
                # Usage recorder failures must not disrupt core provider execution
                pass

    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> ProviderResponse:
        """Send chat completion request to the provider.

        Args:
            messages: List of conversation messages.
            tools: Optional tool definitions available for execution.
            system: Optional system instruction prompt.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            timeout: Optional per-request timeout in seconds.

        Returns:
            Standardized ProviderResponse.
        """
        ...

    @abstractmethod
    def stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[StreamDelta]:
        """Stream response deltas incrementally.

        Yields StreamDelta objects containing text deltas and completed tool blocks.
        """
        ...

    async def _execute_with_retry(
        self,
        func: Callable[[], Coroutine[Any, Any, httpx.Response]],
        timeout_s: float,
        provider_name: str,
    ) -> httpx.Response:
        """Execute an HTTP request operation with exponential backoff and jitter."""
        delay = self.initial_backoff_s
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await func()
                # Check response status
                if response.status_code == 200:
                    return response

                # Handle specific HTTP error status codes
                if response.status_code == 401:
                    raise ProviderAuthenticationError(
                        f"Authentication failed: {response.text}", provider=provider_name
                    )

                if response.status_code in (400, 403):
                    raise ProviderRefused(
                        f"Request refused with HTTP {response.status_code}: {response.text}",
                        provider=provider_name,
                        status_code=response.status_code,
                    )

                if response.status_code == 429:
                    retry_after_hdr = response.headers.get("retry-after")
                    retry_after = float(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else None
                    if attempt == self.max_retries:
                        raise ProviderRateLimited(
                            f"Rate limit exceeded: {response.text}",
                            provider=provider_name,
                            retry_after=retry_after,
                        )
                    # Respect retry-after if provided
                    wait_time = retry_after if retry_after is not None else delay + random.uniform(0.0, 0.25 * delay)
                    await asyncio.sleep(wait_time)
                    delay *= self.backoff_multiplier
                    continue

                if response.status_code in (500, 502, 503, 504):
                    if attempt == self.max_retries:
                        raise ProviderServiceUnavailable(
                            f"Server error {response.status_code}: {response.text}",
                            provider=provider_name,
                            status_code=response.status_code,
                        )
                    wait_time = delay + random.uniform(0.0, 0.25 * delay)
                    await asyncio.sleep(wait_time)
                    delay *= self.backoff_multiplier
                    continue

                # Any other unexpected status code
                response.raise_for_status()
                return response

            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise ProviderTimeout(
                        f"Operation timed out after {attempt + 1} attempts",
                        provider=provider_name,
                        timeout_s=timeout_s,
                    ) from exc
                wait_time = delay + random.uniform(0.0, 0.25 * delay)
                await asyncio.sleep(wait_time)
                delay *= self.backoff_multiplier

            except (ProviderAuthenticationError, ProviderRefused):
                # Never retry client refusal or auth failure
                raise

            except httpx.RequestError as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise ProviderServiceUnavailable(
                        f"Network transport error: {exc}", provider=provider_name
                    ) from exc
                wait_time = delay + random.uniform(0.0, 0.25 * delay)
                await asyncio.sleep(wait_time)
                delay *= self.backoff_multiplier

        raise ProviderError(
            f"Execution failed after {self.max_retries} retries: {last_error}",
            provider=provider_name,
        )

