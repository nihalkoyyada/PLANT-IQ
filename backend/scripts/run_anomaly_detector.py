"""CLI Runner to Manually Execute and Inspect Anomaly Detection Scans (§12, Task S4-AI-01).

Usage:
    python scripts/run_anomaly_detector.py
    python scripts/run_anomaly_detector.py --plant "Surya-A" --window-hours 48
    python scripts/run_anomaly_detector.py --list-detectors
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

# Ensure backend root is on sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from sqlalchemy import select

from app.ai.detector_registry import DetectorRegistry
from app.db.session import create_db_engine, get_session_factory
from app.models.entities import Anomaly, Plant
from app.tasks.detector_tasks import execute_plant_anomaly_scan, run_scheduled_anomaly_scans

console = Console()


def list_registered_detectors() -> None:
    """Print all available anomaly detectors registered in the plugin registry."""
    table = Table(title="PlantIQ Registered Anomaly Detectors", header_style="bold cyan")
    table.add_column("Detector Key", style="bold green")
    table.add_column("Class Name", style="white")
    table.add_column("Description", style="dim")

    for meta in DetectorRegistry.all_metadata():
        table.add_row(meta["name"], meta["class_name"], meta["description"])

    console.print(table)


def run_scan(plant_name: Optional[str] = None, window_hours: int = 24) -> None:
    """Execute manual anomaly scan and display a formatted report."""
    engine = create_db_engine()
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        if plant_name:
            plant = session.execute(
                select(Plant).where(Plant.name.ilike(f"%{plant_name}%"))
            ).scalars().first()

            if not plant:
                console.print(f"[bold red]Error:[/bold red] No plant matching '{plant_name}' found in database.")
                return

            console.print(
                Panel.fit(
                    f"[bold yellow]PlantIQ Anomaly Detector Engine[/bold yellow]\n"
                    f"Target Plant: [cyan]{plant.name}[/cyan] (ID: {plant.id})\n"
                    f"Analysis Window: Past [cyan]{window_hours}[/cyan] hours\n"
                    f"Plant Tariff: [green]₹{plant.tariff_inr_per_kwh or 3.50:.2f} / kWh[/green]",
                    title="Manual Scan Trigger",
                    border_style="cyan",
                )
            )

            with console.status("[bold green]Executing anomaly detectors across active channels..."):
                result = execute_plant_anomaly_scan(
                    db=session,
                    plant_id=plant.id,
                    window_hours=window_hours,
                )

            console.print(f"\n[bold green]✓ Scan Completed successfully![/bold green]")
            console.print(
                f"• Detectors evaluated: [bold]{result.get('detectors_evaluated', 0)}[/bold]\n"
                f"• Total anomalies detected: [bold]{result.get('anomalies_detected', 0)}[/bold]\n"
                f"• New records created: [bold green]{result.get('anomalies_created', 0)}[/bold green]\n"
                f"• Ongoing events merged: [bold yellow]{result.get('anomalies_merged', 0)}[/bold yellow] (deduplicated)\n"
            )

            # Query and display the latest anomalies for this plant
            recent_anomalies = (
                session.execute(
                    select(Anomaly)
                    .where(Anomaly.plant_id == plant.id)
                    .order_by(Anomaly.start_time.desc())
                    .limit(10)
                )
                .scalars()
                .all()
            )

            if recent_anomalies:
                table = Table(title=f"Recent Anomalies on {plant.name}", header_style="bold magenta")
                table.add_column("Severity", style="bold")
                table.add_column("Asset", style="cyan")
                table.add_column("Time Window (UTC)", style="white")
                table.add_column("Score", style="yellow")
                table.add_column("Est. Loss (kWh)", style="bold red")
                table.add_column("Financial Loss (₹)", style="bold green")
                table.add_column("Status", style="blue")
                table.add_column("Summary", style="dim")

                for a in recent_anomalies:
                    severity_color = {
                        "critical": "red",
                        "high": "bright_red",
                        "medium": "yellow",
                        "low": "blue",
                    }.get(a.severity, "white")

                    asset_name = a.asset.name if a.asset else "Plant-Level"
                    time_span = f"{a.start_time.strftime('%H:%M')} -> {a.end_time.strftime('%H:%M') if a.end_time else 'ongoing'}"
                    details = a.details or {}
                    kwh = details.get("total_energy_loss_kwh", 0.0)
                    inr = details.get("total_financial_loss_inr", 0.0)

                    table.add_row(
                        f"[{severity_color}]{a.severity.upper()}[/{severity_color}]",
                        asset_name,
                        time_span,
                        f"{a.score:.2f}",
                        f"{kwh:,.1f} kWh",
                        f"₹{inr:,.2f}",
                        a.status,
                        (a.summary or "")[:50] + ("..." if len(a.summary or "") > 50 else ""),
                    )

                console.print(table)
            else:
                console.print("[dim]No active anomalies found on this plant.[/dim]")

        else:
            console.print("[cyan]Triggering multi-plant background scan...[/cyan]")
            result = run_scheduled_anomaly_scans(window_hours=window_hours)
def run_demo_simulation(tariff_inr: float = 4.20) -> None:
    """Run an end-to-end simulation of real-world solar anomalies, severity policy, and deduplication."""
    from datetime import timedelta
    from app.ai.anomaly_policy import FinancialLossPolicy, SeverityPolicy
    from app.ai.detector_registry import DetectedAnomaly, DetectorContext

    console.print(
        Panel.fit(
            f"[bold magenta]PlantIQ Detector Framework Simulation Demo[/bold magenta]\n"
            f"Simulating: [yellow]Surya-A Inverter INV-01 (Rated: 1,000 kW)[/yellow]\n"
            f"Tariff: [green]₹{tariff_inr:.2f} / kWh[/green]\n"
            f"Testing: [cyan]Deviation, Trip, Flatline, Severity Tiers & Window Merging[/cyan]",
            title="S4-AI-01 Live Demonstration",
            border_style="magenta",
        )
    )

    base_time = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
    # Generate 15-minute readings from 06:00 to 18:00 (48 intervals)
    observations = []
    for i in range(48):
        ts = base_time + timedelta(minutes=15 * i)
        hour = ts.hour + (ts.minute / 60.0)
        # Normal diurnal bell curve
        normal_power = max(0.0, 950.0 * math.sin((hour - 6.0) / 12.0 * math.pi))

        # Fault Injection:
        # 1. Deviation derating (10:00 to 11:30): drops to 250 kW
        if 10.0 <= hour <= 11.5:
            val = 250.0
        # 2. Midday Trip (12:00 to 13:00): drops to 0.0 kW
        elif 12.0 <= hour <= 13.0:
            val = 0.0
        # 3. Sensor Flatline (14:30 to 15:45): frozen at 480.0 kW
        elif 14.5 <= hour <= 15.75:
            val = 480.0
        else:
            val = normal_power

        observations.append((ts, val))

    ctx = DetectorContext(
        plant_id=UUID("63d2b0a1-ed00-44d4-97be-0afe76b6749f"),
        asset_id=UUID("11111111-2222-3333-4444-555555555555"),
        canonical_key="active_power",
        plant_name="Surya-A",
        asset_name="INV-01",
        rated_kw=1000.0,
        expected_pr=0.85,
        tariff_inr_per_kwh=tariff_inr,
    )

    # 1. Run Detectors
    all_anomalies: List[DetectedAnomaly] = []
    for method in ["trip", "deviation", "flatline", "zscore"]:
        det = DetectorRegistry.get(method)
        candidates = det.detect(observations, parameters={}, context=ctx)
        for c in candidates:
            # Classify severity
            duration_mins = max(1, int((c.end_time - c.start_time).total_seconds() / 60))
            c.severity = SeverityPolicy.evaluate(
                loss_kw=c.loss_kw,
                loss_kwh=c.loss_kwh,
                score=c.score,
                duration_minutes=duration_mins,
                anomaly_type=c.anomaly_type,
                rated_kw=1000.0,
            )
            all_anomalies.append(c)

    table = Table(title="Detected Anomalies & Impact Analysis", header_style="bold cyan")
    table.add_column("Type", style="bold")
    table.add_column("Severity", style="bold")
    table.add_column("Time Window (UTC)", style="white")
    table.add_column("Duration", style="white")
    table.add_column("Score", style="yellow")
    table.add_column("Energy Loss (kWh)", style="bold red")
    table.add_column("Financial Impact (₹)", style="bold green")
    table.add_column("Summary / Diagnostic", style="dim")

    for a in all_anomalies:
        severity_color = {
            "critical": "red",
            "high": "bright_red",
            "medium": "yellow",
            "low": "blue",
        }.get(a.severity or "medium", "white")

        dur = f"{int((a.end_time - a.start_time).total_seconds() / 60)} mins"
        time_span = f"{a.start_time.strftime('%H:%M')} -> {a.end_time.strftime('%H:%M')}"
        loss_kwh = a.loss_kwh or 0.0
        loss_inr = loss_kwh * tariff_inr

        table.add_row(
            a.anomaly_type.upper(),
            f"[{severity_color}]{(a.severity or 'medium').upper()}[/{severity_color}]",
            time_span,
            dur,
            f"{a.score:.2f}",
            f"{loss_kwh:,.1f} kWh",
            f"₹{loss_inr:,.2f}",
            a.summary,
        )

def run_csv_dataset_scan(
    csv_path: str,
    ground_truth_path: Optional[str] = None,
    target_devices: Optional[List[str]] = None,
    detector_methods: Optional[List[str]] = None,
    tariff_inr: float = 4.20,
) -> None:
    """Scan a solar CSV dataset (e.g. Surya-A-demo.csv) with injected field anomalies."""
    import json
    import polars as pl
    from app.ai.anomaly_policy import FinancialLossPolicy, SeverityPolicy
    from app.ai.detector_registry import DetectedAnomaly, DetectorContext

    file_path = Path(csv_path).resolve()
    if not file_path.exists():
        console.print(f"[bold red]Error:[/bold red] CSV file not found: {file_path}")
        return

    console.print(
        Panel.fit(
            f"[bold cyan]Scanning Solar Telemetry Dataset[/bold cyan]\n"
            f"File: [white]{file_path.name}[/white] ({file_path})\n"
            f"Tariff: [green]₹{tariff_inr:.2f} / kWh[/green]",
            title="S4-AI-01 Dataset Anomaly Scan",
            border_style="cyan",
        )
    )

    with console.status("[bold green]Loading and parsing CSV telemetry..."):
        df = pl.read_csv(str(file_path))

    total_rows = df.height
    all_inverters = df["SOURCE_KEY"].unique().to_list()

    # Default to affected devices if not specified
    if not target_devices:
        target_devices = ["1IF53ai7Xc0U56Y", "7JYdWkrLSPkdwr4", "3PZuoBAID5Wc2HD", "1BY6WEcLGh8j5v7"]

    # Filter to requested devices
    active_devices = [d for d in target_devices if d in all_inverters]
    if not active_devices:
        active_devices = all_inverters[:4]

    console.print(
        f"• Total Rows: [bold]{total_rows:,}[/bold]\n"
        f"• Inverters in file: [bold]{len(all_inverters)}[/bold]\n"
        f"• Scanning target devices: [bold yellow]{', '.join(active_devices)}[/bold yellow]\n"
    )

    # Load ground truth if available
    ground_truth_events = []
    if ground_truth_path:
        gt_file = Path(ground_truth_path).resolve()
        if gt_file.exists():
            with open(gt_file, "r") as f:
                gt_data = json.load(f)
                ground_truth_events = gt_data.get("events", [])
    elif (file_path.parent / "ground_truth_anomalies.json").exists():
        with open(file_path.parent / "ground_truth_anomalies.json", "r") as f:
            gt_data = json.load(f)
            ground_truth_events = gt_data.get("events", [])

    results_table = Table(title="Detected Anomalies from Dataset", header_style="bold magenta")
    results_table.add_column("Device / Inverter", style="cyan")
    results_table.add_column("Type", style="bold")
    results_table.add_column("Severity", style="bold")
    results_table.add_column("Time Window (UTC)", style="white")
    results_table.add_column("Duration", style="white")
    results_table.add_column("Score", style="yellow")
    results_table.add_column("Est. Loss (kWh)", style="bold red")
    results_table.add_column("Financial Impact (₹)", style="bold green")
    results_table.add_column("Ground Truth Match", style="bold green")

    total_detected = 0
    total_loss_kwh = 0.0
    total_loss_inr = 0.0

    for dev in active_devices:
        dev_df = df.filter(pl.col("SOURCE_KEY") == dev)
        observations = []

        # Parse timestamps and AC_POWER
        for row in dev_df.select(["DATE_TIME", "AC_POWER"]).iter_rows():
            dt_str = str(row[0]).strip()
            try:
                # First try Day-Month-Year (e.g. 15-05-2020 00:00)
                ts = datetime.strptime(dt_str, "%d-%m-%Y %H:%M").replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    ts = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

            try:
                observations.append((ts, float(row[1])))
            except Exception:
                continue

        if not observations:
            continue

        ctx = DetectorContext(
            plant_id=UUID("63d2b0a1-ed00-44d4-97be-0afe76b6749f"),
            asset_name=dev,
            canonical_key="ac_power",
            rated_kw=1000.0,
            expected_pr=0.85,
            tariff_inr_per_kwh=tariff_inr,
        )

        dev_candidates: List[DetectedAnomaly] = []
        methods_to_run = detector_methods or [
            "trip", "flatline", "clipping", "soiling",
            "d1_statistical", "d2_pr_deviation", "d3_irradiance_residual", "d4_isolation_forest"
        ]
        for method in methods_to_run:
            if not DetectorRegistry.has_detector(method):
                continue
            det = DetectorRegistry.get(method)
            cands = det.detect(observations, {}, ctx)
            for c in cands:
                dur_mins = max(1, int((c.end_time - c.start_time).total_seconds() / 60))
                c.severity = SeverityPolicy.evaluate(
                    loss_kw=c.loss_kw,
                    loss_kwh=c.loss_kwh,
                    score=c.score,
                    duration_minutes=dur_mins,
                    anomaly_type=c.anomaly_type,
                    rated_kw=1000.0,
                )
                dev_candidates.append(c)

        for a in dev_candidates:
            total_detected += 1
            loss_kwh = a.loss_kwh or 0.0
            loss_inr = loss_kwh * tariff_inr
            total_loss_kwh += loss_kwh
            total_loss_inr += loss_inr

            # Check ground truth match
            gt_match = "-"
            for gt in ground_truth_events:
                if gt.get("device_id") == dev and gt.get("anomaly_type") == a.anomaly_type:
                    gt_match = f"✓ {gt.get('event_id')}"
                    break

            severity_color = {
                "critical": "red",
                "high": "bright_red",
                "medium": "yellow",
                "low": "blue",
            }.get(a.severity or "medium", "white")

            dur_str = f"{int((a.end_time - a.start_time).total_seconds() / 60)} mins"
            time_str = f"{a.start_time.strftime('%Y-%m-%d %H:%M')} -> {a.end_time.strftime('%H:%M')}"

            results_table.add_row(
                dev,
                a.anomaly_type.upper(),
                f"[{severity_color}]{(a.severity or 'medium').upper()}[/{severity_color}]",
                time_str,
                dur_str,
                f"{a.score:.2f}",
                f"{loss_kwh:,.1f} kWh",
                f"₹{loss_inr:,.2f}",
                gt_match,
            )

    console.print(results_table)
    console.print(
        Panel.fit(
            f"• Total Anomalies Detected: [bold]{total_detected}[/bold]\n"
            f"• Total Energy Deficit: [bold red]{total_loss_kwh:,.1f} kWh[/bold red]\n"
            f"• Estimated Financial Impact: [bold green]₹{total_loss_inr:,.2f}[/bold green]",
            title="Scan Summary",
            border_style="green",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="PlantIQ Anomaly Detection CLI Runner")
    parser.add_argument("--plant", "-p", type=str, default="Surya-A", help="Name or partial name of target plant")
    parser.add_argument("--window-hours", "-w", type=int, default=24, help="Lookback window in hours (default: 24)")
    parser.add_argument("--list-detectors", "-l", action="store_true", help="List all registered anomaly detectors")
    parser.add_argument("--all-plants", "-a", action="store_true", help="Run scan across all plants")
    parser.add_argument("--demo", action="store_true", help="Run simulated test scenario showing detection, policies & dedup")
    parser.add_argument("--csv", type=str, default=None, help="Path to telemetry CSV dataset (e.g. Datasets/Surya-A-demo.csv)")
    parser.add_argument("--ground-truth", type=str, default=None, help="Path to ground truth JSON file")
    parser.add_argument("--detector", "-d", type=str, default=None, help="Specific detector(s) e.g. d1_statistical,d2_pr_deviation,trip,flatline,clipping,soiling")
    parser.add_argument("--all-devices", action="store_true", help="Scan all inverters in the CSV file")
    parser.add_argument("--device", type=str, default=None, help="Specific device ID to scan in CSV")

    args = parser.parse_args()

    if args.list_detectors:
        list_registered_detectors()
    elif args.demo:
        run_demo_simulation()
    elif args.csv:
        target_devs = None
        if args.device:
            target_devs = [args.device]
        elif args.all_devices:
            target_devs = None  # scanned inside

        det_methods = [m.strip().lower() for m in args.detector.split(",")] if args.detector else None

        run_csv_dataset_scan(
            csv_path=args.csv,
            ground_truth_path=args.ground_truth,
            target_devices=target_devs,
            detector_methods=det_methods,
        )
    elif args.all_plants:
        run_scan(plant_name=None, window_hours=args.window_hours)
    else:
        run_scan(plant_name=args.plant, window_hours=args.window_hours)


if __name__ == "__main__":
    main()

