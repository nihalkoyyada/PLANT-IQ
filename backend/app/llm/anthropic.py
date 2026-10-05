"""Anthropic Messages API Provider implementation."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional
import httpx

from app.llm.base import BaseProvider
from app.llm.exceptions import ProviderError
from app.llm.hooks import UsageRecorder
from app.llm.types import (
    Message,
    ProviderResponse,
    StopReason,
    StreamDelta,
    TextBlock,
    ToolDefinition,
    ToolUseBlock,
    Usage,
)

DEFAULT_ANTHROPIC_MODEL = "claude-3-7-sonnet-20250219"
DEFAULT_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(BaseProvider):
    """LLM Provider for Anthropic Messages API."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_ANTHROPIC_MODEL,
        base_url: Optional[str] = None,
        default_timeout_s: float = 60.0,
        max_retries: int = 3,
        initial_backoff_s: float = 0.5,
        backoff_multiplier: float = 2.0,
        usage_recorders: Optional[List[UsageRecorder]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(
            model=model,
            default_timeout_s=default_timeout_s,
            max_retries=max_retries,
            initial_backoff_s=initial_backoff_s,
            backoff_multiplier=backoff_multiplier,
            usage_recorders=usage_recorders,
        )
        self.api_key = api_key
        self.base_url = (base_url.rstrip("/") if base_url else "https://api.anthropic.com") + "/v1/messages"
        self._client = client

    def _get_headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _format_payload(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Convert standard types to Anthropic API request payload."""
        anthropic_msgs: List[Dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                # In Anthropic, system messages are placed in top-level 'system' param
                continue
            anthropic_msgs.append({
                "role": "user" if msg.role in ("user", "tool") else "assistant",
                "content": msg.content,
            })

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }

        if system:
            payload["system"] = system

        if tools:
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]

        return payload

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> ProviderResponse:
        """Execute non-streaming chat request against Anthropic Messages API."""
        timeout_s = timeout if timeout is not None else self.default_timeout_s
        payload = self._format_payload(
            messages=messages,
            tools=tools,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )

        headers = self._get_headers()
        start_time = time.perf_counter()

        async def _call() -> httpx.Response:
            if self._client:
                return await self._client.post(
                    self.base_url, json=payload, headers=headers, timeout=timeout_s
                )
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                return await client.post(
                    self.base_url, json=payload, headers=headers
                )

        response = await self._execute_with_retry(_call, timeout_s, provider_name="Anthropic")
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        try:
            data = response.json()
        except Exception as exc:
            raise ProviderError(f"Malformed JSON response: {response.text}", provider="Anthropic") from exc

        # Parse text blocks and tool use blocks
        text_blocks: List[TextBlock] = []
        tool_use_blocks: List[ToolUseBlock] = []

        for block in data.get("content", []):
            b_type = block.get("type")
            if b_type == "text":
                text_blocks.append(TextBlock(text=block.get("text", "")))
            elif b_type == "tool_use":
                tool_use_blocks.append(
                    ToolUseBlock(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input", {}),
                    )
                )

        raw_stop = data.get("stop_reason")
        stop_reason: StopReason = "unknown"
        if raw_stop in ("end_turn", "tool_use", "max_tokens", "stop_sequence"):
            stop_reason = raw_stop

        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
        )

        model_name = data.get("model", self.model)
        self._notify_usage(usage, model_name, latency_ms)

        return ProviderResponse(
            text_blocks=text_blocks,
            tool_use_blocks=tool_use_blocks,
            stop_reason=stop_reason,
            usage=usage,
            latency_ms=latency_ms,
            model=model_name,
        )

    async def stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[StreamDelta]:
        """Stream response deltas incrementally using Anthropic SSE protocol."""
        timeout_s = timeout if timeout is not None else self.default_timeout_s
        payload = self._format_payload(
            messages=messages,
            tools=tools,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        headers = self._get_headers()

        # Track active tool assembly
        current_tool_id = ""
        current_tool_name = ""
        current_tool_json = ""
        accumulated_input_tokens = 0
        accumulated_output_tokens = 0

        client_ctx = self._client or httpx.AsyncClient(timeout=timeout_s)
        try:
            async with client_ctx.stream(
                "POST", self.base_url, json=payload, headers=headers, timeout=timeout_s
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise ProviderError(
                        f"Streaming failed with status {response.status_code}: {body.decode('utf-8', 'replace')}",
                        provider="Anthropic",
                        status_code=response.status_code,
                    )

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    event_data_raw = line[6:].strip()
                    if event_data_raw == "[DONE]":
                        break

                    try:
                        event = json.loads(event_data_raw)
                    except json.JSONDecodeError:
                        continue

                    e_type = event.get("type")

                    if e_type == "message_start":
                        msg_usage = event.get("message", {}).get("usage", {})
                        accumulated_input_tokens = msg_usage.get("input_tokens", 0)

                    elif e_type == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            current_tool_id = block.get("id", "")
                            current_tool_name = block.get("name", "")
                            current_tool_json = ""

                    elif e_type == "content_block_delta":
                        delta = event.get("delta", {})
                        d_type = delta.get("type")
                        if d_type == "text_delta":
                            yield StreamDelta(delta_text=delta.get("text", ""))
                        elif d_type == "input_json_delta":
                            current_tool_json += delta.get("partial_json", "")

                    elif e_type == "content_block_stop":
                        if current_tool_id and current_tool_name:
                            try:
                                args = json.loads(current_tool_json) if current_tool_json else {}
                            except json.JSONDecodeError:
                                args = {"raw_json": current_tool_json}
                            yield StreamDelta(
                                completed_tool_use=ToolUseBlock(
                                    id=current_tool_id,
                                    name=current_tool_name,
                                    arguments=args,
                                )
                            )
                            current_tool_id = ""
                            current_tool_name = ""
                            current_tool_json = ""

                    elif e_type == "message_delta":
                        delta = event.get("delta", {})
                        raw_stop = delta.get("stop_reason")
                        stop_reason: Optional[StopReason] = None
                        if raw_stop in ("end_turn", "tool_use", "max_tokens", "stop_sequence"):
                            stop_reason = raw_stop

                        delta_usage = event.get("usage", {})
                        accumulated_output_tokens = delta_usage.get("output_tokens", 0)

                        yield StreamDelta(
                            stop_reason=stop_reason,
                            usage=Usage(
                                input_tokens=accumulated_input_tokens,
                                output_tokens=accumulated_output_tokens,
                            ),
                        )
        finally:
            if client_ctx != self._client:
                await client_ctx.aclose()

