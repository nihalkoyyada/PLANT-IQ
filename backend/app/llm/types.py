"""Data types and schemas for LLM provider abstraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union

Role = Literal["user", "assistant", "system", "tool"]
StopReason = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "unknown"]


@dataclass(frozen=True)
class TextBlock:
    """Represents a text segment in an LLM response."""

    text: str


@dataclass(frozen=True)
class ToolUseBlock:
    """Represents a structured tool execution request from the LLM."""

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass(frozen=True)
class Usage:
    """Token accounting counters."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed across input and output."""
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ToolDefinition:
    """Specification of an invocable tool."""

    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema specification


@dataclass(frozen=True)
class Message:
    """Chat message exchanged with the LLM provider."""

    role: Role
    content: Union[str, List[Dict[str, Any]]]
    name: Optional[str] = None
    tool_call_id: Optional[str] = None


@dataclass(frozen=True)
class ProviderResponse:
    """Standardized normalized response contract returned by all providers."""

    text_blocks: List[TextBlock] = field(default_factory=list)
    tool_use_blocks: List[ToolUseBlock] = field(default_factory=list)
    stop_reason: StopReason = "end_turn"
    usage: Usage = field(default_factory=lambda: Usage(input_tokens=0, output_tokens=0))
    latency_ms: float = 0.0
    model: str = ""

    @property
    def text(self) -> str:
        """Concatenated text content of all text blocks."""
        return "".join(b.text for b in self.text_blocks)

    @property
    def has_tool_use(self) -> bool:
        """Indicates whether any tool calls were returned."""
        return len(self.tool_use_blocks) > 0


@dataclass(frozen=True)
class StreamDelta:
    """Incremental chunk yielded during streaming responses."""

    delta_text: Optional[str] = None
    completed_tool_use: Optional[ToolUseBlock] = None
    usage: Optional[Usage] = None
    stop_reason: Optional[StopReason] = None
