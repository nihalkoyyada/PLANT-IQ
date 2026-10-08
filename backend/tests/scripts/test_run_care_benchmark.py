"""Unit & Integration Tests for CARE Benchmark CLI Script (§12, Task S4-AI-05).

Validates:
1. Typer CLI options, help output, and argument parsing.
2. CLI execution with filtered detector keys and custom output files.
3. Verification that Markdown report artifact is created on disk.
4. JSON export generation.
5. Error handling when invalid dataset paths are provided.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scripts.run_care_benchmark import (
    DEFAULT_DATASET,
    DEFAULT_GROUND_TRUTH,
    app,
)

runner = CliRunner()


def test_cli_help() -> None:
    """Verify that CLI help displays all options properly."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Execute the CARE Benchmark Harness across solar anomaly detectors" in result.output
    assert "--dataset" in result.output
    assert "--ground-truth" in result.output
    assert "--detectors" in result.output
    assert "--output-markdown" in result.output
    assert "--output-json" in result.output
    assert "--tolerance-mins" in result.output


def test_cli_missing_dataset_error(tmp_path: Path) -> None:
    """Verify proper error handling and exit code when dataset file does not exist."""
    fake_csv = tmp_path / "non_existent.csv"
    result = runner.invoke(app, ["--dataset", str(fake_csv)])
    assert result.exit_code != 0
    assert "Telemetry dataset not found" in result.output


@pytest.mark.skipif(not DEFAULT_DATASET.exists() or not DEFAULT_GROUND_TRUTH.exists(), reason="Reference datasets not found")
def test_cli_execution_with_filtered_detectors(tmp_path: Path) -> None:
    """Run CLI with focused detector list and check generated reports."""
    output_md = tmp_path / "cli_care_report.md"
    output_js = tmp_path / "cli_care_report.json"

    result = runner.invoke(
        app,
        [
            "--dataset", str(DEFAULT_DATASET),
            "--ground-truth", str(DEFAULT_GROUND_TRUTH),
            "--detectors", "trip,flatline",
            "--output-markdown", str(output_md),
            "--output-json", str(output_js),
            "--tolerance-mins", "60",
        ],
    )

    assert result.exit_code == 0
    assert "CARE Benchmark Completed Successfully" in result.output
    assert "Ground Truth Fault Catalog Verification" in result.output
    assert "Algorithm Performance Comparison Matrix" in result.output

    # Verify Markdown file exists and is populated
    assert output_md.exists()
    md_text = output_md.read_text(encoding="utf-8")
    assert "# PlantIQ: CARE Benchmark & Detector Validation Report" in md_text
    assert "Inverter Trip Detector" in md_text
    assert "Sensor Flatline Detector" in md_text

    # Verify JSON file exists and has valid structure
    assert output_js.exists()
    with open(output_js, "r", encoding="utf-8") as f:
        js_data = json.load(f)
    assert "results_by_detector" in js_data
    assert "trip" in js_data["results_by_detector"]
    assert "flatline" in js_data["results_by_detector"]
