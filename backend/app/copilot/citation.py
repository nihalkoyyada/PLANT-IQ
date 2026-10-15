"""Citation tagging and extraction mechanics for Copilot responses (§10.3, Task S5-AI-02).

Enforces citation markers ([T1], [T2], ...) mapping generated text directly back
to the exact tool execution trace, parameters, and outputs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


CITATION_REGEX = re.compile(r"\[T(\d+)\]")


class CitationMetadata(BaseModel):
    """Metadata representing a verified or detected citation marker in an assistant response."""

    tag: str = Field(..., description="Citation marker text as it appears in content, e.g. '[T1]'.")
    index: int = Field(..., description="1-based tool execution sequence index.")
    tool_name: str = Field(..., description="Name of the invoked tool.")
    tool_call_id: Optional[UUID] = Field(None, description="UUID of the persisted ToolCallRecord.")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Input parameters passed to the tool.")
    status: str = Field("ok", description="Execution status ('ok', 'error', 'rejected', 'invalid').")
    output_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Condensed summary of tool execution output for UI popovers.",
    )
    valid: bool = Field(True, description="True if the citation points to an executed tool within bounds.")


def _summarize_tool_output(output: Optional[Dict[str, Any]], max_items: int = 5) -> Dict[str, Any]:
    """Generate a clean, compact summary of tool output suitable for citation popovers."""
    if not output:
        return {}

    if not isinstance(output, dict):
        return {"raw": str(output)[:300]}

    # Check for success/data wrapper
    data = output.get("data", output)
    if not isinstance(data, dict):
        return {"data": str(data)[:300]}

    summary: Dict[str, Any] = {}
    for key, val in data.items():
        if isinstance(val, list):
            summary[key] = f"List of {len(val)} items"
            if val and len(val) <= max_items:
                summary[f"{key}_sample"] = val[:max_items]
        elif isinstance(val, dict):
            summary[key] = {k: v for k, v in list(val.items())[:max_items]}
        elif isinstance(val, (str, int, float, bool)) or val is None:
            summary[key] = val
        else:
            summary[key] = str(val)[:200]

    return summary


def extract_citations(text: str, tool_trace: List[Any]) -> List[CitationMetadata]:
    """Parse citation markers like '[T1]' from text and map to executed tool steps.

    Args:
        text: The generated assistant response text.
        tool_trace: Chronological list of ToolTraceStep objects executed in this turn.

    Returns:
        Ordered list of unique CitationMetadata corresponding to markers in the text.
    """
    if not text:
        return []

    matches = CITATION_REGEX.findall(text)
    if not matches:
        return []

    citations: List[CitationMetadata] = []
    seen_indices = set()

    for match in matches:
        try:
            idx = int(match)
        except ValueError:
            continue

        if idx in seen_indices:
            continue
        seen_indices.add(idx)

        tag = f"[T{idx}]"
        # 1-based index into tool_trace
        if 1 <= idx <= len(tool_trace):
            step = tool_trace[idx - 1]
            tool_name = getattr(step, "tool_name", "unknown")
            arguments = getattr(step, "arguments", {})
            raw_output = getattr(step, "raw_output", {})
            status = getattr(step, "status", "ok")
            tool_call_id = getattr(step, "tool_call_id", None)

            citations.append(
                CitationMetadata(
                    tag=tag,
                    index=idx,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    arguments=arguments,
                    status=status,
                    output_summary=_summarize_tool_output(raw_output),
                    valid=True,
                )
            )
        else:
            # Out-of-bounds citation (model hallucinated index)
            citations.append(
                CitationMetadata(
                    tag=tag,
                    index=idx,
                    tool_name="unexecuted_tool",
                    tool_call_id=None,
                    arguments={},
                    status="invalid",
                    output_summary={"error": f"Tool execution index {idx} was not executed (total tools: {len(tool_trace)})."},
                    valid=False,
                )
            )

    return citations


def validate_citations(text: str, total_tools_executed: int) -> Dict[str, Any]:
    """Audit citation integrity, checking for out-of-bounds citations or missing citations."""
    matches = [int(m) for m in CITATION_REGEX.findall(text or "") if m.isdigit()]
    unique_matches = sorted(list(set(matches)))

    valid = [idx for idx in unique_matches if 1 <= idx <= total_tools_executed]
    invalid = [idx for idx in unique_matches if idx < 1 or idx > total_tools_executed]
    uncited = [idx for idx in range(1, total_tools_executed + 1) if idx not in unique_matches]

    return {
        "total_citations_found": len(matches),
        "unique_citations_found": len(unique_matches),
        "valid_citations": valid,
        "invalid_citations": invalid,
        "uncited_tools": uncited,
        "is_valid": len(invalid) == 0,
        "coverage_ratio": (len(valid) / total_tools_executed) if total_tools_executed > 0 else 1.0,
    }
