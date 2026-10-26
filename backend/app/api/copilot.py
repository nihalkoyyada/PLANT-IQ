"""Copilot API Endpoints (§10.2, §10.3, Tasks S5-AI-01 & S5-AI-02).

Provides:
- Conversational chat endpoint with multi-step tool orchestration and trace persistence.
- Streaming chat endpoint via Server-Sent Events (SSE).
- Retrieval of conversation threads, interaction turns, and "Show working" tool traces.
- Retrieval of cached large timeseries results (ResultRefStore).
- Retrieval of cached interactive charts (ChartStore).
- Direct operational tool execution and schema inspection.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.copilot.context import ToolSecurityContext
from app.copilot.orchestrator import CopilotOrchestrator
from app.copilot.registry import default_tool_registry
from app.copilot.result_store import default_chart_store, default_result_store
from app.db.database import get_db
from app.models.entities import Conversation, Message, Plant, User

router = APIRouter(
    prefix="/copilot",
    tags=["Copilot"],
)


class ExecuteToolRequest(BaseModel):
    """Payload for invoking a Copilot tool operational handler directly."""

    tool: str = Field(..., description="Tool name (e.g. 'query_timeseries', 'get_plant_summary').")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool parameter arguments.")
    plant_id: Optional[UUID] = Field(None, description="Optional target plant ID context.")


class CopilotChatRequest(BaseModel):
    """Payload for conversational interaction turn with Copilot agent loop."""

    prompt: str = Field(..., description="Natural-language question or instruction.")
    plant_id: UUID = Field(..., description="Target plant ID context.")
    conversation_id: Optional[UUID] = Field(None, description="Optional ID of existing conversation thread.")
    client_message_id: Optional[UUID] = Field(None, description="Optional client message ID for request tracking and idempotency.")


def _verify_plant_access(plant_id: UUID, current_user: User, db: Session) -> Plant:
    """Ensure user organization owns the specified plant."""
    plant = db.execute(
        select(Plant).where(Plant.id == plant_id, Plant.org_id == current_user.org_id)
    ).scalar_one_or_none()
    if not plant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Plant '{plant_id}' does not belong to your organization.",
        )
    return plant


@router.post("/chat")
async def chat_copilot(
    request: CopilotChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Execute conversational turn through Copilot multi-step tool agent loop (§10.2).

    Executes tools, records full traces, extracts citation markers, and persists audit state.
    """
    _verify_plant_access(request.plant_id, current_user, db)

    context = ToolSecurityContext(
        org_id=current_user.org_id,
        plant_id=request.plant_id,
        user_id=current_user.id,
        user_role=current_user.role,
    )

    orchestrator = CopilotOrchestrator()
    result = await orchestrator.execute(
        prompt=request.prompt,
        context=context,
        session=db,
        conversation_id=request.conversation_id,
    )

    return result.to_dict()


@router.post("/chat/stream")
async def stream_copilot(
    request: CopilotChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream Copilot agent execution events and tokens incrementally over SSE."""
    _verify_plant_access(request.plant_id, current_user, db)

    context = ToolSecurityContext(
        org_id=current_user.org_id,
        plant_id=request.plant_id,
        user_id=current_user.id,
        user_role=current_user.role,
    )

    orchestrator = CopilotOrchestrator()

    async def sse_event_generator() -> AsyncIterator[str]:
        try:
            async for event in orchestrator.stream(
                prompt=request.prompt,
                context=context,
                session=db,
                conversation_id=request.conversation_id,
            ):
                event_type = event.get("event", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event, default=str)}\n\n"
        except asyncio.CancelledError:
            # Client disconnected or cancelled request
            pass

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/info")
def get_copilot_info(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieve Copilot runtime provider status, model name, and tool capabilities."""
    orchestrator = CopilotOrchestrator()
    provider = orchestrator.provider
    model_name = provider.model or "unknown"
    is_mock = "mock" in model_name.lower() or provider.__class__.__name__ == "MockLLMProvider"

    tool_names = default_tool_registry.list_tool_names()
    return {
        "provider": "mock" if is_mock else "live",
        "provider_class": provider.__class__.__name__,
        "model": model_name,
        "is_mock": is_mock,
        "tool_count": len(tool_names),
        "tools": tool_names,
    }


@router.get("/conversations")
def list_conversations(
    plant_id: UUID = Query(..., description="Target plant ID."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """List conversation threads for a plant within the authenticated organization."""
    _verify_plant_access(plant_id, current_user, db)

    stmt = (
        select(Conversation)
        .where(
            Conversation.plant_id == plant_id,
            Conversation.user_id == current_user.id,
        )
        .order_by(Conversation.created_at.desc())
    )
    convs = db.execute(stmt).scalars().all()

    return {
        "conversations": [
            {
                "id": str(c.id),
                "title": c.title,
                "plant_id": str(c.plant_id),
                "created_at": c.created_at.isoformat(),
                "message_count": len(c.messages),
            }
            for c in convs
        ],
        "count": len(convs),
    }


@router.get("/conversations/{conversation_id}")
def get_conversation_details(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get complete conversation thread with message turns, charts, and 'Show working' tool trace."""
    stmt = (
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = db.execute(stmt).scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )

    # Serialize message turns and tool calls
    turns = []
    for msg in conv.messages:
        turn_data: Dict[str, Any] = {
            "id": str(msg.id),
            "role": msg.role,
            "content": msg.content,
            "model": msg.model,
            "latency_ms": msg.latency_ms,
            "created_at": msg.created_at.isoformat(),
            "tool_calls": [
                {
                    "id": str(tc.id),
                    "seq": tc.seq,
                    "tool_name": tc.tool_name,
                    "input": tc.input,
                    "output": tc.output,
                    "status": tc.status,
                    "duration_ms": tc.duration_ms,
                    "created_at": tc.created_at.isoformat(),
                }
                for tc in msg.tool_calls
            ],
            "charts": [
                {
                    "id": str(ch.id),
                    "spec": ch.spec,
                    "created_at": ch.created_at.isoformat(),
                }
                for ch in msg.charts
            ],
        }
        turns.append(turn_data)

    return {
        "id": str(conv.id),
        "title": conv.title,
        "plant_id": str(conv.plant_id),
        "created_at": conv.created_at.isoformat(),
        "messages": turns,
    }


@router.get("/tools")
def list_copilot_tools(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """List all registered Copilot operational tools and their schemas."""
    definitions = default_tool_registry.get_tool_definitions()
    return {
        "tools": [
            {
                "name": d.name,
                "description": d.description,
                "parameters": d.parameters,
            }
            for d in definitions
        ],
        "count": len(definitions),
    }


@router.post("/tools/execute")
def execute_copilot_tool(
    request: ExecuteToolRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Execute a Copilot operational tool within the user's multi-tenant security context."""
    context = ToolSecurityContext(
        org_id=current_user.org_id,
        plant_id=request.plant_id,
        user_id=current_user.id,
        user_role=current_user.role,
    )

    result = default_tool_registry.execute_tool(
        name=request.tool,
        arguments=request.arguments,
        context=context,
        session=db,
    )

    if not result.get("success"):
        error_type = result.get("error")
        if error_type == "security_scope_error":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=result.get("message"),
            )
        elif error_type in ("unknown_tool", "validation_error"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message"),
            )

    return result


@router.get("/results/{ref_id}")
def get_cached_timeseries_result(
    ref_id: str,
    current_user: User = Depends(get_current_user),
) -> Any:
    """Retrieve full timeseries coordinates for a cached result reference ID."""
    cached = default_result_store.get(ref_id)
    if not cached:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Result reference '{ref_id}' not found or has expired from cache.",
        )
    return cached


@router.get("/charts/{chart_id}")
def get_cached_chart_spec(
    chart_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieve rendered chart specification for an interactive ECharts visualization."""
    chart = default_chart_store.get(chart_id)
    if not chart:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chart '{chart_id}' not found or has expired from cache.",
        )
    return chart
