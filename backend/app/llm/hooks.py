"""Token accounting hooks and usage recorder interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol, Union
from app.llm.types import Usage


@dataclass(frozen=True)
class UsageRecord:
    """Individual record of token usage for an LLM call."""

    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


class UsageRecorder(Protocol):
    """Protocol for recording LLM usage and token metrics."""

    def record(
        self,
        usage: Usage,
        model: str,
        latency_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record usage information for a completed LLM invocation."""
        ...


class InMemoryUsageRecorder:
    """Default thread-safe in-memory usage recorder for accounting and testing."""

    def __init__(self) -> None:
        self.records: List[UsageRecord] = []

    def record(
        self,
        usage: Usage,
        model: str,
        latency_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        rec = UsageRecord(
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            latency_ms=latency_ms,
            metadata=metadata or {},
        )
        self.records.append(rec)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.records)

    @property
    def call_count(self) -> int:
        return len(self.records)

    def clear(self) -> None:
        self.records.clear()

