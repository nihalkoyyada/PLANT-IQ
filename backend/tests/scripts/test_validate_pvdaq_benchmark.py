"""Unit & Integration Tests for NREL PVDAQ Benchmark Validation CLI Tool (§11, Task S3-AI-03).

Validates:
1. CLI options, help message, and parameters.
2. Programmatic execution of `run_pvdaq_validation` against the cataloged PVDAQ dataset.
3. Verification that all 7 solar KPIs fall within the defined ±2% sanity tolerance margins.
4. JSON machine-readable export and Markdown validation note export.
5. Detection and flagging of sanity margin violations when out-of-bounds parameters are tested.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pytest
from typer.testing import CliRunner

from scripts.validate_pvdaq_benchmark import (
    DEFAULT_DATASET_PATH,
    PVDAQ_SANITY_MARGINS,
    PVDAQValidationReport,
    SanityMargin,
    app,
    export_markdown_validation_note,
    run_pvdaq_validation,
)

runner = CliRunner()


def test_cli_help() -> None:
    """Verify CLI help text and option listings."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "Validate PlantIQ KPI Engine against NREL PVDAQ benchmark datasets" in res.output
    assert "--dataset-path" in res.output
    assert "--dc-capacity" in res.output
    assert "--ac-capacity" in res.output
    assert "--export-markdown" in res.output


def test_run_pvdaq_validation_programmatic() -> None:
    """Verify programmatic execution on default PVDAQ reference sample."""
    report = run_pvdaq_validation(
        dataset_path=DEFAULT_DATASET_PATH,
        site_id="NREL_SITE_01",
        dc_capacity_kwp=1000.0,
        ac_capacity_kw=960.0,
        expected_pr=0.80,
    )

    assert isinstance(report, PVDAQValidationReport)
    assert report.site_id == "NREL_SITE_01"
    assert report.total_days == 6
    assert report.overall_sanity_passed is True

    # Check key average metrics against theoretical baselines
    avg = report.average_metrics
    # PR: 94.07% vs model baseline 94.08% (Delta < 0.1%)
    assert 0.93 <= avg["avg_pr"] <= 0.95
    # Inverter efficiency: ~94.07%
    assert 0.93 <= avg["avg_efficiency"] <= 0.96
    # Availability: 100%
    assert avg["avg_availability"] == 1.00
    # CUF: ~32.6% (24h) and ~66.7% (daylight)
    assert 0.30 <= avg["avg_cuf_24h"] <= 0.35
    assert 0.60 <= avg["avg_cuf_daylight"] <= 0.70

    # Ensure every single day passed all sanity checks
    for rec in report.daily_records:
        assert rec.all_sanity_passed is True
        for check in rec.sanity_checks.values():
            assert check["is_pass"] is True


def test_cli_execution_rich_table() -> None:
    """Verify CLI command renders successfully with exit code 0."""
    res = runner.invoke(
        app,
        ["--dataset-path", str(DEFAULT_DATASET_PATH)],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0
    assert "PlantIQ NREL PVDAQ Benchmark Validation Report" in res.output
    assert "Multi-Day Performance Rollups" in res.output
    assert "Sanity Check Margins & Delta Comparison" in res.output
    assert "Overall Pipeline Sanity Assessment: VERIFIED (PASS)" in res.output


def test_cli_json_export() -> None:
    """Verify CLI --json outputs well-structured, valid JSON."""
    res = runner.invoke(
        app,
        ["--dataset-path", str(DEFAULT_DATASET_PATH), "--json"],
    )
    assert res.exit_code == 0
    data = json.loads(res.output)

    assert data["site_id"] == "NREL_SITE_01"
    assert data["total_days"] == 6
    assert data["overall_sanity_passed"] is True
    assert "average_metrics" in data
    assert len(data["daily_records"]) == 6


def test_cli_markdown_export(tmp_path: Path) -> None:
    """Verify CLI --export-markdown generates the documentation artifact."""
    out_file = tmp_path / "test_validation_note.md"
    res = runner.invoke(
        app,
        [
            "--dataset-path", str(DEFAULT_DATASET_PATH),
            "--export-markdown", str(out_file),
        ],
    )
    assert res.exit_code == 0
    assert out_file.exists()

    content = out_file.read_text(encoding="utf-8")
    assert "# PlantIQ: NREL PVDAQ Benchmark Validation Note" in content
    assert "PASSED (VERIFIED)" in content
    assert "Performance Ratio (PR)" in content
    assert "Sanity Margins & Percentage Delta Comparison" in content
    assert "Deployment Readiness" in content


def test_sanity_margin_violation_detection() -> None:
    """Verify that unrealistic/strict tolerances detect violations and trigger failure."""
    strict_margins = {
        "pr": SanityMargin(
            name="Performance Ratio",
            expected_nominal=0.9408,
            tolerance_pct=0.0001,  # Impossibly tight tolerance (0.0001%)
            min_operational_bound=0.999,  # Unrealistic operational bound
            max_operational_bound=1.000,
            unit="ratio",
        ),
    }

    report = run_pvdaq_validation(
        dataset_path=DEFAULT_DATASET_PATH,
        sanity_tolerances=strict_margins,
    )

    # Must flag failure
    assert report.overall_sanity_passed is False
    assert any(not rec.all_sanity_passed for rec in report.daily_records)

    # CLI with --fail-on-error should exit with code 1
    # We test with a mock margin in runner
    res = runner.invoke(
        app,
        [
            "--dataset-path", str(DEFAULT_DATASET_PATH),
            "--dc-capacity", "2000.0",  # Distorts capacity, triggering margin error
            "--fail-on-error",
        ],
    )
    assert res.exit_code == 1
