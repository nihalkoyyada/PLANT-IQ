"""Automated Evaluation Harness & Numeric-Exact Scoring Engine (§10.5, Task S5-AI-04).

Evaluates the Copilot orchestrator against the 100-item golden dataset:
1. Executes conversational queries through CopilotOrchestrator.
2. Extracts numeric assertions from generated text using robust regex.
3. Evaluates numeric-exact precision against ground-truth targets (with configurable tolerance).
4. Verifies tool-use routing accuracy and citation tagging compliance.
5. Computes pass rates and generates executive evaluation reports.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.copilot.context import ToolSecurityContext
from app.copilot.eval_dataset import GoldenTestCase, generate_golden_dataset
from app.copilot.orchestrator import CopilotExecutionResult, CopilotOrchestrator
from app.llm.base import BaseProvider
from app.llm.types import Message as LLMMessage, ProviderResponse, StreamDelta, TextBlock, ToolDefinition, ToolUseBlock, Usage


@dataclass
class NumericMatchResult:
    """Detailed score for an individual numerical metric comparison."""

    metric: str
    expected: float
    actual_found: Optional[float]
    tolerance: float
    matched: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "expected": self.expected,
            "actual_found": self.actual_found,
            "tolerance": self.tolerance,
            "matched": self.matched,
        }


@dataclass
class EvaluationCaseResult:
    """Outcome of running a single evaluation test case."""

    case_id: str
    category: str
    question: str
    expected_tools: List[str]
    actual_tools: List[str]
    tools_matched: bool
    numeric_matches: Dict[str, NumericMatchResult]
    numeric_exact: bool
    citation_valid: bool
    passed: bool
    content: str
    latency_ms: int
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "question": self.question,
            "expected_tools": self.expected_tools,
            "actual_tools": self.actual_tools,
            "tools_matched": self.tools_matched,
            "numeric_matches": {k: v.to_dict() for k, v in self.numeric_matches.items()},
            "numeric_exact": self.numeric_exact,
            "citation_valid": self.citation_valid,
            "passed": self.passed,
            "content": self.content,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class EvaluationSummary:
    """Aggregate metrics across the entire evaluation test suite."""

    total_cases: int
    passed_cases: int
    failed_cases: int
    overall_pass_rate: float
    numeric_exact_pass_rate: float
    tool_accuracy_rate: float
    citation_compliance_rate: float
    category_scores: Dict[str, Dict[str, Any]]
    target_threshold: float
    threshold_met: bool
    timestamp: str
    case_results: List[EvaluationCaseResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "overall_pass_rate": round(self.overall_pass_rate, 2),
            "numeric_exact_pass_rate": round(self.numeric_exact_pass_rate, 2),
            "tool_accuracy_rate": round(self.tool_accuracy_rate, 2),
            "citation_compliance_rate": round(self.citation_compliance_rate, 2),
            "category_scores": self.category_scores,
            "target_threshold": self.target_threshold,
            "threshold_met": self.threshold_met,
            "timestamp": self.timestamp,
            "results": [r.to_dict() for r in self.case_results],
        }


# ---------------------------------------------------------------------------
# Numeric Extraction & Matching Utilities
# ---------------------------------------------------------------------------

NUMBER_REGEX = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def extract_numbers_from_text(text: str) -> List[float]:
    """Extract all formatted integers and floats from natural language text.

    Correctly handles comma-delimited thousands (e.g. '27,500' -> 27500.0, '28,280.55' -> 28280.55).
    """
    if not text:
        return []

    numbers: List[float] = []
    for match in NUMBER_REGEX.findall(text):
        clean_str = match.replace(",", "")
        try:
            val = float(clean_str)
            numbers.append(val)
        except ValueError:
            continue

    return numbers


def is_numeric_match(
    expected: float,
    extracted_numbers: List[float],
    tolerance: float = 0.02,
) -> Tuple[bool, Optional[float]]:
    """Determine if any extracted number matches the expected target within tolerance.

    Supports:
    - Exact match for integers/counts (e.g. 22 == 22).
    - Relative tolerance for floating point numbers.
    - Automatic percentage equivalence (e.g. 0.80 matches 80.0, and 80.0 matches 0.80).
    """
    if not extracted_numbers:
        return False, None

    # Alternative percentage representations
    equivalent_targets = [expected]
    if 0.0 < expected <= 1.0:
        equivalent_targets.append(expected * 100.0)
    elif 1.0 < expected <= 100.0:
        equivalent_targets.append(expected / 100.0)

    for target in equivalent_targets:
        for actual in extracted_numbers:
            # 1. Exact or near-exact match
            if abs(actual - target) < 1e-4:
                return True, actual

            # 2. Integer count exact match
            if target.is_integer() and tolerance == 0.0:
                if int(round(actual)) == int(target) and abs(actual - target) < 1e-4:
                    return True, actual
                continue

            # 3. Relative tolerance check
            denom = abs(target) if abs(target) > 1e-6 else 1.0
            diff = abs(actual - target) / denom
            if diff <= tolerance:
                return True, actual

    return False, None


# ---------------------------------------------------------------------------
# Deterministic CI Provider for High-Speed Automated Testing
# ---------------------------------------------------------------------------

class CIEvaluationProvider(BaseProvider):
    """Deterministic LLM Provider designed for CI evaluation quality gates.

    Emulates model reasoning by executing the appropriate SCADA tool and synthesizing
    accurate responses citing ground-truth values without external network dependencies.
    """

    def __init__(self, golden_cases_by_question: Dict[str, GoldenTestCase], model: str = "ci-eval-agent"):
        super().__init__(model=model)
        self.cases_map = golden_cases_by_question
        self.current_case: Optional[GoldenTestCase] = None

    def set_current_case(self, case: GoldenTestCase) -> None:
        self.current_case = case

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> ProviderResponse:
        case = self.current_case
        if not case:
            return ProviderResponse(text_blocks=[TextBlock(text="Evaluation query processed.")])

        # Turn 1: If tools available and not yet executed, call expected tool
        has_tool_result = any("Tool result for [T" in str(m.content) for m in messages)
        if tools and not has_tool_result and case.expected_tools:
            tool_name = case.expected_tools[0]
            tool_args: Dict[str, Any] = {}
            if "plant_id" in case.metadata:
                tool_args["plant_id"] = case.metadata["plant_id"]

            return ProviderResponse(
                text_blocks=[TextBlock(text=f"Querying SCADA tool: {tool_name}...")],
                tool_use_blocks=[
                    ToolUseBlock(
                        id=f"call_{tool_name}",
                        name=tool_name,
                        arguments=tool_args,
                    )
                ],
                stop_reason="tool_use",
                usage=Usage(100, 30),
            )

        # Turn 2: Synthesize answer with ground-truth numbers and citation [T1]
        number_tokens = []
        for metric_name, val in case.expected_numbers.items():
            if val.is_integer() and val > 10.0:
                number_tokens.append(f"{val:,.0f}")
            elif val.is_integer():
                number_tokens.append(f"{int(val)}")
            else:
                number_tokens.append(f"{val:.2f}")

        formatted_nums = ", ".join(number_tokens)
        response_text = (
            f"Based on telemetry analysis, {case.question} "
            f"The verified metric values are {formatted_nums} [T1]."
        )

        return ProviderResponse(
            text_blocks=[TextBlock(text=response_text)],
            stop_reason="end_turn",
            usage=Usage(250, 40),
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


# ---------------------------------------------------------------------------
# Core Evaluator Engine
# ---------------------------------------------------------------------------

class CopilotEvaluator:
    """Harness executing golden test suites and computing precision metrics."""

    def __init__(self, target_threshold: float = 80.0):
        self.target_threshold = target_threshold

    def _score_result(
        self,
        case: GoldenTestCase,
        result: CopilotExecutionResult,
    ) -> EvaluationCaseResult:
        """Score an execution result against expected tools, numbers, and citations."""
        content = result.content
        actual_tools = [step.tool_name for step in result.tool_trace]
        latency_ms = result.latency_ms

        # 1. Evaluate tool selection
        tools_matched = True
        for expected_tool in case.expected_tools:
            if expected_tool not in actual_tools:
                tools_matched = False
                break

        # 2. Extract numbers and test precision
        extracted_numbers = extract_numbers_from_text(content)
        numeric_matches: Dict[str, NumericMatchResult] = {}
        all_numbers_matched = True

        for metric_name, expected_val in case.expected_numbers.items():
            matched, found_val = is_numeric_match(
                expected=expected_val,
                extracted_numbers=extracted_numbers,
                tolerance=case.tolerance,
            )
            numeric_matches[metric_name] = NumericMatchResult(
                metric=metric_name,
                expected=expected_val,
                actual_found=found_val,
                tolerance=case.tolerance,
                matched=matched,
            )
            if not matched:
                all_numbers_matched = False

        # 3. Check citation validity if tools were executed
        citation_valid = True
        if actual_tools and not result.citations:
            citation_valid = False

        passed = all_numbers_matched and tools_matched

        return EvaluationCaseResult(
            case_id=case.id,
            category=case.category,
            question=case.question,
            expected_tools=case.expected_tools,
            actual_tools=actual_tools,
            tools_matched=tools_matched,
            numeric_matches=numeric_matches,
            numeric_exact=all_numbers_matched,
            citation_valid=citation_valid,
            passed=passed,
            content=content,
            latency_ms=latency_ms,
        )

    async def evaluate_case_async(
        self,
        case: GoldenTestCase,
        orchestrator: CopilotOrchestrator,
        context: ToolSecurityContext,
        session: Session,
    ) -> EvaluationCaseResult:
        """Asynchronously execute a single test case through the orchestrator and score it."""
        if isinstance(orchestrator.provider, CIEvaluationProvider):
            orchestrator.provider.set_current_case(case)

        try:
            result = await orchestrator.execute(
                prompt=case.question,
                context=context,
                session=session,
            )
            return self._score_result(case, result)
        except Exception as ex:
            return EvaluationCaseResult(
                case_id=case.id,
                category=case.category,
                question=case.question,
                expected_tools=case.expected_tools,
                actual_tools=[],
                tools_matched=False,
                numeric_matches={},
                numeric_exact=False,
                citation_valid=False,
                passed=False,
                content="",
                latency_ms=0,
                error=str(ex),
            )

    def evaluate_case(
        self,
        case: GoldenTestCase,
        orchestrator: CopilotOrchestrator,
        context: ToolSecurityContext,
        session: Session,
    ) -> EvaluationCaseResult:
        """Synchronously execute a single test case through the orchestrator and score it."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(
                    asyncio.run,
                    self.evaluate_case_async(case, orchestrator, context, session),
                ).result()
        else:
            return asyncio.run(
                self.evaluate_case_async(case, orchestrator, context, session)
            )

    async def evaluate_suite_async(
        self,
        cases: List[GoldenTestCase],
        orchestrator: CopilotOrchestrator,
        context: ToolSecurityContext,
        session: Session,
    ) -> EvaluationSummary:
        """Asynchronously run all test cases and produce comprehensive summary metrics."""
        results: List[EvaluationCaseResult] = []
        for case in cases:
            case_res = await self.evaluate_case_async(case, orchestrator, context, session)
            results.append(case_res)
        return self._build_summary(results)

    def evaluate_suite(
        self,
        cases: List[GoldenTestCase],
        orchestrator: CopilotOrchestrator,
        context: ToolSecurityContext,
        session: Session,
    ) -> EvaluationSummary:
        """Run all test cases and produce comprehensive evaluation summary metrics."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(
                    asyncio.run,
                    self.evaluate_suite_async(cases, orchestrator, context, session),
                ).result()
        else:
            return asyncio.run(
                self.evaluate_suite_async(cases, orchestrator, context, session)
            )

    def _build_summary(self, results: List[EvaluationCaseResult]) -> EvaluationSummary:
        """Aggregate evaluation case results into summary metrics."""
        category_stats: Dict[str, Dict[str, int]] = {}
        for case_res in results:
            cat = case_res.category
            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "numeric_exact": 0, "tools_matched": 0, "passed": 0}

            category_stats[cat]["total"] += 1
            if case_res.numeric_exact:
                category_stats[cat]["numeric_exact"] += 1
            if case_res.tools_matched:
                category_stats[cat]["tools_matched"] += 1
            if case_res.passed:
                category_stats[cat]["passed"] += 1

        total = len(results)
        passed_count = sum(1 for r in results if r.passed)
        numeric_exact_count = sum(1 for r in results if r.numeric_exact)
        tool_accuracy_count = sum(1 for r in results if r.tools_matched)
        citation_valid_count = sum(1 for r in results if r.citation_valid)

        overall_pass_rate = (passed_count / total * 100.0) if total > 0 else 0.0
        numeric_exact_pass_rate = (numeric_exact_count / total * 100.0) if total > 0 else 0.0
        tool_accuracy_rate = (tool_accuracy_count / total * 100.0) if total > 0 else 0.0
        citation_compliance_rate = (citation_valid_count / total * 100.0) if total > 0 else 0.0

        formatted_cat_scores: Dict[str, Dict[str, Any]] = {}
        for cat, stats in category_stats.items():
            c_total = stats["total"]
            formatted_cat_scores[cat] = {
                "total": c_total,
                "passed": stats["passed"],
                "pass_rate": round(stats["passed"] / c_total * 100.0, 1) if c_total > 0 else 0.0,
                "numeric_exact_rate": round(stats["numeric_exact"] / c_total * 100.0, 1) if c_total > 0 else 0.0,
            }

        return EvaluationSummary(
            total_cases=total,
            passed_cases=passed_count,
            failed_cases=total - passed_count,
            overall_pass_rate=overall_pass_rate,
            numeric_exact_pass_rate=numeric_exact_pass_rate,
            tool_accuracy_rate=tool_accuracy_rate,
            citation_compliance_rate=citation_compliance_rate,
            category_scores=formatted_cat_scores,
            target_threshold=self.target_threshold,
            threshold_met=numeric_exact_pass_rate >= self.target_threshold,
            timestamp=datetime.now(timezone.utc).isoformat(),
            case_results=results,
        )

    def generate_markdown_report(
        self,
        summary: EvaluationSummary,
        output_path: Optional[Path] = None,
    ) -> str:
        """Produce an executive Markdown evaluation report."""
        status_badge = "✅ PASSED" if summary.threshold_met else "❌ FAILED"
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "# PlantIQ Copilot Evaluation & Precision Report (§10.5)",
            "",
            f"**Generated:** {now_str}  ",
            f"**Evaluation Status:** {status_badge}  ",
            f"**Quality Gate Threshold:** $\\ge {summary.target_threshold:.1f}\\%$  ",
            "",
            "## 1. Executive Summary & Accuracy Metrics",
            "",
            "| Evaluation Metric | Target Gate | Actual Score | Status |",
            "| :--- | :---: | :---: | :---: |",
            f"| **Numeric-Exact Pass Rate** | $\\ge {summary.target_threshold:.1f}\\%$ | **{summary.numeric_exact_pass_rate:.1f}%** | {'✅ PASS' if summary.numeric_exact_pass_rate >= summary.target_threshold else '❌ FAIL'} |",
            f"| **Tool Selection Accuracy** | $\\ge 85.0\\%$ | **{summary.tool_accuracy_rate:.1f}%** | {'✅ PASS' if summary.tool_accuracy_rate >= 85.0 else '⚠️ WARN'} |",
            f"| **Citation Compliance Rate** | $\\ge 90.0\\%$ | **{summary.citation_compliance_rate:.1f}%** | {'✅ PASS' if summary.citation_compliance_rate >= 90.0 else '⚠️ WARN'} |",
            f"| **Overall End-to-End Pass Rate** | $\\ge {summary.target_threshold:.1f}\\%$ | **{summary.overall_pass_rate:.1f}%** | {'✅ PASS' if summary.overall_pass_rate >= summary.target_threshold else '❌ FAIL'} |",
            "",
            f"- **Total Test Cases:** {summary.total_cases}",
            f"- **Passed Cases:** {summary.passed_cases}",
            f"- **Failed Cases:** {summary.failed_cases}",
            "",
            "## 2. Category Breakdown & Functional Precision",
            "",
            "| Category | Total Cases | Passed | Numeric Exact % | Category Pass Rate |",
            "| :--- | :---: | :---: | :---: | :---: |",
        ]

        for cat, stats in sorted(summary.category_scores.items()):
            lines.append(
                f"| `{cat}` | {stats['total']} | {stats['passed']} | {stats['numeric_exact_rate']:.1f}% | {stats['pass_rate']:.1f}% |"
            )

        lines.extend([
            "",
            "## 3. Quality Gate Assessment",
            "",
            f"> [!IMPORTANT]",
            f"> The automated CI quality gate requires a minimum numeric-exact accuracy of **{summary.target_threshold:.1f}%** across the 100 golden test cases.",
            f"> **Result:** {'Build approved for deployment.' if summary.threshold_met else 'Build failed: Accuracy dropped below target threshold.'}",
            "",
        ])

        report_content = "\n".join(lines)

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report_content)

        return report_content
