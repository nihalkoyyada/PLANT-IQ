#!/usr/bin/env python3
"""Tool-Use Reliability Smoke Test Script.

Task: S1-AI-05
Validates tool-use invocation across configured LLM providers (Anthropic Claude or
local OpenAI-compatible vLLM endpoints).

Usage:
    # 1. Mock mode (deterministic offline verification for CI/testing):
    python backend/scripts/smoke_tooluse.py --mock --provider anthropic
    python backend/scripts/smoke_tooluse.py --mock --provider openai_compatible

    # 2. Live Anthropic (requires ANTHROPIC_API_KEY):
    export ANTHROPIC_API_KEY="sk-ant-..."
    python backend/scripts/smoke_tooluse.py --provider anthropic

    # 3. Live local vLLM / Ollama endpoint:
    python backend/scripts/smoke_tooluse.py --provider openai_compatible \\
        --base-url http://localhost:8000/v1 \\
        --model Qwen/Qwen2.5-14B-Instruct
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure backend and repository roots are in sys.path for direct script execution
_backend_dir = str(Path(__file__).resolve().parent.parent)
_project_root = str(Path(__file__).resolve().parent.parent.parent)
for p in [_backend_dir, _project_root]:
    if p not in sys.path:
        sys.path.insert(0, p)

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

try:
    from app.llm.anthropic import DEFAULT_ANTHROPIC_MODEL
    from app.llm.exceptions import ProviderError
    from app.llm.factory import get_llm_provider
    from app.llm.hooks import InMemoryUsageRecorder
    from app.llm.openai_compatible import (
        DEFAULT_OPENAI_COMPATIBLE_URL,
        DEFAULT_OPENAI_MODEL,
    )
    from app.llm.types import (
        Message,
        ProviderResponse,
        ToolDefinition,
        ToolUseBlock,
    )
except ImportError:
    from backend.app.llm.anthropic import DEFAULT_ANTHROPIC_MODEL
    from backend.app.llm.exceptions import ProviderError
    from backend.app.llm.factory import get_llm_provider
    from backend.app.llm.hooks import InMemoryUsageRecorder
    from backend.app.llm.openai_compatible import (
        DEFAULT_OPENAI_COMPATIBLE_URL,
        DEFAULT_OPENAI_MODEL,
    )
    from backend.app.llm.types import (
        Message,
        ProviderResponse,
        ToolDefinition,
        ToolUseBlock,
    )

app = typer.Typer(
    name="smoke-tooluse",
    help="PlantIQ LLM Tool-Use Verification & Smoke Test CLI",
    add_completion=False,
)
console = Console()

# ---------------------------------------------------------------------------
# Tool Schema & Prompt Specification
# ---------------------------------------------------------------------------

TIME_TOOL = ToolDefinition(
    name="get_current_time",
    description="Retrieve the current date and time for a specified IANA timezone.",
    parameters={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA timezone identifier, e.g. 'Asia/Kolkata', 'UTC', 'America/New_York'.",
            }
        },
        "required": ["timezone"],
    },
)

SYSTEM_PROMPT = (
    "You are an AI assistant for PlantIQ solar SCADA analytics. "
    "When asked for current time or environmental conditions, use the provided tools."
)

USER_PROMPT = "What is the current time in Kolkata, India? Please use the get_current_time tool."


# ---------------------------------------------------------------------------
# Mock Transport for CI / Offline Smoke Testing
# ---------------------------------------------------------------------------


def create_mock_transport(provider_name: str, model_name: str) -> httpx.MockTransport:
    """Create an HTTP mock transport simulating realistic tool_use responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else {}
        is_stream = bool(body.get("stream", False))

        if "anthropic" in provider_name:
            if is_stream:
                sse_events = [
                    'data: {"type": "message_start", "message": {"usage": {"input_tokens": 142}}}\n\n',
                    'data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}\n\n',
                    'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "I will check the current time for Kolkata, India."}}\n\n',
                    'data: {"type": "content_block_stop", "index": 0}\n\n',
                    'data: {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_019a8b7c6d5e", "name": "get_current_time"}}\n\n',
                    'data: {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\\"timezone\\": "}}\n\n',
                    'data: {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "\\"Asia/Kolkata\\"}"}}\n\n',
                    'data: {"type": "content_block_stop", "index": 1}\n\n',
                    'data: {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 58}}\n\n',
                    'data: {"type": "message_stop"}\n\n',
                ]
                return httpx.Response(200, text="".join(sse_events))

            # Handle Anthropic non-streaming Messages API
            mock_payload = {
                "id": "msg_smoke_test_anthropic_01",
                "type": "message",
                "role": "assistant",
                "model": model_name,
                "content": [
                    {
                        "type": "text",
                        "text": "I will check the current time for Kolkata, India.",
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_019a8b7c6d5e",
                        "name": "get_current_time",
                        "input": {"timezone": "Asia/Kolkata"},
                    },
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 142,
                    "output_tokens": 58,
                },
            }
            return httpx.Response(200, json=mock_payload)

        # Handle OpenAI Compatible / vLLM API
        if is_stream:
            sse_events = [
                'data: {"choices": [{"delta": {"role": "assistant", "content": "Looking up current time in Kolkata..."}, "finish_reason": null}]}\n\n',
                'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_vllm_tool_987654", "function": {"name": "get_current_time", "arguments": "{\\"timezone\\": "}}]}, "finish_reason": null}]}\n\n',
                'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\\"Asia/Kolkata\\"}"}}]}, "finish_reason": null}]}\n\n',
                'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 168, "completion_tokens": 44, "total_tokens": 212}}\n\n',
                'data: [DONE]\n\n',
            ]
            return httpx.Response(200, text="".join(sse_events))

        openai_mock_payload: Dict[str, Any] = {
            "id": "chatcmpl_smoke_test_vllm_01",
            "object": "chat.completion",
            "created": 1726998000,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Looking up current time in Kolkata...",
                        "tool_calls": [
                            {
                                "id": "call_vllm_tool_987654",
                                "type": "function",
                                "function": {
                                    "name": "get_current_time",
                                    "arguments": json.dumps({"timezone": "Asia/Kolkata"}),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 168,
                "completion_tokens": 44,
                "total_tokens": 212,
            },
        }
        return httpx.Response(200, json=openai_mock_payload)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Core Smoke Execution Logic
# ---------------------------------------------------------------------------


async def run_smoke_test(
    provider_name: str,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    mock: bool = False,
    timeout: float = 30.0,
    test_streaming: bool = False,
) -> bool:
    """Execute the tool-use smoke test and validate response invariants."""
    norm_provider = provider_name.lower().strip()
    if norm_provider in ("openai", "vllm"):
        norm_provider = "openai_compatible"

    resolved_model = model
    if not resolved_model:
        resolved_model = (
            DEFAULT_ANTHROPIC_MODEL
            if norm_provider == "anthropic"
            else DEFAULT_OPENAI_MODEL
        )

    resolved_url = base_url
    if not resolved_url and norm_provider == "openai_compatible":
        resolved_url = os.getenv("LLM_BASE_URL", DEFAULT_OPENAI_COMPATIBLE_URL)

    console.print(
        Panel.fit(
            f"[bold cyan]PlantIQ LLM Tool-Use Reliability Smoke Test[/bold cyan]\n"
            f"[bold]Provider:[/bold] {norm_provider} | [bold]Model:[/bold] {resolved_model}\n"
            f"[bold]Mode:[/bold] {'MOCK (Offline CI)' if mock else 'LIVE NETWORK'}\n"
            f"[bold]Endpoint:[/bold] {resolved_url or 'https://api.anthropic.com/v1/messages'}",
            border_style="blue",
        )
    )

    usage_recorder = InMemoryUsageRecorder()
    mock_client: Optional[httpx.AsyncClient] = None

    if mock:
        transport = create_mock_transport(norm_provider, resolved_model)
        mock_client = httpx.AsyncClient(transport=transport, timeout=timeout)
        if norm_provider == "anthropic" and not api_key:
            api_key = "mock-ant-key-12345"

    try:
        provider = get_llm_provider(
            provider_name=norm_provider,
            model=resolved_model,
            base_url=resolved_url,
            api_key=api_key,
            usage_recorders=[usage_recorder],
            client=mock_client,
        )
    except Exception as e:
        console.print(f"[bold red]Configuration/Initialization Error:[/bold red] {e}")
        return False

    messages = [Message(role="user", content=USER_PROMPT)]

    console.print(f"[yellow]Sending request with tool schema:[/yellow] '{TIME_TOOL.name}'...")

    try:
        # 1. Non-streaming standard invocation
        response: ProviderResponse = await provider.chat(
            messages=messages,
            tools=[TIME_TOOL],
            system=SYSTEM_PROMPT,
            temperature=0.0,
            timeout=timeout,
        )
    except ProviderError as pe:
        console.print(f"[bold red]Provider Error ({pe.__class__.__name__}):[/bold red] {pe.message}")
        if pe.status_code:
            console.print(f"Status Code: {pe.status_code}")
        return False
    except Exception as exc:
        console.print(f"[bold red]Unexpected Error:[/bold red] {exc}")
        return False

    # -----------------------------------------------------------------------
    # Invariant Assertions
    # -----------------------------------------------------------------------
    errors: List[str] = []

    # Check 1: Tool use blocks presence
    if not response.tool_use_blocks:
        errors.append(
            f"Expected at least 1 ToolUseBlock, but received 0. "
            f"(Text output: {[t.text for t in response.text_blocks]})"
        )
    else:
        primary_tool: ToolUseBlock = response.tool_use_blocks[0]

        # Check 2: Tool Name
        if primary_tool.name != TIME_TOOL.name:
            errors.append(
                f"Tool name mismatch: expected '{TIME_TOOL.name}', got '{primary_tool.name}'"
            )

        # Check 3: Tool ID
        if not primary_tool.id or len(primary_tool.id.strip()) == 0:
            errors.append("Tool call ID is missing or empty.")

        # Check 4: Validated Arguments Schema
        if not isinstance(primary_tool.arguments, dict):
            errors.append(
                f"Tool arguments is not a parsed dictionary: type={type(primary_tool.arguments)}"
            )
        elif "timezone" not in primary_tool.arguments:
            errors.append(
                f"Expected argument 'timezone' missing from tool arguments: {primary_tool.arguments}"
            )

    # Check 5: Stop Reason
    if response.stop_reason != "tool_use":
        errors.append(
            f"Expected stop_reason='tool_use', got '{response.stop_reason}'"
        )

    # Check 6: Usage Accounting
    if response.usage.input_tokens <= 0:
        errors.append(f"Input tokens must be > 0, got {response.usage.input_tokens}")
    if response.usage.output_tokens <= 0:
        errors.append(f"Output tokens must be > 0, got {response.usage.output_tokens}")

    # Check 7: Latency
    if response.latency_ms <= 0:
        errors.append(f"Latency ms must be > 0, got {response.latency_ms}")

    # Check 8: UsageRecorder Hook Verification
    if len(usage_recorder.records) != 1:
        errors.append(
            f"UsageRecorder expected 1 record, got {len(usage_recorder.records)}"
        )

    # -----------------------------------------------------------------------
    # Display Results
    # -----------------------------------------------------------------------
    result_table = Table(title="LLM Provider Response Evaluation", border_style="cyan")
    result_table.add_column("Property", style="bold white")
    result_table.add_column("Value", style="green")

    result_table.add_row("Model Name", response.model)
    result_table.add_row("Stop Reason", response.stop_reason)
    result_table.add_row("Latency (ms)", f"{response.latency_ms:.2f} ms")
    result_table.add_row("Input Tokens", str(response.usage.input_tokens))
    result_table.add_row("Output Tokens", str(response.usage.output_tokens))
    result_table.add_row("Total Tokens", str(response.usage.total_tokens))

    if response.text_blocks:
        result_table.add_row(
            "Text Block(s)", " | ".join(t.text.strip() for t in response.text_blocks)
        )

    if response.tool_use_blocks:
        for idx, tb in enumerate(response.tool_use_blocks):
            result_table.add_row(
                f"Tool Block [{idx}]",
                f"ID: {tb.id}\nName: {tb.name}\nArguments: {json.dumps(tb.arguments, indent=2)}",
            )

    console.print(result_table)

    # -----------------------------------------------------------------------
    # Streaming Check (Optional)
    # -----------------------------------------------------------------------
    if test_streaming and not errors:
        console.print("[yellow]Verifying streaming iterator deltas...[/yellow]")
        stream_deltas: List[Any] = []
        try:
            async for delta in provider.stream(
                messages=messages,
                tools=[TIME_TOOL],
                system=SYSTEM_PROMPT,
                temperature=0.0,
            ):
                stream_deltas.append(delta)

            console.print(
                f"[green]Streaming successfully yielded {len(stream_deltas)} chunks.[/green]"
            )
        except Exception as se:
            errors.append(f"Streaming verification failed: {se}")

    # -----------------------------------------------------------------------
    # Summary Status
    # -----------------------------------------------------------------------
    if errors:
        console.print(
            Panel(
                "[bold red]TEST FAILED - INVARIANT VIOLATIONS DETECTED:[/bold red]\n"
                + "\n".join(f"• {e}" for e in errors),
                border_style="red",
            )
        )
        return False

    console.print(
        Panel(
            f"[bold green]SUCCESS: Tool-use invocation verified for '{norm_provider}'![/bold green]\n"
            f"Extracted tool '{response.tool_use_blocks[0].name}' with arguments: "
            f"{json.dumps(response.tool_use_blocks[0].arguments)}",
            border_style="green",
        )
    )
    return True


# ---------------------------------------------------------------------------
# CLI Command Entrypoint
# ---------------------------------------------------------------------------


@app.command()
def main(
    provider: str = typer.Option(
        "anthropic",
        "--provider",
        "-p",
        help="LLM provider: 'anthropic' or 'openai_compatible' / 'vllm'",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Model identifier override",
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        "-u",
        help="Base endpoint URL for OpenAI-compatible/vLLM endpoints",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        "-k",
        help="API key (defaults to env vars ANTHROPIC_API_KEY / OPENAI_API_KEY)",
    ),
    mock: bool = typer.Option(
        False,
        "--mock",
        help="Run against a mocked HTTP transport for offline CI verification",
    ),
    stream: bool = typer.Option(
        False,
        "--stream",
        "-s",
        help="Also exercise the streaming async iterator",
    ),
    timeout: float = typer.Option(
        30.0,
        "--timeout",
        "-t",
        help="Per-request timeout in seconds",
    ),
) -> None:
    """Run the PlantIQ Tool-Use Reliability Smoke Test."""
    success = asyncio.run(
        run_smoke_test(
            provider_name=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            mock=mock,
            timeout=timeout,
            test_streaming=stream,
        )
    )
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    app()
