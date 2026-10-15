"""Comprehensive Test Suite for Copilot Agent Loop & Orchestration (§10.2, §10.3, Task S5-AI-02).

Tests:
1. Core Agent Loop & Multi-step reasoning with tools.
2. Safety Controls: Strict 15-call cap prevents infinite recursion/runaway execution.
3. Trace Persistence: Full DB audit persistence for conversations, messages, tool_calls, charts.
4. Citation Markers: Parsing and validation of [T1], [T2], ... citation tags.
5. Chart Rendering integration: ChartStore and ChartRecord DB persistence.
6. Multi-tenant security scoping & isolation.
7. REST API endpoints: /copilot/chat, /copilot/chat/stream, /copilot/conversations.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient

from app.api.copilot import router
from app.core.security import create_access_token
from app.copilot.citation import CitationMetadata, extract_citations, validate_citations
from app.copilot.context import ToolSecurityContext
from app.copilot.orchestrator import (
    CopilotExecutionResult,
    CopilotOrchestrator,
    MAX_TOOL_CALLS,
    ToolTraceStep,
)
from app.copilot.registry import default_tool_registry
from app.copilot.result_store import default_chart_store
from app.db.database import SessionLocal
from app.llm.base import BaseProvider
from app.llm.types import Message as LLMMessage, ProviderResponse, StreamDelta, TextBlock, ToolDefinition, ToolUseBlock, Usage
from app.main import app
from app.models.entities import (
    ChartRecord,
    Conversation,
    Message,
    Organization,
    Plant,
    ToolCallRecord,
    User,
)


class MockProvider(BaseProvider):
    """Controllable mock LLM provider for orchestration unit testing."""

    def __init__(self, responses: Optional[List[ProviderResponse]] = None, model: str = "mock-llm-v1"):
        super().__init__(model=model)
        self.responses = list(responses or [])
        self.call_count = 0
        self.received_messages: List[List[LLMMessage]] = []
        self.received_tools: List[Optional[List[ToolDefinition]]] = []

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> ProviderResponse:
        self.call_count += 1
        self.received_messages.append(messages)
        self.received_tools.append(tools)

        if self.responses:
            return self.responses.pop(0)

        return ProviderResponse(
            text_blocks=[TextBlock(text="Default fallback response.")],
            stop_reason="end_turn",
            usage=Usage(10, 10),
            model=self.model,
        )

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[StreamDelta]:
        resp = await self.chat(messages, tools, system, max_tokens, temperature, timeout)
        yield StreamDelta(delta_text=resp.text, usage=resp.usage, stop_reason=resp.stop_reason)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def orch_db():
    """Setup organizations, users, and plants for orchestrator testing."""
    db = SessionLocal()
    try:
        # Org 1 & User 1
        org1 = db.query(Organization).filter(Organization.name == "Orchestrator Org 1").first()
        if not org1:
            org1 = Organization(name="Orchestrator Org 1")
            db.add(org1)
            db.commit()
            db.refresh(org1)

        user1 = db.query(User).filter(User.email == "orch_user_1@test.com").first()
        if not user1:
            user1 = User(
                org_id=org1.id,
                email="orch_user_1@test.com",
                password_hash="hash",
                full_name="Orchestrator User 1",
                role="engineer",
                is_active=True,
            )
            db.add(user1)
            db.commit()
            db.refresh(user1)

        # Org 2 & User 2 (Cross-tenant attacker)
        org2 = db.query(Organization).filter(Organization.name == "Orchestrator Org 2").first()
        if not org2:
            org2 = Organization(name="Orchestrator Org 2")
            db.add(org2)
            db.commit()
            db.refresh(org2)

        user2 = db.query(User).filter(User.email == "orch_user_2@test.com").first()
        if not user2:
            user2 = User(
                org_id=org2.id,
                email="orch_user_2@test.com",
                password_hash="hash",
                full_name="Orchestrator User 2",
                role="engineer",
                is_active=True,
            )
            db.add(user2)
            db.commit()
            db.refresh(user2)

        # Plant 1 (owned by Org 1)
        plant1 = db.query(Plant).filter(Plant.name == "Orch Solar Plant 1", Plant.org_id == org1.id).first()
        if not plant1:
            plant1 = Plant(
                org_id=org1.id,
                name="Orch Solar Plant 1",
                plant_type="solar",
                capacity_ac_kw=5000.0,
                capacity_dc_kwp=6000.0,
                tariff_inr_per_kwh=4.20,
                expected_pr=0.82,
                timezone="Asia/Kolkata",
            )
            db.add(plant1)
            db.commit()
            db.refresh(plant1)

        yield {
            "org1": org1,
            "user1": user1,
            "org2": org2,
            "user2": user2,
            "plant1": plant1,
        }
    finally:
        db.close()


@pytest.fixture
def db_session():
    """Isolated per-test database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# -------------------------------------------------------------------------
# 1. CITATION MECHANICS TESTS
# -------------------------------------------------------------------------

def test_citation_extraction_and_mapping():
    """Verify regex citation extraction and 1-based tool index resolution."""
    trace = [
        ToolTraceStep(
            seq=1,
            tool_name="get_plant_summary",
            arguments={"time_window_hours": 24},
            raw_output={"success": True, "data": {"capacity_ac_kw": 5000.0, "active_anomalies_count": 2}},
            status="ok",
            duration_ms=45,
            tool_call_id=uuid4(),
        ),
        ToolTraceStep(
            seq=2,
            tool_name="list_anomalies",
            arguments={"status": "open"},
            raw_output={"success": True, "data": {"anomalies": [{"id": "a1", "severity": "high"}]}},
            status="ok",
            duration_ms=30,
            tool_call_id=uuid4(),
        ),
    ]

    text = "The plant capacity is 5000 kW [T1], with 2 active anomalies detected [T1]. High severity issue found [T2]."
    citations = extract_citations(text, trace)

    assert len(citations) == 2
    assert citations[0].tag == "[T1]"
    assert citations[0].index == 1
    assert citations[0].tool_name == "get_plant_summary"
    assert citations[0].valid is True
    assert citations[0].status == "ok"

    assert citations[1].tag == "[T2]"
    assert citations[1].index == 2
    assert citations[1].tool_name == "list_anomalies"
    assert citations[1].valid is True


def test_citation_hallucination_detection():
    """Verify that citing out-of-bounds tool markers ([T99]) is flagged as invalid."""
    trace = [
        ToolTraceStep(
            seq=1,
            tool_name="get_current_time",
            arguments={},
            raw_output={"success": True, "data": {"server_utc": "2026-10-12T10:00:00Z"}},
            status="ok",
            duration_ms=5,
        ),
    ]

    text = "Current time retrieved [T1], but phantom data cited [T99]."
    citations = extract_citations(text, trace)

    assert len(citations) == 2
    assert citations[0].valid is True
    assert citations[1].tag == "[T99]"
    assert citations[1].valid is False
    assert citations[1].status == "invalid"

    audit = validate_citations(text, total_tools_executed=1)
    assert audit["is_valid"] is False
    assert 99 in audit["invalid_citations"]
    assert 1 in audit["valid_citations"]


# -------------------------------------------------------------------------
# 2. CORE AGENT LOOP & MULTI-STEP REASONING
# -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_loop_direct_answer(orch_db, db_session):
    """Test single-turn conversational execution without tool invocations."""
    db = db_session
    user = orch_db["user1"]
    plant = orch_db["plant1"]

    mock_resp = ProviderResponse(
        text_blocks=[TextBlock(text="Solar PV cells convert sunlight directly into electricity via the photovoltaic effect.")],
        stop_reason="end_turn",
        usage=Usage(input_tokens=150, output_tokens=25),
        model="claude-3-5-sonnet-20241022",
    )
    provider = MockProvider([mock_resp])
    orchestrator = CopilotOrchestrator(provider=provider)

    context = ToolSecurityContext(
        org_id=user.org_id,
        plant_id=plant.id,
        user_id=user.id,
        user_role=user.role,
    )

    result = await orchestrator.execute(
        prompt="Explain what a solar cell is.",
        context=context,
        session=db,
    )

    assert result.content.startswith("Solar PV cells convert sunlight")
    assert result.tool_calls_count == 0
    assert len(result.tool_trace) == 0
    assert len(result.citations) == 0
    assert result.model == "claude-3-5-sonnet-20241022"
    assert result.usage.total_tokens == 175

    # Verify database persistence
    conv_rec = db.query(Conversation).filter(Conversation.id == result.conversation_id).first()
    assert conv_rec is not None
    assert conv_rec.user_id == user.id
    assert conv_rec.plant_id == plant.id

    msg_rec = db.query(Message).filter(Message.id == result.message_id).first()
    assert msg_rec is not None
    assert msg_rec.role == "assistant"
    assert msg_rec.content == result.content
    assert msg_rec.tool_ids == []


@pytest.mark.asyncio
async def test_agent_loop_multi_step_tool_execution(orch_db, db_session):
    """Test multi-turn reasoning: Turn 1 requests tool, Turn 2 uses tool result with citation."""
    db = db_session
    user = orch_db["user1"]
    plant = orch_db["plant1"]

    # Turn 1: LLM decides to call get_plant_summary
    turn1_resp = ProviderResponse(
        text_blocks=[TextBlock(text="Checking plant summary telemetry...")],
        tool_use_blocks=[
            ToolUseBlock(id="call_summary", name="get_plant_summary", arguments={})
        ],
        stop_reason="tool_use",
        usage=Usage(120, 30),
        model="claude-3-5-sonnet-20241022",
    )

    # Turn 2: LLM receives tool output and writes final synthesized answer with citation [T1]
    turn2_resp = ProviderResponse(
        text_blocks=[
            TextBlock(
                text="The plant 'Orch Solar Plant 1' has an AC capacity of 5,000 kW and 0 active anomalies detected [T1]."
            )
        ],
        stop_reason="end_turn",
        usage=Usage(350, 40),
        model="claude-3-5-sonnet-20241022",
    )

    provider = MockProvider([turn1_resp, turn2_resp])
    orchestrator = CopilotOrchestrator(provider=provider)

    context = ToolSecurityContext(
        org_id=user.org_id,
        plant_id=plant.id,
        user_id=user.id,
        user_role=user.role,
    )

    result = await orchestrator.execute(
        prompt="What is the operational status of the plant?",
        context=context,
        session=db,
    )

    assert result.tool_calls_count == 1
    assert len(result.tool_trace) == 1
    assert result.tool_trace[0].tool_name == "get_plant_summary"
    assert result.tool_trace[0].status == "ok"
    assert result.tool_trace[0].seq == 1
    assert result.tool_trace[0].raw_output["success"] is True

    # Check citation mapping
    assert len(result.citations) == 1
    assert result.citations[0].tag == "[T1]"
    assert result.citations[0].tool_name == "get_plant_summary"
    assert result.citations[0].valid is True
    assert result.citations[0].tool_call_id is not None

    # Check DB persistence
    tool_rec = db.query(ToolCallRecord).filter(ToolCallRecord.id == result.tool_trace[0].tool_call_id).first()
    assert tool_rec is not None
    assert tool_rec.tool_name == "get_plant_summary"
    assert tool_rec.status == "ok"
    assert tool_rec.seq == 1

    assistant_msg = db.query(Message).filter(Message.id == result.message_id).first()
    assert assistant_msg is not None
    assert assistant_msg.tool_ids == [tool_rec.id]


# -------------------------------------------------------------------------
# 3. SAFETY CONTROLS (15-CALL EXECUTION CAP)
# -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_controls_15_call_cap(orch_db, db_session):
    """Enforce strict safety controls: 15-call tool limit cuts off runaway execution."""
    db = db_session
    user = orch_db["user1"]
    plant = orch_db["plant1"]

    # Construct an adversarial or looping LLM that requests 10 tools per turn
    def make_looping_response(turn_num: int) -> ProviderResponse:
        return ProviderResponse(
            text_blocks=[TextBlock(text=f"Turn {turn_num} requesting 10 tools")],
            tool_use_blocks=[
                ToolUseBlock(id=f"t_{turn_num}_{i}", name="get_current_time", arguments={})
                for i in range(10)
            ],
            stop_reason="tool_use",
            usage=Usage(100, 50),
        )

    final_resp = ProviderResponse(
        text_blocks=[TextBlock(text="Synthesized summary after safety cap [T1] [T15].")],
        stop_reason="end_turn",
        usage=Usage(200, 30),
    )

    # 2 turns with 10 tools each (20 tool calls total) followed by final synthesis
    responses = [make_looping_response(1), make_looping_response(2), final_resp]
    provider = MockProvider(responses)
    orchestrator = CopilotOrchestrator(provider=provider, max_tool_calls=MAX_TOOL_CALLS)

    context = ToolSecurityContext(
        org_id=user.org_id,
        plant_id=plant.id,
        user_id=user.id,
        user_role=user.role,
    )

    result = await orchestrator.execute(
        prompt="Run comprehensive diagnostic across all sensors.",
        context=context,
        session=db,
    )

    # Exactly 15 tool calls should have been allowed, excess rejected
    executed_ok = [step for step in result.tool_trace if step.status == "ok"]
    assert len(executed_ok) == 15
    # Any subsequent tool calls in the turn were recorded as 'rejected'
    assert len(result.tool_trace) >= 15
    rejected = [step for step in result.tool_trace if step.status == "rejected"]
    assert len(rejected) >= 1
    assert rejected[0].raw_output["error"] == "tool_cap_exceeded"

    # Verify system notice was delivered to LLM instructing synthesis
    last_call_tools = provider.received_tools[-1]
    assert last_call_tools is None, "Tools must be withheld once execution cap is reached."


# -------------------------------------------------------------------------
# 4. CHART RENDERING & CHART PERSISTENCE
# -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chart_rendering_trace_persistence(orch_db, db_session):
    """Verify tool_render_chart resolves, stores in ChartStore, and creates ChartRecord in DB."""
    db = db_session
    user = orch_db["user1"]
    plant = orch_db["plant1"]

    chart_input = {
        "title": "Plant 1 Active Power Profile",
        "chart_type": "line",
        "x_axis": {"label": "Timestamp", "type": "time"},
        "y_axis": {"label": "Power (kW)", "unit": "kW"},
        "series": [
            {
                "name": "Active Power",
                "data_points": [
                    {"x": "2026-10-12T08:00:00Z", "y": 1200.0},
                    {"x": "2026-10-12T09:00:00Z", "y": 2800.0},
                    {"x": "2026-10-12T10:00:00Z", "y": 4500.0},
                ],
            }
        ],
    }

    turn1 = ProviderResponse(
        tool_use_blocks=[
            ToolUseBlock(id="call_chart", name="render_chart", arguments=chart_input)
        ],
        stop_reason="tool_use",
        usage=Usage(100, 40),
    )
    turn2 = ProviderResponse(
        text_blocks=[TextBlock(text="Here is the generation profile curve [T1]. Peak generation reached 4,500 kW.")],
        stop_reason="end_turn",
        usage=Usage(200, 30),
    )

    provider = MockProvider([turn1, turn2])
    orchestrator = CopilotOrchestrator(provider=provider)

    context = ToolSecurityContext(
        org_id=user.org_id,
        plant_id=plant.id,
        user_id=user.id,
        user_role=user.role,
    )

    result = await orchestrator.execute(
        prompt="Plot the generation curve for today.",
        context=context,
        session=db,
    )

    assert len(result.charts) == 1
    assert result.charts[0]["title"] == "Plant 1 Active Power Profile"
    assert result.tool_trace[0].chart_id is not None

    # Check DB persistence in charts table
    chart_rec = db.query(ChartRecord).filter(ChartRecord.message_id == result.message_id).first()
    assert chart_rec is not None
    assert chart_rec.spec["title"] == "Plant 1 Active Power Profile"


# -------------------------------------------------------------------------
# 5. MULTI-TENANT ISOLATION & REST API ENDPOINTS
# -------------------------------------------------------------------------

def test_copilot_chat_cross_tenant_forbidden(client, orch_db):
    """User 2 (Org 2) must be strictly blocked with HTTP 403 when querying Plant 1 (Org 1)."""
    user2 = orch_db["user2"]
    plant1 = orch_db["plant1"]

    token = create_access_token({"sub": str(user2.id), "org_id": str(user2.org_id), "role": user2.role})
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "prompt": "Show plant status",
        "plant_id": str(plant1.id),
    }

    res = client.post("/copilot/chat", json=payload, headers=headers)
    assert res.status_code == 403
    assert "Access denied" in res.json()["detail"]


def test_copilot_conversations_and_working_trace_api(client, orch_db, monkeypatch):
    """Test /copilot/conversations and /copilot/conversations/{id} retrieving full 'Show working' trace."""
    user1 = orch_db["user1"]
    plant1 = orch_db["plant1"]

    token = create_access_token({"sub": str(user1.id), "org_id": str(user1.org_id), "role": user1.role})
    headers = {"Authorization": f"Bearer {token}"}

    # Mock provider to avoid live API keys during API test
    mock_resp1 = ProviderResponse(
        tool_use_blocks=[ToolUseBlock(id="t1", name="get_current_time", arguments={})],
        stop_reason="tool_use",
        usage=Usage(50, 10),
    )
    mock_resp2 = ProviderResponse(
        text_blocks=[TextBlock(text="System time is verified [T1]. Everything normal.")],
        stop_reason="end_turn",
        usage=Usage(100, 20),
    )
    mock_p = MockProvider([mock_resp1, mock_resp2])
    monkeypatch.setattr("app.copilot.orchestrator.get_llm_provider", lambda: mock_p)

    # 1. Execute chat turn
    chat_payload = {
        "prompt": "Check SCADA clock synchronization",
        "plant_id": str(plant1.id),
    }
    chat_res = client.post("/copilot/chat", json=chat_payload, headers=headers)
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    conv_id = chat_data["conversation_id"]

    # 2. List conversations
    list_res = client.get(f"/copilot/conversations?plant_id={plant1.id}", headers=headers)
    assert list_res.status_code == 200
    conv_list = list_res.json()["conversations"]
    assert any(c["id"] == conv_id for c in conv_list)

    # 3. Retrieve conversation thread with 'Show working' tool trace
    detail_res = client.get(f"/copilot/conversations/{conv_id}", headers=headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == conv_id
    assert len(detail["messages"]) >= 2  # user and assistant

    assistant_turn = next(m for m in detail["messages"] if m["role"] == "assistant")
    assert len(assistant_turn["tool_calls"]) == 1
    assert assistant_turn["tool_calls"][0]["tool_name"] == "get_current_time"
    assert assistant_turn["tool_calls"][0]["status"] == "ok"


def test_copilot_chat_stream_api(client, orch_db, monkeypatch):
    """Test /copilot/chat/stream delivering SSE events (start, tool_start, tool_end, delta, done)."""
    user1 = orch_db["user1"]
    plant1 = orch_db["plant1"]

    token = create_access_token({"sub": str(user1.id), "org_id": str(user1.org_id), "role": user1.role})
    headers = {"Authorization": f"Bearer {token}"}

    mock_resp1 = ProviderResponse(
        tool_use_blocks=[ToolUseBlock(id="t_stream", name="get_current_time", arguments={})],
        stop_reason="tool_use",
        usage=Usage(50, 10),
    )
    mock_resp2 = ProviderResponse(
        text_blocks=[TextBlock(text="Clock sync OK [T1].")],
        stop_reason="end_turn",
        usage=Usage(100, 20),
    )
    mock_p = MockProvider([mock_resp1, mock_resp2])
    monkeypatch.setattr("app.copilot.orchestrator.get_llm_provider", lambda: mock_p)

    payload = {
        "prompt": "Stream clock check",
        "plant_id": str(plant1.id),
    }

    res = client.post("/copilot/chat/stream", json=payload, headers=headers)
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    content = res.text
    assert "event: start" in content
    assert "event: tool_start" in content
    assert "event: tool_end" in content
    assert "event: delta" in content
    assert "event: done" in content

