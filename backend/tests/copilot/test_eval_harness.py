"""Test Suite for Copilot Evaluation Harness & Numeric-Exact CI Quality Gate (§10.5, Task S5-AI-04).

Tests:
1. Golden dataset generation and schema integrity (100 synthetic Q&A test cases).
2. Numeric extraction regex with commas, negative values, and decimals.
3. Precision matching logic with relative tolerance and percentage equivalence.
4. Deterministic CIEvaluationProvider reasoning and tool execution loop.
5. CopilotEvaluator failure detection on inaccurate agent outputs.
6. End-to-end evaluation suite execution and >= 80% CI quality gate enforcement.
7. Markdown and JSON evaluation reporting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List
from uuid import UUID, uuid4
import pytest

from app.copilot.context import ToolSecurityContext
from app.copilot.eval_dataset import (
    GoldenTestCase,
    generate_golden_dataset,
    load_golden_dataset_from_file,
    save_golden_dataset_to_file,
)
from app.copilot.eval_harness import (
    CIEvaluationProvider,
    CopilotEvaluator,
    EvaluationCaseResult,
    EvaluationSummary,
    NumericMatchResult,
    extract_numbers_from_text,
    is_numeric_match,
)
from app.copilot.orchestrator import (
    CopilotExecutionResult,
    CopilotOrchestrator,
    ToolTraceStep,
)
from app.db.database import SessionLocal
from app.llm.base import BaseProvider
from app.llm.types import Message as LLMMessage, ProviderResponse, TextBlock, Usage
from app.models.entities import Organization, Plant, User


@pytest.fixture(scope="module")
def eval_db():
    """Setup database session and test organization/plant context."""
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.name == "Eval Harness Org").first()
        if not org:
            org = Organization(name="Eval Harness Org")
            db.add(org)
            db.commit()
            db.refresh(org)

        plant = db.query(Plant).filter(Plant.name == "Eval Harness Plant").first()
        if not plant:
            plant = Plant(
                org_id=org.id,
                name="Eval Harness Plant",
                plant_type="solar",
                capacity_ac_kw=27500.0,
                capacity_dc_kwp=28280.55,
                latitude=24.5854,
                longitude=73.7125,
            )
            db.add(plant)
            db.commit()
            db.refresh(plant)

        user = db.query(User).filter(User.email == "eval_user@test.com").first()
        if not user:
            user = User(
                org_id=org.id,
                email="eval_user@test.com",
                password_hash="hash",
                full_name="Eval User",
                role="engineer",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        yield {"db": db, "org": org, "plant": plant, "user": user}
    finally:
        db.close()


@pytest.fixture
def eval_context(eval_db):
    return ToolSecurityContext(
        org_id=eval_db["org"].id,
        user_id=eval_db["user"].id,
        plant_id=eval_db["plant"].id,
        user_role="engineer",
    )


# ---------------------------------------------------------------------------
# 1. Golden Dataset Generation Tests
# ---------------------------------------------------------------------------

def test_golden_dataset_generation_count():
    """Verify golden dataset contains exactly 100 structured test cases."""
    cases = generate_golden_dataset()
    assert len(cases) == 100, f"Expected 100 test cases, found {len(cases)}"


def test_golden_dataset_category_distribution():
    """Verify all 8 operational categories are represented in the golden suite."""
    cases = generate_golden_dataset()
    categories = {c.category for c in cases}
    expected_categories = {
        "plant_summary",
        "asset_hierarchy",
        "kpi_computation",
        "timeseries_query",
        "compare_assets",
        "anomaly_analysis",
        "event_listing",
        "data_coverage",
    }
    assert expected_categories.issubset(categories)

    # Check ID uniqueness
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "Case IDs must be strictly unique"


def test_golden_dataset_serialization(tmp_path: Path):
    """Verify golden dataset serializes and deserializes to/from JSON cleanly."""
    cases = generate_golden_dataset()
    json_path = tmp_path / "test_golden.json"

    save_golden_dataset_to_file(json_path, cases)
    assert json_path.exists()

    loaded_cases = load_golden_dataset_from_file(json_path)
    assert len(loaded_cases) == 100
    assert loaded_cases[0].id == cases[0].id
    assert loaded_cases[0].expected_numbers == cases[0].expected_numbers


# ---------------------------------------------------------------------------
# 2. Numeric Extraction & Precision Matching Tests
# ---------------------------------------------------------------------------

def test_extract_numbers_from_text():
    """Verify robust regex extraction of integers, decimals, and comma-separated numbers."""
    text = "Plant AC rating is 27,500 kW while DC is 28,280.55 kWp with PR 80% and temp -4.5 C."
    nums = extract_numbers_from_text(text)
    assert 27500.0 in nums
    assert 28280.55 in nums
    assert 80.0 in nums
    assert -4.5 in nums


def test_numeric_match_exact_integers():
    """Verify exact count matching (tol=0.0)."""
    # Exact match
    matched, found = is_numeric_match(expected=22.0, extracted_numbers=[10.0, 22.0, 50.0], tolerance=0.0)
    assert matched is True
    assert found == 22.0

    # Non-match when outside exact value
    matched, _ = is_numeric_match(expected=22.0, extracted_numbers=[21.0, 23.0], tolerance=0.0)
    assert matched is False


def test_numeric_match_floating_tolerance():
    """Verify relative tolerance matching for metrics."""
    # Within 2% tolerance (1250 * 0.02 = 25 -> range 1225..1275)
    matched, found = is_numeric_match(expected=1250.0, extracted_numbers=[1260.0], tolerance=0.02)
    assert matched is True
    assert found == 1260.0

    # Outside tolerance
    matched, _ = is_numeric_match(expected=1250.0, extracted_numbers=[1300.0], tolerance=0.02)
    assert matched is False


def test_numeric_match_percentage_equivalence():
    """Verify automatic equivalence between ratio (0.80) and percentage (80.0%)."""
    # Expected 0.80, text has 80.0
    matched, found = is_numeric_match(expected=0.80, extracted_numbers=[80.0])
    assert matched is True
    assert found == 80.0

    # Expected 80.0, text has 0.80
    matched, found = is_numeric_match(expected=80.0, extracted_numbers=[0.80])
    assert matched is True
    assert found == 0.80


# ---------------------------------------------------------------------------
# 3. Harness Execution & Quality Gate Enforcement Tests
# ---------------------------------------------------------------------------

def test_evaluator_single_case_success(eval_db, eval_context):
    """Verify single case evaluation with CIEvaluationProvider passes with exact numbers."""
    case = GoldenTestCase(
        id="TEST-001",
        category="plant_summary",
        question="What is the total AC capacity of Surya-A in kW?",
        expected_tools=["get_plant_summary"],
        expected_numbers={"ac_capacity": 27500.0},
        tolerance=0.01,
        description="Verify AC capacity extraction.",
    )

    provider = CIEvaluationProvider(golden_cases_by_question={case.question: case})
    orchestrator = CopilotOrchestrator(provider=provider)
    evaluator = CopilotEvaluator(target_threshold=80.0)

    result: EvaluationCaseResult = evaluator.evaluate_case(
        case=case,
        orchestrator=orchestrator,
        context=eval_context,
        session=eval_db["db"],
    )

    assert result.passed is True
    assert result.numeric_exact is True
    assert result.tools_matched is True
    assert result.citation_valid is True
    assert result.numeric_matches["ac_capacity"].matched is True


def test_evaluator_detects_inaccurate_agent(eval_db, eval_context):
    """Verify evaluator accurately fails when agent generates hallucinated/inaccurate numbers."""
    class InaccurateProvider(BaseProvider):
        def __init__(self):
            super().__init__(model="inaccurate-model")

        async def chat(self, messages, tools=None, system=None, max_tokens=4096, temperature=0.0, timeout=None):
            return ProviderResponse(
                text_blocks=[TextBlock(text="The plant capacity is 99,999 kW [T1].")]
            )

        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=0.0, timeout=None):
            resp = await self.chat(messages)
            yield resp

    case = GoldenTestCase(
        id="TEST-002",
        category="plant_summary",
        question="What is the total AC capacity of Surya-A in kW?",
        expected_tools=["get_plant_summary"],
        expected_numbers={"ac_capacity": 27500.0},
        tolerance=0.01,
        description="Verify rejection of hallucinated output.",
    )

    orchestrator = CopilotOrchestrator(provider=InaccurateProvider())
    evaluator = CopilotEvaluator(target_threshold=80.0)

    result = evaluator.evaluate_case(
        case=case,
        orchestrator=orchestrator,
        context=eval_context,
        session=eval_db["db"],
    )

    assert result.passed is False
    assert result.numeric_exact is False
    assert result.numeric_matches["ac_capacity"].matched is False


def test_quality_gate_threshold_logic():
    """Verify threshold_met flag strictly adheres to configured target threshold."""
    evaluator_80 = CopilotEvaluator(target_threshold=80.0)
    evaluator_99 = CopilotEvaluator(target_threshold=99.0)

    # 10 cases: 9 pass (90%), 1 fails
    results = [
        EvaluationCaseResult(
            case_id=f"C-{i}",
            category="test",
            question="Q?",
            expected_tools=[],
            actual_tools=[],
            tools_matched=True,
            numeric_matches={},
            numeric_exact=(i < 9),
            citation_valid=True,
            passed=(i < 9),
            content="Answer",
            latency_ms=10,
        )
        for i in range(10)
    ]

    summary_80 = evaluator_80._build_summary(results)
    assert summary_80.numeric_exact_pass_rate == 90.0
    assert summary_80.threshold_met is True

    summary_99 = evaluator_99._build_summary(results)
    assert summary_99.numeric_exact_pass_rate == 90.0
    assert summary_99.threshold_met is False


def test_eval_suite_end_to_end_ci_quality_gate(eval_db, eval_context, tmp_path: Path):
    """End-to-end evaluation suite execution enforcing >= 80% CI pass rate quality gate."""
    cases = generate_golden_dataset()
    cases_map = {c.question: c for c in cases}

    provider = CIEvaluationProvider(golden_cases_by_question=cases_map)
    orchestrator = CopilotOrchestrator(provider=provider)
    evaluator = CopilotEvaluator(target_threshold=80.0)

    summary = evaluator.evaluate_suite(
        cases=cases,
        orchestrator=orchestrator,
        context=eval_context,
        session=eval_db["db"],
    )

    assert summary.total_cases == 100
    assert summary.numeric_exact_pass_rate >= 80.0
    assert summary.threshold_met is True
    assert summary.overall_pass_rate >= 80.0

    # Verify Markdown Report Generation
    report_file = tmp_path / "test_report.md"
    report_text = evaluator.generate_markdown_report(summary, output_path=report_file)
    assert report_file.exists()
    assert "PlantIQ Copilot Evaluation & Precision Report" in report_text
    assert "✅ PASSED" in report_text
    assert "Numeric-Exact Pass Rate" in report_text
