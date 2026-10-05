"""Comprehensive unit tests for LLM providers using mocked HTTP transport.

Task: S1-AI-05
Validates:
- AnthropicProvider and OpenAICompatibleProvider output identical ProviderResponse shapes.
- Normal responses, tool-use responses, and multi-block responses.
- SSE streaming response deltas and tool assembly.
- Retry and exponential backoff on 429, 5xx, and timeout errors.
- Typed exceptions (ProviderTimeout, ProviderRateLimited, ProviderRefused, ProviderAuthenticationError).
- Token accounting and UsageRecorder callbacks.
- Provider factory environment configuration (NFR-5).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
import httpx
import pytest

from app.llm.anthropic import AnthropicProvider
from app.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimited,
    ProviderRefused,
    ProviderServiceUnavailable,
    ProviderTimeout,
)
from app.llm.factory import get_llm_provider
from app.llm.hooks import InMemoryUsageRecorder
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.types import (
    Message,
    ProviderResponse,
    StreamDelta,
    TextBlock,
    ToolDefinition,
    ToolUseBlock,
    Usage,
)


@pytest.fixture
def sample_messages() -> List[Message]:
    return [
        Message(role="user", content="What is the current status of inverter INV-04?"),
    ]


@pytest.fixture
def sample_tool() -> ToolDefinition:
    return ToolDefinition(
        name="get_inverter_telemetry",
        description="Fetch current operating power and yield for a solar inverter.",
        parameters={
            "type": "object",
            "properties": {
                "inverter_id": {"type": "string", "description": "The inverter identifier (e.g. INV-04)"},
            },
            "required": ["inverter_id"],
        },
    )


class TestAnthropicProvider:
    """Test suite for AnthropicProvider using mocked HTTP transport."""

    @pytest.mark.asyncio
    async def test_chat_normal_text(self, sample_messages: List[Message]) -> None:
        """Verify normal text response normalization."""
        mock_response = {
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": "claude-3-7-sonnet-20250219",
            "content": [{"type": "text", "text": "Inverter INV-04 is operating normally at 1,120 kW."}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 42, "output_tokens": 18},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["x-api-key"] == "test-key"
            assert request.headers["anthropic-version"] == "2023-06-01"
            return httpx.Response(200, json=mock_response)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        recorder = InMemoryUsageRecorder()
        provider = AnthropicProvider(api_key="test-key", client=client, usage_recorders=[recorder])

        resp = await provider.chat(messages=sample_messages, system="You are an expert PV assistant.")

        assert isinstance(resp, ProviderResponse)
        assert resp.text == "Inverter INV-04 is operating normally at 1,120 kW."
        assert len(resp.text_blocks) == 1
        assert len(resp.tool_use_blocks) == 0
        assert resp.has_tool_use is False
        assert resp.stop_reason == "end_turn"
        assert resp.usage.input_tokens == 42
        assert resp.usage.output_tokens == 18
        assert resp.usage.total_tokens == 60
        assert resp.latency_ms > 0
        assert resp.model == "claude-3-7-sonnet-20250219"

        # Verify usage recorder
        assert recorder.call_count == 1
        assert recorder.total_tokens == 60

    @pytest.mark.asyncio
    async def test_chat_tool_use(self, sample_messages: List[Message], sample_tool: ToolDefinition) -> None:
        """Verify tool-use response normalization."""
        mock_response = {
            "id": "msg_02",
            "model": "claude-3-7-sonnet-20250219",
            "content": [
                {"type": "text", "text": "I will check the telemetry for INV-04."},
                {
                    "type": "tool_use",
                    "id": "toolu_01",
                    "name": "get_inverter_telemetry",
                    "input": {"inverter_id": "INV-04"},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 120, "output_tokens": 45},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            assert "tools" in body
            assert body["tools"][0]["name"] == "get_inverter_telemetry"
            return httpx.Response(200, json=mock_response)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = AnthropicProvider(api_key="test-key", client=client)

        resp = await provider.chat(messages=sample_messages, tools=[sample_tool])

        assert resp.has_tool_use is True
        assert resp.stop_reason == "tool_use"
        assert len(resp.text_blocks) == 1
        assert resp.text_blocks[0].text == "I will check the telemetry for INV-04."
        assert len(resp.tool_use_blocks) == 1

        tool_block = resp.tool_use_blocks[0]
        assert tool_block.id == "toolu_01"
        assert tool_block.name == "get_inverter_telemetry"
        assert tool_block.arguments == {"inverter_id": "INV-04"}

    @pytest.mark.asyncio
    async def test_streaming_assembly(self, sample_messages: List[Message]) -> None:
        """Verify streaming text deltas and tool blocks."""
        sse_events = [
            'data: {"type": "message_start", "message": {"usage": {"input_tokens": 25}}}\n\n',
            'data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}\n\n',
            'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello "}}\n\n',
            'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Solar!"}}\n\n',
            'data: {"type": "content_block_stop", "index": 0}\n\n',
            'data: {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "call_123", "name": "get_time"}}\n\n',
            'data: {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\\"tz\\": "}}\n\n',
            'data: {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "\\"Asia/Kolkata\\"}"}}\n\n',
            'data: {"type": "content_block_stop", "index": 1}\n\n',
            'data: {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 15}}\n\n',
            'data: {"type": "message_stop"}\n\n',
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="".join(sse_events))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = AnthropicProvider(api_key="test-key", client=client)

        deltas: List[StreamDelta] = []
        async for delta in provider.stream(messages=sample_messages):
            deltas.append(delta)

        text_chunks = [d.delta_text for d in deltas if d.delta_text]
        assert "".join(text_chunks) == "Hello Solar!"

        tool_blocks = [d.completed_tool_use for d in deltas if d.completed_tool_use]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "get_time"
        assert tool_blocks[0].arguments == {"tz": "Asia/Kolkata"}

        stop_reasons = [d.stop_reason for d in deltas if d.stop_reason]
        assert stop_reasons == ["tool_use"]


class TestOpenAICompatibleProvider:
    """Test suite for OpenAICompatibleProvider (vLLM) using mocked HTTP transport."""

    @pytest.mark.asyncio
    async def test_chat_normal_text(self, sample_messages: List[Message]) -> None:
        """Verify normal completion normalization."""
        mock_response = {
            "id": "chatcmpl_01",
            "object": "chat.completion",
            "model": "Qwen/Qwen2.5-14B-Instruct",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Weather station WS-01 shows irradiance 940 W/m²."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/chat/completions"
            return httpx.Response(200, json=mock_response)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleProvider(
            base_url="http://localhost:8000/v1", model="Qwen/Qwen2.5-14B-Instruct", client=client
        )

        resp = await provider.chat(messages=sample_messages)

        assert isinstance(resp, ProviderResponse)
        assert resp.text == "Weather station WS-01 shows irradiance 940 W/m²."
        assert resp.has_tool_use is False
        assert resp.stop_reason == "end_turn"
        assert resp.usage.input_tokens == 30
        assert resp.usage.output_tokens == 12
        assert resp.model == "Qwen/Qwen2.5-14B-Instruct"

    @pytest.mark.asyncio
    async def test_chat_tool_use(self, sample_messages: List[Message], sample_tool: ToolDefinition) -> None:
        """Verify function calling normalization."""
        mock_response = {
            "id": "chatcmpl_02",
            "model": "Qwen/Qwen2.5-14B-Instruct",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc123",
                                "type": "function",
                                "function": {
                                    "name": "get_inverter_telemetry",
                                    "arguments": '{"inverter_id": "INV-11"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 80, "completion_tokens": 25},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            assert "tools" in body
            assert body["tools"][0]["function"]["name"] == "get_inverter_telemetry"
            return httpx.Response(200, json=mock_response)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleProvider(client=client)

        resp = await provider.chat(messages=sample_messages, tools=[sample_tool])

        assert resp.has_tool_use is True
        assert resp.stop_reason == "tool_use"
        assert len(resp.tool_use_blocks) == 1
        assert resp.tool_use_blocks[0].name == "get_inverter_telemetry"
        assert resp.tool_use_blocks[0].arguments == {"inverter_id": "INV-11"}

    @pytest.mark.asyncio
    async def test_streaming_assembly(self, sample_messages: List[Message]) -> None:
        """Verify OpenAI SSE streaming delta assembly."""
        sse_events = [
            'data: {"choices": [{"delta": {"content": "Checking "}}]}\n\n',
            'data: {"choices": [{"delta": {"content": "plant..."}}]}\n\n',
            'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_99", "function": {"name": "query_db", "arguments": "{\\"table\\": "}}]}}]}\n\n',
            'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\\"plants\\"}"}}]}}]}\n\n',
            'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 10, "completion_tokens": 20}}\n\n',
            "data: [DONE]\n\n",
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="".join(sse_events))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleProvider(client=client)

        deltas: List[StreamDelta] = []
        async for delta in provider.stream(messages=sample_messages):
            deltas.append(delta)

        text = "".join(d.delta_text for d in deltas if d.delta_text)
        assert text == "Checking plant..."

        tools = [d.completed_tool_use for d in deltas if d.completed_tool_use]
        assert len(tools) == 1
        assert tools[0].name == "query_db"
        assert tools[0].arguments == {"table": "plants"}

        stop = [d.stop_reason for d in deltas if d.stop_reason]
        assert stop == ["tool_use"]


class TestResilienceAndExceptions:
    """Test retry logic, backoff, and typed exception handling."""

    @pytest.mark.asyncio
    async def test_retry_on_429_rate_limit(self, sample_messages: List[Message]) -> None:
        """Verify provider retries on 429 and succeeds on subsequent attempt."""
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"retry-after": "0.01"}, text="Too Many Requests")
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "Success after retry"}],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = AnthropicProvider(api_key="key", client=client, initial_backoff_s=0.01, max_retries=2)

        resp = await provider.chat(messages=sample_messages)
        assert attempts == 2
        assert resp.text == "Success after retry"

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises_typed_exception(self, sample_messages: List[Message]) -> None:
        """Verify ProviderRateLimited raised when 429 persists."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"retry-after": "0.01"}, text="Persistent Rate Limit")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = AnthropicProvider(api_key="key", client=client, initial_backoff_s=0.01, max_retries=1)

        with pytest.raises(ProviderRateLimited) as exc_info:
            await provider.chat(messages=sample_messages)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_timeout_raises_provider_timeout(self, sample_messages: List[Message]) -> None:
        """Verify timeout raises ProviderTimeout with configured seconds."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Socket read timed out")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = AnthropicProvider(api_key="key", client=client, default_timeout_s=5.0, initial_backoff_s=0.01, max_retries=1)

        with pytest.raises(ProviderTimeout) as exc_info:
            await provider.chat(messages=sample_messages)
        assert exc_info.value.status_code == 408

    @pytest.mark.asyncio
    async def test_500_server_error_retries_and_raises_service_unavailable(self, sample_messages: List[Message]) -> None:
        """Verify 5xx errors retry and raise ProviderServiceUnavailable."""
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(503, text="GPU Worker Crashed")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleProvider(client=client, initial_backoff_s=0.01, max_retries=2)

        with pytest.raises(ProviderServiceUnavailable) as exc_info:
            await provider.chat(messages=sample_messages)
        assert attempts == 3
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_client_refusal_does_not_retry(self, sample_messages: List[Message]) -> None:
        """Verify 400 Bad Request / Content Refusal fails fast without retry."""
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(400, text="Invalid JSON Schema")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = AnthropicProvider(api_key="key", client=client, max_retries=3)

        with pytest.raises(ProviderRefused) as exc_info:
            await provider.chat(messages=sample_messages)
        assert attempts == 1
        assert exc_info.value.status_code == 400


class TestFactoryConfiguration:
    """Test get_llm_provider factory environment parsing (NFR-5)."""

    def test_missing_anthropic_api_key_raises_auth_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        with pytest.raises(ProviderAuthenticationError):
            get_llm_provider()

    def test_anthropic_provider_creation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-1234")
        monkeypatch.setenv("LLM_MODEL", "claude-3-7-sonnet-20250219")

        provider = get_llm_provider()
        assert isinstance(provider, AnthropicProvider)
        assert provider.model == "claude-3-7-sonnet-20250219"

    def test_openai_compatible_provider_creation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
        monkeypatch.setenv("LLM_BASE_URL", "http://vllm-node:8000/v1")
        monkeypatch.setenv("LLM_MODEL", "Qwen/Qwen2.5-14B-Instruct")

        provider = get_llm_provider()
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.model == "Qwen/Qwen2.5-14B-Instruct"
        assert provider.base_url == "http://vllm-node:8000/v1/chat/completions"

    def test_unsupported_provider_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "unsupported_llm")

        with pytest.raises(ProviderError):
            get_llm_provider()
