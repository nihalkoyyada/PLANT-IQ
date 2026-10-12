"""Copilot Agent Loop & Multi-Step Orchestration Engine (§10.2, §10.3, Task S5-AI-02).

Manages:
1. Multi-turn reasoning and tool-use execution loop with LLM provider.
2. Strict 15-tool execution cap (MAX_TOOL_CALLS = 15) to prevent loops or token runaway.
3. Database persistence for conversations, messages, tool_calls, and rendered charts.
4. Citation marker extraction ([T1], [T2], ...) linking final answers to tool outputs.
5. Non-streaming and streaming execution modes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.copilot.citation import CitationMetadata, extract_citations
from app.copilot.context import ToolSecurityContext
from app.copilot.guardrails import (
    sanitize_scada_data,
    validate_input_prompt,
    validate_output_content,
)
from app.copilot.prompts import build_copilot_system_prompt
from app.copilot.registry import CopilotToolRegistry, default_tool_registry
from app.copilot.result_store import default_chart_store
from app.llm.base import BaseProvider
from app.llm.factory import get_llm_provider
from app.llm.types import Message as LLMMessage, ProviderResponse, Usage
from app.models.entities import ChartRecord, Conversation, Message, Plant, ToolCallRecord

logger = logging.getLogger("plantiq.copilot.orchestrator")

MAX_TOOL_CALLS = 15
MAX_TURNS = 10


def sanitize_json_payload(obj: Any) -> Any:
    """Recursively convert Decimal, UUID, date, datetime, and custom objects to standard JSON primitives."""
    if isinstance(obj, dict):
        return {str(k): sanitize_json_payload(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return [sanitize_json_payload(v) for v in obj]
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, UUID):
        return str(obj)
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


@dataclass
class ToolTraceStep:
    """Audit record of a single tool execution step within a conversational turn."""

    seq: int
    tool_name: str
    arguments: Dict[str, Any]
    raw_output: Dict[str, Any]
    status: str  # 'ok', 'error', 'rejected'
    duration_ms: int
    tool_call_id: Optional[UUID] = None
    chart_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "raw_output": self.raw_output,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "tool_call_id": str(self.tool_call_id) if self.tool_call_id else None,
            "chart_id": self.chart_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CopilotExecutionResult:
    """Complete finalized result of an agent orchestration interaction turn."""

    conversation_id: UUID
    message_id: UUID
    user_message_id: UUID
    content: str
    tool_trace: List[ToolTraceStep]
    citations: List[CitationMetadata]
    charts: List[Dict[str, Any]]
    usage: Usage
    model: str
    latency_ms: int
    tool_calls_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation_id": str(self.conversation_id),
            "message_id": str(self.message_id),
            "user_message_id": str(self.user_message_id),
            "content": self.content,
            "tool_trace": [step.to_dict() for step in self.tool_trace],
            "citations": [c.model_dump() for c in self.citations],
            "charts": self.charts,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "total_tokens": self.usage.total_tokens,
            },
            "model": self.model,
            "latency_ms": self.latency_ms,
            "tool_calls_count": self.tool_calls_count,
        }


class CopilotOrchestrator:
    """Core tool-use agent loop coordinating the LLM and 12 Copilot SCADA tools."""

    def __init__(
        self,
        provider: Optional[BaseProvider] = None,
        registry: Optional[CopilotToolRegistry] = None,
        max_tool_calls: int = MAX_TOOL_CALLS,
        max_turns: int = MAX_TURNS,
    ) -> None:
        self._provider = provider
        self.registry = registry or default_tool_registry
        self.max_tool_calls = max_tool_calls
        self.max_turns = max_turns

    @property
    def provider(self) -> BaseProvider:
        """Lazily resolve LLM provider if not explicitly injected."""
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    def _get_or_create_conversation(
        self,
        session: Session,
        user_id: UUID,
        plant_id: UUID,
        conversation_id: Optional[UUID],
        prompt: str,
    ) -> Conversation:
        """Fetch existing conversation or instantiate a new conversation thread."""
        if conversation_id:
            conv = session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            ).scalar_one_or_none()
            if conv:
                return conv

        # Create new conversation thread
        conv = Conversation(
            id=conversation_id or uuid4(),
            user_id=user_id,
            plant_id=plant_id,
            title=(prompt[:97] + "..." if len(prompt) > 100 else prompt).strip(),
        )
        session.add(conv)
        session.flush()
        return conv

    def _load_history(
        self,
        session: Session,
        conversation_id: UUID,
        current_user_msg_id: UUID,
        limit: int = 20,
    ) -> List[LLMMessage]:
        """Load prior conversation messages formatted for the LLM provider."""
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.id != current_user_msg_id,
            )
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        history_records = session.execute(stmt).scalars().all()
        history_msgs: List[LLMMessage] = []

        for rec in history_records:
            role = rec.role if rec.role in ("user", "assistant") else "user"
            history_msgs.append(LLMMessage(role=role, content=rec.content))

        return history_msgs

    def _build_system_prompt(self, session: Session, plant_id: Optional[UUID]) -> str:
        """Formulate localized system prompt with active plant metadata."""
        if not plant_id:
            return build_copilot_system_prompt()

        plant = session.execute(
            select(Plant).where(Plant.id == plant_id)
        ).scalar_one_or_none()

        if not plant:
            return build_copilot_system_prompt()

        return build_copilot_system_prompt(
            plant_name=plant.name,
            capacity_ac_kw=float(plant.capacity_ac_kw) if plant.capacity_ac_kw is not None else None,
            capacity_dc_kwp=float(plant.capacity_dc_kwp) if plant.capacity_dc_kwp is not None else None,
            timezone_name=plant.timezone,
            tariff_inr_per_kwh=float(plant.tariff_inr_per_kwh) if plant.tariff_inr_per_kwh is not None else None,
            expected_pr=float(plant.expected_pr) if plant.expected_pr is not None else None,
        )

    async def execute(
        self,
        prompt: str,
        context: ToolSecurityContext,
        session: Session,
        conversation_id: Optional[UUID] = None,
    ) -> CopilotExecutionResult:
        """Run complete conversational tool-use agent loop for a user query (§10.2).

        Args:
            prompt: User natural-language question or instruction.
            context: Verified ToolSecurityContext for multi-tenant isolation.
            session: Active SQLAlchemy database session.
            conversation_id: Optional ID of existing conversation thread.

        Returns:
            CopilotExecutionResult with final content, tool trace, citations, and charts.
        """
        start_time = time.monotonic()

        # 1. Ensure plant_id exists in context
        plant_id = context.plant_id
        if not plant_id:
            raise ValueError("ToolSecurityContext must have a plant_id to execute Copilot queries.")

        # 2. Get or create conversation thread
        conversation = self._get_or_create_conversation(
            session=session,
            user_id=context.user_id,
            plant_id=plant_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )

        # 3. Persist incoming user message
        user_msg = Message(
            conversation_id=conversation.id,
            role="user",
            content=prompt,
            tool_ids=[],
        )
        session.add(user_msg)
        session.flush()

        # 4. Check Input Guardrails (Prompt injection, jailbreak, off-topic)
        guard_res = validate_input_prompt(prompt)
        if not guard_res.allowed:
            rejection_text = guard_res.rejection_message or "Request blocked by security guardrails."
            total_latency_ms = max(1, int((time.monotonic() - start_time) * 1000))
            assistant_msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=rejection_text,
                model="guardrail",
                latency_ms=total_latency_ms,
                tool_ids=[],
            )
            session.add(assistant_msg)
            session.commit()
            return CopilotExecutionResult(
                conversation_id=conversation.id,
                message_id=assistant_msg.id,
                user_message_id=user_msg.id,
                content=rejection_text,
                tool_trace=[],
                citations=[],
                charts=[],
                usage=Usage(input_tokens=0, output_tokens=0),
                model="guardrail",
                latency_ms=total_latency_ms,
                tool_calls_count=0,
            )

        sanitized_user_prompt = guard_res.sanitized_prompt

        # 5. Assemble system prompt and conversation messages
        system_prompt = self._build_system_prompt(session, plant_id)
        prior_history = self._load_history(session, conversation.id, user_msg.id)

        llm_messages: List[LLMMessage] = list(prior_history)
        llm_messages.append(LLMMessage(role="user", content=sanitized_user_prompt))

        # 5. Core Agent Reasoning & Tool Execution Loop
        tool_defs = self.registry.get_tool_definitions()
        tool_trace: List[ToolTraceStep] = []
        total_input_tokens = 0
        total_output_tokens = 0
        final_text = ""
        model_name = self.provider.model
        turn = 0

        while turn < self.max_turns:
            turn += 1
            available_tools = tool_defs if len(tool_trace) < self.max_tool_calls else None

            # If cap reached, instruct model to produce final synthesis
            if len(tool_trace) >= self.max_tool_calls:
                llm_messages.append(
                    LLMMessage(
                        role="user",
                        content=(
                            f"[SYSTEM NOTICE: Maximum execution cap of {self.max_tool_calls} tool calls "
                            f"has been reached. Do NOT attempt to invoke more tools. Synthesize your final "
                            f"detailed response now based strictly on the data already retrieved, including "
                            f"relevant citation markers [T1]..[T{len(tool_trace)}].]"
                        ),
                    )
                )

            # Invoke LLM provider
            response: ProviderResponse = await self.provider.chat(
                messages=llm_messages,
                tools=available_tools,
                system=system_prompt,
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            if response.model:
                model_name = response.model

            # Check if LLM requested tools
            if not response.has_tool_use:
                final_text = response.text
                break

            # Process requested tool invocations
            assistant_content = response.text or "Executing operational diagnostic tools..."
            llm_messages.append(LLMMessage(role="assistant", content=assistant_content))

            for tool_call in response.tool_use_blocks:
                # Enforce strict 15-call safety cap
                if len(tool_trace) >= self.max_tool_calls:
                    seq = len(tool_trace) + 1
                    rejected_step = ToolTraceStep(
                        seq=seq,
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                        raw_output={
                            "success": False,
                            "error": "tool_cap_exceeded",
                            "message": f"Execution cap of {self.max_tool_calls} tools reached. Tool was not executed.",
                        },
                        status="rejected",
                        duration_ms=0,
                    )
                    tool_trace.append(rejected_step)
                    continue

                # Prepare tool arguments with active plant context fallback
                tool_args = dict(tool_call.arguments or {})
                tool_meta = self.registry.get_tool(tool_call.name)
                if (
                    tool_meta
                    and hasattr(tool_meta.schema, "model_fields")
                    and "plant_id" in tool_meta.schema.model_fields
                    and "plant_id" not in tool_args
                    and context.plant_id
                ):
                    tool_args["plant_id"] = str(context.plant_id)

                seq = len(tool_trace) + 1
                t0 = time.monotonic()

                # Dispatch tool execution under user security context
                tool_result = self.registry.execute_tool(
                    name=tool_call.name,
                    arguments=tool_args,
                    context=context,
                    session=session,
                )
                duration_ms = max(1, int((time.monotonic() - t0) * 1000))

                # Map status code adhering to ck_tool_calls_status constraint ('ok', 'error', 'rejected')
                if tool_result.get("success"):
                    status = "ok"
                elif tool_result.get("error") == "security_scope_error":
                    status = "rejected"
                else:
                    status = "error"

                # Check if an interactive chart was compiled
                chart_id: Optional[str] = None
                if tool_call.name == "render_chart" and tool_result.get("success"):
                    chart_id = tool_result.get("data", {}).get("chart_id")

                clean_output = sanitize_json_payload(tool_result)
                clean_args = sanitize_json_payload(tool_args)

                step = ToolTraceStep(
                    seq=seq,
                    tool_name=tool_call.name,
                    arguments=clean_args,
                    raw_output=clean_output,
                    status=status,
                    duration_ms=duration_ms,
                    chart_id=chart_id,
                )
                tool_trace.append(step)

                # Sanitize SCADA data to neutralize any delimiter breaks or embedded injection strings
                safe_output = sanitize_scada_data(clean_output)
                serialized_output = json.dumps(safe_output, default=str)
                # Keep individual tool output within reasonable token bounds
                if len(serialized_output) > 25000:
                    serialized_output = serialized_output[:25000] + "... [output truncated for context length]"

                tool_response_text = (
                    f"<scada_data seq=\"{seq}\" tool=\"{tool_call.name}\">\n"
                    f"Tool result for [T{seq}] ({tool_call.name}):\n{serialized_output}\n"
                    f"</scada_data>"
                )
                llm_messages.append(LLMMessage(role="user", content=tool_response_text))

        # Fallback if text is somehow empty
        if not final_text:
            final_text = "Analysis completed. Telemetry data has been retrieved."

        # 6. Apply Output Guardrails (System Prompt Leakage / Credential Redaction)
        output_guard = validate_output_content(final_text)
        final_text = output_guard.sanitized_content

        # 7. Extract citation markers mapping to executed tools
        citations = extract_citations(final_text, tool_trace)

        # 7. Collect rendered charts from ChartStore
        rendered_charts: List[Dict[str, Any]] = []
        for step in tool_trace:
            if step.chart_id:
                cached_chart = default_chart_store.get(step.chart_id)
                if cached_chart:
                    rendered_charts.append(sanitize_json_payload(cached_chart))

        total_latency_ms = max(1, int((time.monotonic() - start_time) * 1000))

        # 8. Persist trace records to PostgreSQL
        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=final_text,
            model=model_name,
            latency_ms=total_latency_ms,
            tool_ids=[],
        )
        session.add(assistant_msg)
        session.flush()

        persisted_tool_ids: List[UUID] = []
        for step in tool_trace:
            tool_rec = ToolCallRecord(
                message_id=assistant_msg.id,
                seq=step.seq,
                tool_name=step.tool_name,
                input=step.arguments,
                output=step.raw_output,
                status=step.status,
                duration_ms=step.duration_ms,
            )
            session.add(tool_rec)
            session.flush()
            step.tool_call_id = tool_rec.id
            persisted_tool_ids.append(tool_rec.id)

        # Update assistant_msg tool_ids array
        assistant_msg.tool_ids = persisted_tool_ids

        # Persist charts linked to this assistant message
        for chart_spec in rendered_charts:
            chart_rec = ChartRecord(
                message_id=assistant_msg.id,
                spec=chart_spec,
            )
            session.add(chart_rec)

        session.commit()

        # Update citation metadata with persisted tool_call_ids
        for citation in citations:
            if 1 <= citation.index <= len(tool_trace):
                citation.tool_call_id = tool_trace[citation.index - 1].tool_call_id

        return CopilotExecutionResult(
            conversation_id=conversation.id,
            message_id=assistant_msg.id,
            user_message_id=user_msg.id,
            content=final_text,
            tool_trace=tool_trace,
            citations=citations,
            charts=rendered_charts,
            usage=Usage(input_tokens=total_input_tokens, output_tokens=total_output_tokens),
            model=model_name,
            latency_ms=total_latency_ms,
            tool_calls_count=len(tool_trace),
        )

    async def stream(
        self,
        prompt: str,
        context: ToolSecurityContext,
        session: Session,
        conversation_id: Optional[UUID] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream execution events and incremental tokens over Server-Sent Events (SSE).

        Yields:
            Event dictionaries: 'start', 'tool_start', 'tool_end', 'chart', 'delta', 'done'.
        """
        # Execute the agent reasoning and persistence
        result = await self.execute(
            prompt=prompt,
            context=context,
            session=session,
            conversation_id=conversation_id,
        )

        # Emit initial start event
        yield {
            "event": "start",
            "conversation_id": str(result.conversation_id),
            "message_id": str(result.message_id),
        }

        # Emit tool execution history
        for step in result.tool_trace:
            yield {
                "event": "tool_start",
                "seq": step.seq,
                "tool": step.tool_name,
                "tag": f"[T{step.seq}]",
                "arguments": step.arguments,
            }
            yield {
                "event": "tool_end",
                "seq": step.seq,
                "tool": step.tool_name,
                "status": step.status,
                "duration_ms": step.duration_ms,
            }

        # Emit any rendered charts
        for chart in result.charts:
            yield {
                "event": "chart",
                "chart": chart,
            }

        # Stream content in realistic chunks
        chunk_size = 24
        for i in range(0, len(result.content), chunk_size):
            yield {
                "event": "delta",
                "text": result.content[i : i + chunk_size],
            }

        # Emit done event with complete result
        yield {
            "event": "done",
            "result": result.to_dict(),
        }
