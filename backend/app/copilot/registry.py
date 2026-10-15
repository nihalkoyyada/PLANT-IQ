"""Tool Registry and Execution Dispatcher for Copilot 12-Tool Suite (§10.3, Task S5-AI-01).

Manages registration, Pydantic validation, schema generation (ToolDefinition for LLM),
and authorized execution scoping for all Copilot SCADA operational tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.copilot.context import SecurityScopeError, ToolSecurityContext
from app.copilot.schemas import (
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
from app.llm.types import ToolDefinition


@dataclass(frozen=True)
class CopilotTool:
    """Registered Copilot operational tool metadata and handler."""

    name: str
    description: str
    schema: Type[BaseModel]
    handler: Callable[[Any, ToolSecurityContext, Session], Dict[str, Any]]

    def get_tool_definition(self) -> ToolDefinition:
        """Produce standard ToolDefinition with JSON schema for LLM function calling."""
        schema_dict = self.schema.model_json_schema()
        # Clean title from schema root if present for cleaner LLM prompting
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=schema_dict,
        )


class CopilotToolRegistry:
    """Registry coordinating Copilot tools, validation, and execution."""

    def __init__(self) -> None:
        self._tools: Dict[str, CopilotTool] = {}

    def register(
        self,
        name: str,
        description: str,
        schema: Type[BaseModel],
        handler: Callable[[Any, ToolSecurityContext, Session], Dict[str, Any]],
    ) -> None:
        """Register a new tool."""
        self._tools[name] = CopilotTool(
            name=name,
            description=description.strip(),
            schema=schema,
            handler=handler,
        )

    def get_tool(self, name: str) -> Optional[CopilotTool]:
        """Look up tool by name."""
        return self._tools.get(name)

    def list_tool_names(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def list_tools(self) -> List[CopilotTool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Generate ToolDefinition specifications for all registered tools."""
        return [tool.get_tool_definition() for tool in self._tools.values()]

    def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        context: ToolSecurityContext,
        session: Session,
    ) -> Dict[str, Any]:
        """Validate parameters against Pydantic schema and execute operational handler.

        Enforces multi-tenant organizational scoping and catches validation errors.
        """
        tool = self.get_tool(name)
        if not tool:
            return {
                "success": False,
                "error": "unknown_tool",
                "message": f"Tool '{name}' is not recognized. Available tools: {', '.join(self.list_tool_names())}",
            }

        # 1. Pydantic validation
        try:
            validated_params = tool.schema.model_validate(arguments or {})
        except ValidationError as val_err:
            return {
                "success": False,
                "error": "validation_error",
                "message": f"Parameter validation failed for tool '{name}'.",
                "details": [
                    {
                        "loc": [str(loc_item) for loc_item in err["loc"]],
                        "msg": err["msg"],
                        "type": err["type"],
                    }
                    for err in val_err.errors()
                ],
            }
        except Exception as ex:
            return {
                "success": False,
                "error": "validation_error",
                "message": f"Invalid arguments for tool '{name}': {str(ex)}",
            }

        # 2. Execution under security context
        try:
            result = tool.handler(validated_params, context, session)
            return {
                "success": True,
                "tool": name,
                "data": result,
            }
        except SecurityScopeError as sec_err:
            return {
                "success": False,
                "error": "security_scope_error",
                "message": str(sec_err),
            }
        except Exception as exec_err:
            return {
                "success": False,
                "error": "execution_error",
                "message": f"Error executing tool '{name}': {str(exec_err)}",
            }


def build_default_tool_registry() -> CopilotToolRegistry:
    """Instantiate and populate the standard registry with all 12 operational tools (§10.3)."""
    registry = CopilotToolRegistry()

    # 1. get_plant_summary
    registry.register(
        name="get_plant_summary",
        description=(
            "Retrieve high-level plant overview including name, capacity, status, asset rollups, "
            "aggregated power generation, current PR & CUF, and active anomaly counts for a specified time window."
        ),
        schema=GetPlantSummaryInput,
        handler=tool_get_plant_summary,
    )

    # 2. list_assets
    registry.register(
        name="list_assets",
        description=(
            "List assets in the plant hierarchy with optional filtering by asset type (e.g. inverter, "
            "weather_station) or parent asset. Returns capacity, model, and available canonical signal keys."
        ),
        schema=ListAssetsInput,
        handler=tool_list_assets,
    )

    # 3. query_timeseries
    registry.register(
        name="query_timeseries",
        description=(
            "Query SCADA timeseries telemetry for specified assets and canonical signals. Supports "
            "temporal downsampling (raw, 15m, 1h, 1d) and aggregations (avg, min, max, sum). Automatically caches "
            "large arrays (>50 points) into ResultRefStore and returns compact reference IDs with summary statistics."
        ),
        schema=QueryTimeseriesInput,
        handler=tool_query_timeseries,
    )

    # 4. compute_kpi
    registry.register(
        name="compute_kpi",
        description=(
            "Compute solar PV performance KPIs (performance_ratio, cuf, specific_yield, availability, "
            "inverter_efficiency, energy_loss) adhering to IEC 61724-1 standards across plant or asset scope."
        ),
        schema=ComputeKPIInput,
        handler=tool_compute_kpi,
    )

    # 5. compare_assets
    registry.register(
        name="compare_assets",
        description=(
            "Compare and rank multiple assets (e.g. inverters) against a metric (active_power, daily_yield, "
            "performance_ratio) over a specified time window with statistical aggregation (avg, sum, p95)."
        ),
        schema=CompareAssetsInput,
        handler=tool_compare_assets,
    )

    # 6. list_anomalies
    registry.register(
        name="list_anomalies",
        description=(
            "Query detected anomalies for a plant with optional filtering by status (open, acknowledged, "
            "resolved), severity (low, medium, high, critical), asset ID, and time window. Includes financial loss estimates."
        ),
        schema=ListAnomaliesInput,
        handler=tool_list_anomalies,
    )

    # 7. get_anomaly
    registry.register(
        name="get_anomaly",
        description=(
            "Retrieve comprehensive details for a specific anomaly including detector method, root cause analysis, "
            "affected asset, peer inverter context, SCADA readings, and weather condition pointers."
        ),
        schema=GetAnomalyInput,
        handler=tool_get_anomaly,
    )

    # 8. list_events
    registry.register(
        name="list_events",
        description=(
            "Query plant operational events, grid trips, inverter faults, SCADA warnings, and maintenance logs "
            "over a designated time period."
        ),
        schema=ListEventsInput,
        handler=tool_list_events,
    )

    # 9. detect_on_demand
    registry.register(
        name="detect_on_demand",
        description=(
            "Execute an ad-hoc anomaly detection scan over a specified signal and time window using detection "
            "algorithms (zscore, residual, d1_statistical, d2_pr_deviation, d3_irradiance_residual, d4_isolation_forest) without persisting to DB."
        ),
        schema=DetectOnDemandInput,
        handler=tool_detect_on_demand,
    )

    # 10. render_chart
    registry.register(
        name="render_chart",
        description=(
            "Validate and prepare an ECharts specification for interactive visual rendering. Resolves series data "
            "from cached timeseries result references (data_ref) into fully populated chart objects stored in ChartStore."
        ),
        schema=RenderChartInput,
        handler=tool_render_chart,
    )

    # 11. get_data_coverage
    registry.register(
        name="get_data_coverage",
        description=(
            "Analyze telemetry completeness and data quality across canonical signals for a plant over a time "
            "window. Identifies communication dropouts, missing intervals, and sensor health."
        ),
        schema=GetDataCoverageInput,
        handler=tool_get_data_coverage,
    )

    # 12. get_current_time
    registry.register(
        name="get_current_time",
        description=(
            "Retrieve current server UTC time and plant-specific local time, timezone, and solar daylight status. "
            "Prevents LLM temporal hallucination and grounds SCADA queries in current date."
        ),
        schema=GetCurrentTimeInput,
        handler=tool_get_current_time,
    )

    return registry


# Singleton registry instance
default_tool_registry = build_default_tool_registry()
