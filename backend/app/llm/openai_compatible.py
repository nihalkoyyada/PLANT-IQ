"""OpenAI-compatible Provider implementation for local vLLM and air-gapped endpoints."""

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

DEFAULT_OPENAI_COMPATIBLE_URL = "http://localhost:8000/v1"
DEFAULT_OPENAI_MODEL = "Qwen/Qwen2.5-14B-Instruct"


class OpenAICompatibleProvider(BaseProvider):
    """LLM Provider targeting OpenAI-compatible APIs (e.g., local vLLM, Ollama, LiteLLM)."""

    def __init__(
        self,
        base_url: str = DEFAULT_OPENAI_COMPATIBLE_URL,
        api_key: Optional[str] = None,
        model: str = DEFAULT_OPENAI_MODEL,
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
        self.base_url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key or "EMPTY"  # vLLM default placeholder
        self._client = client

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "content-type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _format_payload(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Convert standard types to OpenAI-compatible request payload."""
        openai_msgs: List[Dict[str, Any]] = []

        if system:
            openai_msgs.append({"role": "system", "content": system})

        for msg in messages:
            m_dict: Dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.name:
                m_dict["name"] = msg.name
            if msg.tool_call_id:
                m_dict["tool_call_id"] = msg.tool_call_id
            openai_msgs.append(m_dict)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": openai_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }

        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            payload["tool_choice"] = "auto"

        if stream:
            payload["stream_options"] = {"include_usage": True}

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
        """Execute chat completion request against OpenAI/vLLM endpoint."""
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

        response = await self._execute_with_retry(_call, timeout_s, provider_name="vLLM/OpenAI")
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        try:
            data = response.json()
        except Exception as exc:
            raise ProviderError(f"Malformed JSON response: {response.text}", provider="vLLM/OpenAI") from exc

        choices = data.get("choices", [])
        if not choices:
            raise ProviderError("No completion choices returned by model", provider="vLLM/OpenAI")

        choice = choices[0]
        msg = choice.get("message", {})

        text_blocks: List[TextBlock] = []
        raw_text = msg.get("content")
        if raw_text:
            text_blocks.append(TextBlock(text=raw_text))

        tool_use_blocks: List[ToolUseBlock] = []
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, dict):
                args = raw_args
            else:
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"raw_arguments": raw_args}

            tool_use_blocks.append(
                ToolUseBlock(
                    id=tc.get("id", f"call_{len(tool_use_blocks)}"),
                    name=fn.get("name", ""),
                    arguments=args,
                )
            )

        raw_finish = choice.get("finish_reason")
        stop_reason: StopReason = "unknown"
        if raw_finish in ("stop", None):
            stop_reason = "end_turn"
        elif raw_finish in ("tool_calls", "function_call"):
            stop_reason = "tool_use"
        elif raw_finish == "length":
            stop_reason = "max_tokens"

        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("completion_tokens", 0),
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
        """Stream response deltas incrementally using OpenAI SSE protocol."""
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

        # Track tool calls assembly across chunks
        tool_assemblers: Dict[int, Dict[str, Any]] = {}

        client_ctx = self._client or httpx.AsyncClient(timeout=timeout_s)
        try:
            async with client_ctx.stream(
                "POST", self.base_url, json=payload, headers=headers, timeout=timeout_s
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise ProviderError(
                        f"Streaming failed with status {response.status_code}: {body.decode('utf-8', 'replace')}",
                        provider="vLLM/OpenAI",
                        status_code=response.status_code,
                    )

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    raw_data = line[6:].strip()
                    if raw_data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(raw_data)
                    except json.JSONDecodeError:
                        continue

                    # Handle usage in stream_options
                    if "usage" in chunk and chunk["usage"]:
                        u_data = chunk["usage"]
                        yield StreamDelta(
                            usage=Usage(
                                input_tokens=u_data.get("prompt_tokens", 0),
                                output_tokens=u_data.get("completion_tokens", 0),
                            )
                        )

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    choice = choices[0]
                    delta = choice.get("delta", {})

                    # Text delta
                    text_delta = delta.get("content")
                    if text_delta:
                        yield StreamDelta(delta_text=text_delta)

                    # Incremental tool calls
                    tool_calls = delta.get("tool_calls", [])
                    for tc in tool_calls:
                        idx = tc.get("index", 0)
                        if idx not in tool_assemblers:
                            tool_assemblers[idx] = {
                                "id": tc.get("id", ""),
                                "name": tc.get("function", {}).get("name", ""),
                                "arguments_json": "",
                            }
                        assembler = tool_assemblers[idx]
                        if tc.get("id"):
                            assembler["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            assembler["name"] = tc["function"]["name"]
                        if tc.get("function", {}).get("arguments"):
                            assembler["arguments_json"] += tc["function"]["arguments"]

                    # Check finish reason
                    raw_finish = choice.get("finish_reason")
                    if raw_finish:
                        # Flush completed tool calls
                        for assembler in tool_assemblers.values():
                            try:
                                args = json.loads(assembler["arguments_json"]) if assembler["arguments_json"] else {}
                            except json.JSONDecodeError:
                                args = {"raw_arguments": assembler["arguments_json"]}

                            yield StreamDelta(
                                completed_tool_use=ToolUseBlock(
                                    id=assembler["id"],
                                    name=assembler["name"],
                                    arguments=args,
                                )
                            )
                        tool_assemblers.clear()

                        stop_reason: StopReason = "unknown"
                        if raw_finish == "stop":
                            stop_reason = "end_turn"
                        elif raw_finish in ("tool_calls", "function_call"):
                            stop_reason = "tool_use"
                        elif raw_finish == "length":
                            stop_reason = "max_tokens"

                        yield StreamDelta(stop_reason=stop_reason)
        finally:
            if client_ctx != self._client:
                await client_ctx.aclose()

