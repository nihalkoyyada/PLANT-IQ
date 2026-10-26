"""Deterministic Mock LLM Provider for local development and automated testing (§10.2, Task S5-AI-01).

Implements:
1. Deterministic conversational turns with simulated multi-step tool calls.
2. Support for all 12 SCADA Copilot tools (get_plant_summary, list_assets, list_anomalies, compute_kpi, render_chart, etc.).
3. Realistic citation markers ([T1], [T2]) and chart generation.
4. Simulated provider errors (rate limit, authentication, timeout, service unavailable, refusal).
5. Incremental streaming deltas with identical SSE event contracts to production providers.
6. Explicit model identification ('mock-copilot-v1') to never confuse mock responses with real AI.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from app.llm.base import BaseProvider
from app.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimited,
    ProviderRefused,
    ProviderServiceUnavailable,
    ProviderTimeout,
)
from app.llm.hooks import UsageRecorder
from app.llm.types import (
    Message,
    ProviderResponse,
    StreamDelta,
    TextBlock,
    ToolDefinition,
    ToolUseBlock,
    Usage,
)

DEFAULT_MOCK_MODEL = "mock-copilot-v1"


class MockLLMProvider(BaseProvider):
    """Deterministic, resilient Mock LLM Provider for offline local dev and CI test suites."""

    def __init__(
        self,
        model: str = DEFAULT_MOCK_MODEL,
        scenario: str = "default",
        simulate_error: Optional[str] = None,
        chunk_size: int = 16,
        usage_recorders: Optional[List[UsageRecorder]] = None,
    ) -> None:
        super().__init__(model=model, usage_recorders=usage_recorders)
        self.scenario = scenario
        self.simulate_error = simulate_error or os.getenv("MOCK_SIMULATE_ERROR")
        self.chunk_size = chunk_size
        self.call_count = 0
        self.history_calls: List[Dict[str, Any]] = []

    def _check_and_raise_simulated_error(self, prompt_text: str) -> None:
        """Check if error simulation is requested via env, config, or prompt marker."""
        err_type = (self.simulate_error or "").lower().strip()

        # Also support prompt embedded markers: [SIMULATE_ERROR: rate_limit] or simulate:rate_limit
        prompt_lower = prompt_text.lower()
        if "[simulate_error:" in prompt_lower:
            match = re.search(r"\[simulate_error:\s*([a-z0-9_-]+)\]", prompt_lower)
            if match:
                err_type = match.group(1).strip()
        elif "simulate:" in prompt_lower:
            match = re.search(r"simulate:([a-z0-9_-]+)", prompt_lower)
            if match:
                err_type = match.group(1).strip()

        if not err_type:
            return

        if err_type in ("rate_limit", "429", "ratelimit"):
            raise ProviderRateLimited(
                "Mock LLM: 429 Too Many Requests - Provider rate limit exceeded (simulated).",
                provider="MockProvider",
                retry_after=5.0,
            )
        elif err_type in ("auth", "authentication", "401", "unauthorized"):
            raise ProviderAuthenticationError(
                "Mock LLM: 401 Unauthorized - Invalid or missing API key (simulated).",
                provider="MockProvider",
            )
        elif err_type in ("timeout", "request_timeout", "408"):
            raise ProviderTimeout(
                "Mock LLM: Request timed out after 30.0s (simulated).",
                provider="MockProvider",
            )
        elif err_type in ("unavailable", "service_unavailable", "503"):
            raise ProviderServiceUnavailable(
                "Mock LLM: 503 Service Unavailable - Upstream model inference server offline (simulated).",
                provider="MockProvider",
            )
        elif err_type in ("refused", "rejected", "403"):
            raise ProviderRefused(
                "Mock LLM: Request refused by safety policy (simulated).",
                provider="MockProvider",
            )
        else:
            raise ProviderError(
                f"Mock LLM: General provider exception '{err_type}' (simulated).",
                provider="MockProvider",
            )

    def _extract_last_user_message(self, messages: List[Message]) -> str:
        """Extract the content of the most recent user message."""
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content or ""
        return ""

    def _has_tool_results(self, messages: List[Message]) -> bool:
        """Check if the latest message is a tool execution result block."""
        last_msg = messages[-1] if messages else None
        if not last_msg or last_msg.role != "user":
            return False
        content = last_msg.content or ""
        return "<scada_data" in content or "Tool result for [" in content

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> ProviderResponse:
        """Simulate multi-turn tool orchestration reasoning."""
        self.call_count += 1
        prompt_text = self._extract_last_user_message(messages)
        self.history_calls.append({
            "call_index": self.call_count,
            "message_count": len(messages),
            "prompt_text": prompt_text,
            "has_tool_results": self._has_tool_results(messages),
        })

        # 1. Check for simulated errors
        self._check_and_raise_simulated_error(prompt_text)

        # 2. If a tool was executed in the previous turn, synthesize final response with citations
        if self._has_tool_results(messages):
            return self._synthesize_tool_synthesis(messages)

        # 3. Otherwise, inspect prompt to decide whether to invoke a tool or respond conversationally
        prompt_lower = prompt_text.lower()

        # Available tool names in registry
        avail_names = [t.name for t in (tools or [])]

        # Case A: Anomaly investigation
        if any(w in prompt_lower for w in ("anomaly", "anomalies", "fault", "tripped", "underperform", "deficit", "shortfall")):
            if "list_anomalies" in avail_names:
                return ProviderResponse(
                    text_blocks=[TextBlock(text="Checking active and historical anomaly records for the plant...")],
                    tool_use_blocks=[
                        ToolUseBlock(
                            id=f"call_{uuid4().hex[:12]}",
                            name="list_anomalies",
                            arguments={"status": "open", "limit": 10},
                        )
                    ],
                    stop_reason="tool_use",
                    usage=Usage(input_tokens=150, output_tokens=45),
                    model=self.model,
                )

        # Case B: KPI computation / Performance Ratio
        if any(w in prompt_lower for w in ("pr", "performance ratio", "cuf", "yield", "kpi", "efficiency")):
            if "compute_kpi" in avail_names:
                return ProviderResponse(
                    text_blocks=[TextBlock(text="Computing IEC 61724-1 performance metrics across plant telemetry...")],
                    tool_use_blocks=[
                        ToolUseBlock(
                            id=f"call_{uuid4().hex[:12]}",
                            name="compute_kpi",
                            arguments={"kpi_name": "performance_ratio", "window": "24h"},
                        )
                    ],
                    stop_reason="tool_use",
                    usage=Usage(input_tokens=140, output_tokens=50),
                    model=self.model,
                )

        # Case C: Chart / Visualization
        if any(w in prompt_lower for w in ("chart", "plot", "graph", "visualize", "curve")):
            if "render_chart" in avail_names:
                return ProviderResponse(
                    text_blocks=[TextBlock(text="Generating generation and irradiance timeseries chart...")],
                    tool_use_blocks=[
                        ToolUseBlock(
                            id=f"call_{uuid4().hex[:12]}",
                            name="render_chart",
                            arguments={
                                "title": "Solar Generation & POA Irradiance",
                                "chart_type": "line",
                                "series": [
                                    {"name": "Active Power (kW)", "data": [0, 120, 450, 780, 920, 850, 310, 0]},
                                    {"name": "POA Irradiance (W/m²)", "data": [0, 150, 520, 890, 1010, 930, 340, 0]},
                                ],
                            },
                        )
                    ],
                    stop_reason="tool_use",
                    usage=Usage(input_tokens=160, output_tokens=70),
                    model=self.model,
                )

        # Case D: Inverters / Asset hierarchy
        if any(w in prompt_lower for w in ("asset", "inverter", "device", "hierarchy", "equipment")):
            if "list_assets" in avail_names:
                return ProviderResponse(
                    text_blocks=[TextBlock(text="Retrieving plant asset hierarchy...")],
                    tool_use_blocks=[
                        ToolUseBlock(
                            id=f"call_{uuid4().hex[:12]}",
                            name="list_assets",
                            arguments={"asset_type": "inverter"},
                        )
                    ],
                    stop_reason="tool_use",
                    usage=Usage(input_tokens=120, output_tokens=40),
                    model=self.model,
                )

        # Case E: Plant summary (default operational tool for SCADA telemetry inquiries)
        if any(w in prompt_lower for w in ("summary", "status", "overview", "generation", "power", "solar", "surya")) or tools:
            if "get_plant_summary" in avail_names:
                return ProviderResponse(
                    text_blocks=[TextBlock(text="Retrieving plant operating summary and active telemetry metrics...")],
                    tool_use_blocks=[
                        ToolUseBlock(
                            id=f"call_{uuid4().hex[:12]}",
                            name="get_plant_summary",
                            arguments={},
                        )
                    ],
                    stop_reason="tool_use",
                    usage=Usage(input_tokens=130, output_tokens=40),
                    model=self.model,
                )

        # Case F: Conversational general question without tool use
        text = (
            "Hello! I am the PlantIQ AI Solar Copilot (Mock LLM Mode). "
            "I can assist you with real-time SCADA telemetry analysis, Performance Ratio tracking, "
            "inverter underperformance investigation, and interactive chart generation. "
            "How can I assist you with your plant operations today?"
        )
        return ProviderResponse(
            text_blocks=[TextBlock(text=text)],
            stop_reason="end_turn",
            usage=Usage(input_tokens=90, output_tokens=55),
            model=self.model,
        )

    def _synthesize_tool_synthesis(self, messages: List[Message]) -> ProviderResponse:
        """Synthesize final response referencing executed tool outputs with citation markers."""
        last_msg = messages[-1].content or ""

        # Determine which tool was executed from scada_data header
        tool_match = re.search(r'<scada_data\s+seq="(\d+)"\s+tool="([^"]+)">', last_msg)
        seq = tool_match.group(1) if tool_match else "1"
        tool_name = tool_match.group(2) if tool_match else "scada_tool"
        tag = f"[T{seq}]"

        if tool_name == "get_plant_summary":
            text = (
                f"Based on the plant telemetry analysis {tag}, the solar farm has an installed capacity of "
                f"27.50 MW AC / 28.28 MWp DC with 22 active central inverters and 1 weather monitoring station. "
                f"The plant Performance Ratio is currently tracking at 103.0% to 109.5% against measured POA irradiance, "
                f"and active inverters are operating nominally."
            )
        elif tool_name == "list_anomalies":
            text = (
                f"According to the anomaly inbox records {tag}, historical PR deviations have been verified and "
                f"reconciled against the measured POA baseline. Inverter 1BY6WEcLGh8j5v7 remains acknowledged by "
                f"engineering triage (investigating DC disconnect switch), while all other inverters show nominal generation."
            )
        elif tool_name == "compute_kpi":
            text = (
                f"The IEC 61724-1 solar KPI computation {tag} confirms a 24-hour plant Performance Ratio of 109.5% "
                f"with 130.08 MWh measured generation versus 118.80 MWh expected generation. Net generation shortfall "
                f"is 0.0 MWh, indicating optimal generation efficiency."
            )
        elif tool_name == "render_chart":
            text = (
                f"I have rendered the solar generation and POA irradiance profile chart {tag} for your selected interval. "
                f"The power curve accurately tracks daylight solar irradiance with nominal inverter ramp-up and ramp-down."
            )
        elif tool_name == "list_assets":
            text = (
                f"The plant asset tree {tag} contains 22 inverters (INV-01 through INV-22) and weather monitoring station "
                f"WS-01. All telemetry channels are actively transmitting 15-minute readings."
            )
        elif tool_name == "compare_assets":
            text = (
                f"Cross-inverter comparison {tag} shows consistent generation across all 22 units. "
                f"Minor relative variance was observed on inverters 1BY6WEcLGh8j5v7 and bvBOhCH3iADSZry over the evaluation window."
            )
        else:
            text = (
                f"Operational SCADA tool execution {tag} for {tool_name} completed successfully. "
                f"The telemetry data has been verified and aligned with plant baseline parameters."
            )

        return ProviderResponse(
            text_blocks=[TextBlock(text=text)],
            stop_reason="end_turn",
            usage=Usage(input_tokens=280, output_tokens=90),
            model=self.model,
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
        """Stream response deltas incrementally with realistic chunk pacing."""
        resp = await self.chat(
            messages=messages,
            tools=tools,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )

        if resp.has_tool_use:
            # Yield tool use block
            yield StreamDelta(
                delta_text="",
                tool_use_blocks=resp.tool_use_blocks,
                usage=resp.usage,
                stop_reason="tool_use",
            )
            return

        # Stream text in chunks
        full_text = resp.text
        for i in range(0, len(full_text), self.chunk_size):
            chunk = full_text[i : i + self.chunk_size]
            yield StreamDelta(delta_text=chunk)
            # Brief cooperative yield to simulate network streaming
            await asyncio.sleep(0.005)

        # Final delta with usage and stop reason
        yield StreamDelta(
            delta_text="",
            usage=resp.usage,
            stop_reason=resp.stop_reason or "end_turn",
        )
