#!/usr/bin/env python3
"""CARE Benchmark Harness & Reporting CLI Tool (§12, Task S4-AI-05).

CARE: Comprehensive Anomaly Recognition & Evaluation
Executes automated benchmarking of PlantIQ anomaly detectors (D1 to D4 and rule baselines)
against historical solar operational datasets with known ground-truth fault labels.

Computes:
  * Classification Metrics: Precision, Recall, F1 Score, False Alarm Rate (FAR), Specificity.
  * Lead-Time Metrics: Advance warning minutes before complete hardware failure or peak loss.
  * Markdown Artifact Generation: Professional executive report for O&M stakeholders & investors.

Usage:
  python scripts/run_care_benchmark.py
  python scripts/run_care_benchmark.py --all-inverters
  python scripts/run_care_benchmark.py --detectors d1_statistical,d2_pr_deviation,d3_irradiance_residual,d4_isolation_forest
  python scripts/run_care_benchmark.py --output-markdown docs/care-benchmark-report.md
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# Ensure backend and repository roots are in sys.path
_backend_dir = str(Path(__file__).resolve().parent.parent)
_repo_dir = str(Path(__file__).resolve().parent.parent.parent)
for p in [_backend_dir, _repo_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.ai.care_benchmark import (
    CAREBenchmarkEngine,
    CAREBenchmarkSuite,
    DetectorBenchmarkResult,
    GroundTruthEvent,
)
from app.ai.detector_registry import DetectorRegistry

app = typer.Typer(
    name="care-benchmark",
    help="PlantIQ CARE Anomaly Detection Benchmark & Evaluation CLI (§12, Task S4-AI-05)",
    add_completion=False,
)
console = Console()

DEFAULT_DATASET = Path(_repo_dir) / "Datasets" / "Surya-A-demo.csv"
DEFAULT_GROUND_TRUTH = Path(_repo_dir) / "Datasets" / "ground_truth_anomalies.json"
DEFAULT_WEATHER = Path(_repo_dir) / "Datasets" / "Plant_1_Weather_Sensor_Data.csv"
DEFAULT_MARKDOWN_DOCS = Path(_repo_dir) / "docs" / "care-benchmark-report.md"
DEFAULT_ARTIFACT_DIR = Path("/home/stpl/.gemini/antigravity-ide/brain/34cecd50-bdfe-4733-abec-d839b80f65ee")


def _format_lead_time(minutes: float) -> str:
    """Format minutes into human readable lead time."""
    if minutes >= 60:
        return f"{minutes / 60.0:.1f} hrs"
    return f"{minutes:.0f} min"


@app.command()
def main(
    dataset: Path = typer.Option(
        DEFAULT_DATASET,
        "--dataset",
        "-d",
        help="Path to solar telemetry dataset CSV (e.g., Surya-A-demo.csv)",
    ),
    ground_truth: Path = typer.Option(
        DEFAULT_GROUND_TRUTH,
        "--ground-truth",
        "-g",
        help="Path to ground truth anomalies JSON catalog",
    ),
    weather: Optional[Path] = typer.Option(
        DEFAULT_WEATHER,
        "--weather",
        "-w",
        help="Optional path to weather sensor telemetry CSV",
    ),
    detectors: Optional[str] = typer.Option(
        None,
        "--detectors",
        help="Comma-separated list of detectors to evaluate (e.g. 'd1_statistical,d2_pr_deviation,d3_irradiance_residual,d4_isolation_forest')",
    ),
    all_inverters: bool = typer.Option(
        False,
        "--all-inverters",
        help="Evaluate across all 22 central inverters in the dataset instead of default focused subset (4 faulted + 4 clean)",
    ),
    tolerance_mins: float = typer.Option(
        60.0,
        "--tolerance-mins",
        "-t",
        help="Timestamp matching tolerance window in minutes for event alignment",
    ),
    output_markdown: Optional[Path] = typer.Option(
        DEFAULT_MARKDOWN_DOCS,
        "--output-markdown",
        "-m",
        help="Destination path for generated Markdown report",
    ),
    output_json: Optional[Path] = typer.Option(
        None,
        "--output-json",
        "-j",
        help="Destination path for structured JSON results export",
    ),
    artifact_dir: Optional[Path] = typer.Option(
        DEFAULT_ARTIFACT_DIR,
        "--artifact-dir",
        help="IDE Artifact Directory to mirror the generated markdown report",
    ),
    tariff_inr: float = typer.Option(
        4.20,
        "--tariff",
        help="Feed-in tariff rate in INR (₹) per kWh for loss calculation",
    ),
) -> None:
    """Execute the CARE Benchmark Harness across solar anomaly detectors."""
    console.print(
        Panel.fit(
            f"[bold magenta]PlantIQ CARE Benchmark Harness (§12, Task S4-AI-05)[/bold magenta]\n"
            f"[bold white]Comprehensive Anomaly Recognition & Evaluation Engine[/bold white]\n\n"
            f"• Telemetry Dataset: [cyan]{dataset.name}[/cyan]\n"
            f"• Ground Truth Catalog: [cyan]{ground_truth.name}[/cyan]\n"
            f"• Matching Tolerance: [yellow]±{tolerance_mins:.0f} minutes[/yellow]\n"
            f"• Financial Loss Tariff: [green]₹{tariff_inr:.2f} / kWh[/green]",
            title="S4-AI-05 Automated Evaluation",
            border_style="magenta",
        )
    )

    if not dataset.exists():
        console.print(f"[bold red]Error:[/bold red] Telemetry dataset not found: {dataset}")
        raise typer.Exit(code=1)

    if not ground_truth.exists():
        console.print(f"[bold red]Error:[/bold red] Ground truth catalog not found: {ground_truth}")
        raise typer.Exit(code=1)

    # Initialize Engine
    engine = CAREBenchmarkEngine(
        dataset_path=dataset,
        ground_truth_path=ground_truth,
        weather_path=weather if (weather and weather.exists()) else None,
        tariff_inr=tariff_inr,
        tolerance_minutes=tolerance_mins,
    )

    with console.status("[bold green]Loading telemetry and indexing ground truth catalog..."):
        engine.load_data()

    # Determine target inverters
    if all_inverters:
        target_devices = engine.devices
    else:
        # 4 faulted inverters + 4 clean control inverters
        faulted = [ev.device_id for ev in engine.ground_truth_events]
        clean = [d for d in engine.devices if d not in faulted][:4]
        target_devices = faulted + clean

    console.print(
        f"• Total Rows in File: [bold]{engine.df.height:,}[/bold] (15-min cadence)\n"
        f"• Inverters Profiled: [bold]{len(target_devices)}[/bold] ({len(engine.ground_truth_events)} faulted + {len(target_devices) - len(engine.ground_truth_events)} clean controls)\n"
        f"• Ground Truth Events: [bold yellow]{len(engine.ground_truth_events)} verified fault incidents[/bold yellow]\n"
    )

    # Determine detector keys
    det_list = None
    if detectors:
        det_list = [d.strip() for d in detectors.split(",") if d.strip()]

    # Execute Full Benchmark
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[bold cyan]Executing CARE benchmark suite across detectors...", total=None)
        suite = engine.run_full_benchmark(
            detector_keys=det_list,
            target_devices=target_devices,
            include_ensemble=True,
        )
        progress.update(task, completed=True)

    # 1. Terminal Table: Ground Truth Events
    gt_table = Table(title="Ground Truth Fault Catalog Verification", header_style="bold cyan")
    gt_table.add_column("Event ID", style="bold")
    gt_table.add_column("Category", style="yellow")
    gt_table.add_column("Target Device", style="cyan")
    gt_table.add_column("Window (UTC)", style="white")
    gt_table.add_column("Duration", style="white")
    gt_table.add_column("Affected Rows", style="dim")
    gt_table.add_column("Root Cause Pattern", style="green")

    for ev in suite.ground_truth_events:
        gt_table.add_row(
            ev.event_id,
            ev.anomaly_type.upper(),
            ev.device_id,
            f"{ev.start_time.strftime('%Y-%m-%d %H:%M')} -> {ev.end_time.strftime('%H:%M')}",
            f"{ev.duration_hours:.1f} hrs",
            f"{ev.affected_row_count} rows",
            ev.parameters.get("profile", ev.anomaly_type).replace("_", " ").capitalize(),
        )
    console.print(gt_table)

    # 2. Terminal Table: Algorithm Comparison Matrix
    results_table = Table(title="CARE Algorithm Performance Comparison Matrix", header_style="bold magenta")
    results_table.add_column("Detector / Model", style="bold")
    results_table.add_column("Event Prec.", style="cyan")
    results_table.add_column("Event Recall", style="bold green")
    results_table.add_column("Event F1", style="bold yellow")
    results_table.add_column("Interval F1", style="white")
    results_table.add_column("False Alarm Rate", style="blue")
    results_table.add_column("Mean Lead Time", style="bold cyan")
    results_table.add_column("Throughput", style="dim")

    all_res = list(suite.results_by_detector.values())
    if suite.ensemble_result:
        all_res.append(suite.ensemble_result)

    for r in all_res:
        em = r.event_metrics
        im = r.interval_metrics
        lm = r.lead_time_metrics
        results_table.add_row(
            r.detector_name,
            f"{em.precision * 100:.1f}%",
            f"{em.recall * 100:.1f}%",
            f"{em.f1_score:.3f}",
            f"{im.f1_score:.3f}",
            f"{im.false_alarm_rate * 100:.2f}%",
            _format_lead_time(lm.mean_lead_time_minutes),
            f"{r.throughput_rows_per_second:,.0f} rows/s",
        )
    console.print(results_table)

    # 3. Terminal Table: Lead-Time & Early Warning Capability
    lead_table = Table(title="Lead-Time & Early Warning Diagnostic Summary", header_style="bold green")
    lead_table.add_column("Fault ID", style="bold")
    lead_table.add_column("Category", style="yellow")
    lead_table.add_column("Target Device", style="cyan")
    lead_table.add_column("Best Detecting Model", style="bold")
    lead_table.add_column("Lead Time / Latency", style="bold green")
    lead_table.add_column("Diagnostic Benefit", style="white")

    for ev in suite.ground_truth_events:
        best_det_name = "-"
        best_lead_min = -999999.0
        best_note = "Missed"

        for r in all_res:
            if ev.event_id in r.lead_time_metrics.event_lead_times:
                lead = r.lead_time_metrics.event_lead_times[ev.event_id]
                if lead > best_lead_min:
                    best_lead_min = lead
                    best_det_name = r.detector_name
                    best_note = r.lead_time_metrics.promptness_notes.get(ev.event_id, "Detected")

        lead_str = _format_lead_time(best_lead_min) if best_lead_min > -999999 else "Missed"
        lead_table.add_row(
            ev.event_id,
            ev.anomaly_type.upper(),
            ev.device_id,
            best_det_name,
            lead_str,
            best_note,
        )
    console.print(lead_table)

    # 4. Generate & Save Markdown Report
    saved_paths = []
    if output_markdown:
        out_md = suite.save_markdown_report(output_markdown)
        saved_paths.append(str(out_md))

    # Also mirror into Artifact Directory if exists
    if artifact_dir and artifact_dir.exists():
        art_path = artifact_dir / "care_benchmark_report.md"
        suite.save_markdown_report(art_path)
        saved_paths.append(str(art_path))

    if output_json:
        out_js = suite.save_json(output_json)
        saved_paths.append(str(out_js))

    console.print(
        Panel.fit(
            f"[bold green]✓ CARE Benchmark Completed Successfully![/bold green]\n"
            f"• Run ID: [bold]{suite.run_id}[/bold]\n"
            f"• Reports Generated:\n"
            + "\n".join(f"  - [cyan]{p}[/cyan]" for p in saved_paths),
            title="Evaluation Summary",
            border_style="green",
        )
    )


if __name__ == "__main__":
    app()
