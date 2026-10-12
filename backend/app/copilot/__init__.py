"""Copilot Tool Layer, Agent Loop & Orchestration Engine (§10.2, §10.3, Tasks S5-AI-01 & S5-AI-02).

Provides:
- 12 SCADA operational backend tools
- Pydantic v2 schemas and validation
- Multi-tenant ToolSecurityContext enforcement
- ResultRefStore for large timeseries data ref caching
- ChartStore for interactive chart specifications
- CopilotToolRegistry and dispatcher
- CopilotOrchestrator multi-step reasoning agent loop
- Safety controls (15-call execution cap)
- Trace persistence and "Show working" audit models
- Citation markers ([T1], [T2], ...) extraction and validation
"""

from app.copilot.citation import (
    CitationMetadata,
    extract_citations,
    validate_citations,
)
from app.copilot.context import (
    SecurityScopeError,
    ToolSecurityContext,
)
from app.copilot.guardrails import (
    INJECTION_REJECTION_MESSAGE,
    OFF_TOPIC_REJECTION_MESSAGE,
    SYSTEM_LEAK_REDACTION_MESSAGE,
    InputGuardrailResult,
    OutputGuardrailResult,
    sanitize_scada_data,
    validate_input_prompt,
    validate_output_content,
)
from app.copilot.orchestrator import (
    CopilotExecutionResult,
    CopilotOrchestrator,
    MAX_TOOL_CALLS,
    ToolTraceStep,
)
from app.copilot.prompts import (
    BASE_COPILOT_SYSTEM_PROMPT,
    build_copilot_system_prompt,
)
from app.copilot.registry import (
    CopilotTool,
    CopilotToolRegistry,
    build_default_tool_registry,
    default_tool_registry,
)
from app.copilot.result_store import (
    ChartStore,
    ResultRefStore,
    default_chart_store,
    default_result_store,
    format_timeseries_result,
)
from app.copilot.schemas import (
    ChannelSelector,
    ChartSeriesSpec,
    ChartSpec,
    CompareAssetsInput,
    ComputeKPIInput,
    DetectOnDemandInput,
    GetDataCoverageInput,
    GetAnomalyInput,
    GetCurrentTimeInput,
    GetPlantSummaryInput,
    ListAnomaliesInput,
    ListAssetsInput,
    ListEventsInput,
    QueryTimeseriesInput,
    RenderChartInput,
)
from app.copilot.tools import (
    tool_compare_assets,
    tool_compute_kpi,
    tool_detect_on_demand,
    tool_get_anomaly,
    tool_get_current_time,
    tool_get_data_coverage,
    tool_get_plant_summary,
    tool_list_anomalies,
    tool_list_assets,
    tool_list_events,
    tool_query_timeseries,
    tool_render_chart,
)

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

__all__ = [
    # Security
    "ToolSecurityContext",
    "SecurityScopeError",
    # Result Caching
    "ResultRefStore",
    "ChartStore",
    "default_result_store",
    "default_chart_store",
    "format_timeseries_result",
    # Registry
    "CopilotTool",
    "CopilotToolRegistry",
    "build_default_tool_registry",
    "default_tool_registry",
    # Orchestrator & Execution
    "CopilotOrchestrator",
    "CopilotExecutionResult",
    "ToolTraceStep",
    "MAX_TOOL_CALLS",
    # Prompts, Citations & Guardrails
    "BASE_COPILOT_SYSTEM_PROMPT",
    "build_copilot_system_prompt",
    "CitationMetadata",
    "extract_citations",
    "validate_citations",
    "validate_input_prompt",
    "validate_output_content",
    "sanitize_scada_data",
    "InputGuardrailResult",
    "OutputGuardrailResult",
    "INJECTION_REJECTION_MESSAGE",
    "OFF_TOPIC_REJECTION_MESSAGE",
    "SYSTEM_LEAK_REDACTION_MESSAGE",
    # Schemas
    "ChannelSelector",
    "ChartSeriesSpec",
    "ChartSpec",
    "GetPlantSummaryInput",
    "ListAssetsInput",
    "QueryTimeseriesInput",
    "ComputeKPIInput",
    "CompareAssetsInput",
    "ListAnomaliesInput",
    "GetAnomalyInput",
    "ListEventsInput",
    "DetectOnDemandInput",
    "RenderChartInput",
    "GetDataCoverageInput",
    "GetCurrentTimeInput",
    # Tool Functions
    "tool_get_plant_summary",
    "tool_list_assets",
    "tool_query_timeseries",
    "tool_compute_kpi",
    "tool_compare_assets",
    "tool_list_anomalies",
    "tool_get_anomaly",
    "tool_list_events",
    "tool_detect_on_demand",
    "tool_render_chart",
    "tool_get_data_coverage",
    "tool_get_current_time",
    # Evaluation Harness & Golden Dataset (§10.5, Task S5-AI-04)
    "GoldenTestCase",
    "generate_golden_dataset",
    "save_golden_dataset_to_file",
    "load_golden_dataset_from_file",
    "NumericMatchResult",
    "EvaluationCaseResult",
    "EvaluationSummary",
    "CIEvaluationProvider",
    "CopilotEvaluator",
    "extract_numbers_from_text",
    "is_numeric_match",
]
