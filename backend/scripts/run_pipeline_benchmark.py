#!/usr/bin/env python3
"""End-to-End Real-World Dataset Validation & Job History Benchmark.

Task: S2-AI-04
Executes the complete telemetry ingestion pipeline:
  [File Profiler] -> [Mapping Wizard] -> [Ingest Worker & Vectorized QC] -> [Job History DB Hook]

Validates full-scale reference datasets (Surya-A/B, PVDAQ, or custom solar files),
simulates end-to-end processing under realistic load conditions, compiles a detailed
QC Summary (GAP, FLATLINE, RANGE, SPIKE), and writes the final QC payload directly into
the database's background job history table associated with the run ID.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool
import typer

# Ensure project root in sys.path
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.app.ai.file_profiler import (
    FileProfileResult,
    FileProfiler,
    profile_file,
)
from backend.app.ai.ingest_worker import (
    DEFAULT_CANONICAL_BOUNDS,
    ChannelMappingConfig,
    IngestConfig,
    IngestResult,
    IngestWorker,
    QCFlag,
)
from backend.app.ai.job_history import (
    JobHistory,
    build_qc_summary,
    create_job_record_async,
    get_job_record_async,
    record_job_failure_async,
    record_job_qc_summary_async,
)
from backend.app.ai.mapping_suggester import (
    CANONICAL_SIGNALS,
    MappingSuggester,
    MappingSuggestion,
    suggest_mappings_async,
)
from backend.app.db.session import create_db_engine, init_db
from backend.app.models.base import Base, generate_uuid

app = typer.Typer(
    name="pipeline-benchmark",
    help="PlantIQ End-to-End Real-World Dataset Validation & Job History Benchmark CLI",
    add_completion=False,
)
console = Console()

DATASETS_DIR = Path(__file__).resolve().parent.parent.parent / "Datasets"

# Standard Reference Dataset Map
REFERENCE_PRESETS: Dict[str, Dict[str, Any]] = {
    "surya-a": {
        "name": "Surya-A Generation (Plant 1)",
        "path": DATASETS_DIR / "Plant_1_Generation_Data.csv",
        "description": "22 central inverters, 68,778 generation telemetry rows (Gandikota, India)",
        "scale_overrides": {"DC_POWER": 100.0},
        "device_col": "SOURCE_KEY",
    },
    "surya-a-weather": {
        "name": "Surya-A Weather Sensor (Plant 1)",
        "path": DATASETS_DIR / "Plant_1_Weather_Sensor_Data.csv",
        "description": "On-site meteorological station, 3,182 environmental rows (Bhadla Park)",
        "device_col": "SOURCE_KEY",
    },
    "surya-b": {
        "name": "Surya-B Generation (Plant 2)",
        "path": DATASETS_DIR / "Plant_2_Generation_Data.csv",
        "description": "22 string inverters, 67,698 generation rows (Gandikota, India)",
        "device_col": "SOURCE_KEY",
    },
    "surya-b-weather": {
        "name": "Surya-B Weather Sensor (Plant 2)",
        "path": DATASETS_DIR / "Plant_2_Weather_Sensor_Data.csv",
        "description": "On-site meteorological station, 3,259 environmental rows",
        "device_col": "SOURCE_KEY",
    },
    "pvdaq": {
        "name": "NREL PVDAQ Reference Solar Dataset",
        "path": DATASETS_DIR / "PVDAQ_Reference_Sample.csv",
        "description": "Standard NREL Photovoltaic Data Acquisition system telemetry format",
        "device_col": "Inverter_ID",
    },
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkRunResult:
    """Consolidated outcome of the end-to-end pipeline benchmark execution."""

    passed: bool
    run_id: str
    dataset_name: str
    dataset_path: str
    profiler_duration_ms: float
    mapping_duration_ms: float
    ingest_duration_ms: float
    total_duration_ms: float
    total_rows: int
    observations_created: int
    throughput_rows_per_sec: float
    throughput_obs_per_sec: float
    max_heartbeat_delay_ms: float
    event_loop_healthy: bool
    qc_summary: Dict[str, Any]
    job_record_id: Optional[str]
    job_status: str
    load_simulation: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to serializable dictionary."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Event Loop Heartbeat Monitor
# ---------------------------------------------------------------------------


class HeartbeatMonitor:
    """Monitors asyncio event loop tick latency to verify non-blocking execution."""

    def __init__(self, interval_ms: float = 20.0) -> None:
        self.interval_s = interval_ms / 1000.0
        self._running = False
        self._max_delay_ms = 0.0
        self._task: Optional[asyncio.Task[None]] = None

    async def _loop(self) -> None:
        last_time = time.perf_counter()
        while self._running:
            await asyncio.sleep(self.interval_s)
            now = time.perf_counter()
            elapsed_ms = (now - last_time) * 1000.0
            delay_ms = max(0.0, elapsed_ms - (self.interval_s * 1000.0))
            if delay_ms > self._max_delay_ms:
                self._max_delay_ms = delay_ms
            last_time = now

    def start(self) -> None:
        self._running = True
        self._max_delay_ms = 0.0
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> float:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return round(self._max_delay_ms, 2)


# ---------------------------------------------------------------------------
# PVDAQ Fixture Generator (For CI / Offline Demonstration)
# ---------------------------------------------------------------------------


def ensure_pvdaq_sample_dataset(file_path: Path, rows: int = 1500) -> Path:
    """Generate a synthetic NREL PVDAQ-standard CSV dataset if not present on disk."""
    if file_path.exists():
        return file_path

    file_path.parent.mkdir(parents=True, exist_ok=True)
    base_time = datetime(2023, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    inverters = ["INV_01", "INV_02"]
    num_timestamps = max(10, rows // len(inverters))

    lines = [
        "Date-Time,Site_ID,Inverter_ID,Ambient_Temp,Module_Temp,POA_Irradiance,AC_Power,DC_Power\n"
    ]
    step_minutes = 15
    curr_time = base_time

    for t_idx in range(num_timestamps):
        # Inject periodic GAP: advance clock by an extra 45 mins at step 100
        if t_idx == 100:
            curr_time += timedelta(minutes=45)

        time_str = curr_time.strftime("%Y-%m-%d %H:%M:%S")
        hour = curr_time.hour + (curr_time.minute / 60.0)

        # Diurnal solar curve
        if 6.0 <= hour <= 18.0:
            solar_factor = max(0.0, -((hour - 12.0) ** 2) / 36.0 + 1.0)
            poa_base = round(1000.0 * solar_factor, 2)
            amb_base = round(25.0 + 12.0 * solar_factor, 2)
            mod_base = round(amb_base + 20.0 * solar_factor, 2)
            dc_base = round(500.0 * solar_factor, 2)
            ac_base = round(480.0 * solar_factor * 0.98, 2)
        else:
            poa_base = 0.0
            amb_base = 20.0
            mod_base = 19.5
            dc_base = 0.0
            ac_base = 0.0

        for inv in inverters:
            amb = amb_base
            mod = mod_base
            poa = poa_base
            dc_kw = dc_base
            ac_kw = ac_base

            # Inject FLATLINE: identical values for 5 steps during daytime
            if 50 <= t_idx <= 55:
                mod = 42.15
                ac_kw = 350.0

            # Inject RANGE violation: ambient temp > 75 degC
            if t_idx == 75 and inv == "INV_01":
                amb = 85.0

            # Inject SPIKE: abnormal jump
            if t_idx == 85 and inv == "INV_01":
                ac_kw = 1200.0

            line = f"{time_str},NREL_SITE_01,{inv},{amb},{mod},{poa},{ac_kw},{dc_kw}\n"
            lines.append(line)

        curr_time += timedelta(minutes=step_minutes)

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return file_path


# ---------------------------------------------------------------------------
# Pipeline Mapping Auto-Resolver
# ---------------------------------------------------------------------------


def resolve_channel_mappings(
    profile_result: FileProfileResult,
    mapping_suggestions: Sequence[MappingSuggestion],
    scale_overrides: Optional[Dict[str, float]] = None,
) -> Tuple[str, Optional[str], List[ChannelMappingConfig]]:
    """Translate profiling stats and mapping suggestions into IngestWorker channel configs.

    Returns:
        (timestamp_column, device_id_column, channel_mappings)
    """
    scale_overrides = scale_overrides or {}

    # 1. Resolve Timestamp Column
    timestamp_col: Optional[str] = None
    if profile_result.timestamp_profile:
        timestamp_col = profile_result.timestamp_profile.column_name

    # Fallback to column mapped to "timestamp"
    if not timestamp_col:
        for sug in mapping_suggestions:
            if sug.suggested_canonical_key == "timestamp":
                timestamp_col = sug.raw_header
                break

    if not timestamp_col:
        # Default fallback
        timestamp_col = "DATE_TIME"

    # 2. Resolve Device ID Column
    device_col: Optional[str] = None
    for sug in mapping_suggestions:
        if sug.suggested_canonical_key == "device_id":
            device_col = sug.raw_header
            break

    if not device_col:
        # Heuristic check for common names
        for col_name in [c.name for c in profile_result.columns]:
            if col_name.upper() in ("SOURCE_KEY", "INVERTER_ID", "DEVICE_ID", "INVERTER"):
                device_col = col_name
                break

    # 3. Construct Channel Mappings for Telemetry Columns
    mappings: List[ChannelMappingConfig] = []
    # Dimensional keys to skip as observation channels
    skip_keys = {"timestamp", "device_id", "plant_id"}

    for sug in mapping_suggestions:
        canonical_key = sug.suggested_canonical_key
        if not canonical_key or canonical_key in skip_keys:
            continue

        raw_col = sug.raw_header
        if canonical_key not in CANONICAL_SIGNALS:
            continue

        target_meta = CANONICAL_SIGNALS[canonical_key]
        target_unit = target_meta.unit

        # Infer source unit from raw column suffix or default
        source_unit = target_unit
        norm_col = raw_col.lower()
        if "_kw" in norm_col or norm_col in ("dc_power", "ac_power", "pac", "pdc"):
            source_unit = "kW"
        elif "_kwh" in norm_col or norm_col in ("daily_yield", "total_yield", "daily_energy", "total_energy"):
            source_unit = "kWh"
        elif "degc" in norm_col or "temp" in norm_col:
            source_unit = "degC"
        elif "wm2" in norm_col or norm_col == "irradiation":
            source_unit = "kW/m²" if "kw" in norm_col or norm_col == "irradiation" else "W/m²"

        # Check explicit scale factor overrides
        scale_factor = scale_overrides.get(raw_col, 1.0)

        # Retrieve canonical bound limits
        bounds = DEFAULT_CANONICAL_BOUNDS.get(canonical_key)
        min_bound = bounds[0] if bounds else None
        max_bound = bounds[1] if bounds else None
        max_gradient = bounds[2] if bounds else None

        mappings.append(
            ChannelMappingConfig(
                raw_column=raw_col,
                canonical_key=canonical_key,
                source_unit=source_unit,
                target_unit=target_unit,
                min_bound=min_bound,
                max_bound=max_bound,
                max_gradient=max_gradient,
                scale_factor=scale_factor,
            )
        )

    return timestamp_col, device_col, mappings


# ---------------------------------------------------------------------------
# Core Benchmark Execution Function
# ---------------------------------------------------------------------------


async def execute_pipeline_benchmark(
    dataset_target: Union[str, Path] = "surya-a",
    run_id: Optional[str] = None,
    engine: Optional[Engine] = None,
    db_url: str = "sqlite:///:memory:",
    batch_size: int = 5000,
    target_throughput: float = 10000.0,
    simulate_load_workers: int = 1,
    verbose: bool = False,
    quiet: bool = False,
) -> BenchmarkRunResult:
    """Execute the complete end-to-end pipeline benchmark on a reference dataset.

    Steps:
    1. Initialize Job History tracking entry in DB.
    2. File Profiler: Inspect schema, cadence, and column statistics.
    3. Mapping Wizard: Deduce canonical mappings and build ChannelMappingConfigs.
    4. Ingest Worker: High-performance vectorized QC bitmask evaluation & bulk upsert.
    5. QC Summary Compilation: Aggregate GAP, FLATLINE, RANGE, SPIKE counts.
    6. Job History Update: Commit final QC summary and throughput into background job table.
    """
    start_total_time = time.perf_counter()
    active_run_id = str(run_id) if run_id else str(generate_uuid())

    # 1. Resolve Target File & Presets
    dataset_key = str(dataset_target).lower()
    preset_config: Optional[Dict[str, Any]] = None
    target_path: Path
    dataset_display_name: str
    scale_overrides: Dict[str, float] = {}

    if dataset_key in REFERENCE_PRESETS:
        preset_config = REFERENCE_PRESETS[dataset_key]
        target_path = Path(preset_config["path"])
        dataset_display_name = preset_config["name"]
        scale_overrides = preset_config.get("scale_overrides", {})
        if dataset_key == "pvdaq":
            ensure_pvdaq_sample_dataset(target_path, rows=1200)
    else:
        target_path = Path(dataset_target).resolve()
        dataset_display_name = target_path.name
        # Apply Plant 1 scale artifact automatically if filename matches
        if "plant_1_generation" in target_path.name.lower():
            scale_overrides = {"DC_POWER": 100.0}

    if not target_path.exists():
        raise FileNotFoundError(f"Target dataset file does not exist: {target_path}")

    # 2. Database & Engine Setup
    if engine is None:
        engine_kwargs: Dict[str, Any] = {}
        if db_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in db_url:
                engine_kwargs["poolclass"] = StaticPool
        active_engine = create_engine(db_url, **engine_kwargs)
    else:
        active_engine = engine

    # Ensure all tables exist (including job_history)
    init_db(active_engine)

    # 3. Create Pending/Running Job History Record in DB
    job_record = await create_job_record_async(
        engine_or_session=active_engine,
        run_id=active_run_id,
        job_type="pipeline_benchmark",
        dataset_name=dataset_display_name,
        dataset_path=str(target_path),
        metadata_json={
            "target_throughput": target_throughput,
            "batch_size": batch_size,
            "simulate_load_workers": simulate_load_workers,
        },
    )

    if not quiet:
        console.print(
            Panel.fit(
                f"[bold cyan]PlantIQ End-to-End Pipeline Benchmark & Job History Integration (S2-AI-04)[/bold cyan]\n"
                f"[bold]Run ID:[/bold] [yellow]{active_run_id}[/yellow]\n"
                f"[bold]Dataset:[/bold] {dataset_display_name} ({target_path.stat().st_size / 1024:.1f} KB)\n"
                f"[bold]Path:[/bold] {target_path}\n"
                f"[bold]Target Throughput:[/bold] [bold yellow]{target_throughput:,.0f} rows/s[/bold yellow] | "
                f"[bold]Batch Size:[/bold] {batch_size}\n"
                f"[bold]Database:[/bold] {db_url}",
                border_style="blue",
            )
        )

    # 4. Start Event Loop Heartbeat Monitor
    monitor = HeartbeatMonitor(interval_ms=20.0)
    monitor.start()

    try:
        # ===================================================================
        # STAGE 1: File Profiler
        # ===================================================================
        if not quiet:
            console.print("[bold blue]► Stage 1/4:[/bold blue] Running File Profiler (Polars & DuckDB)...")
        start_prof = time.perf_counter()
        profile_res = await profile_file(target_path, sparkline_points=30)
        profiler_duration_ms = (time.perf_counter() - start_prof) * 1000.0

        if not quiet:
            cadence_str = (
                profile_res.timestamp_profile.cadence_description
                if profile_res.timestamp_profile
                else "unknown"
            )
            console.print(
                f"  ✓ Profiled [bold green]{profile_res.row_count:,}[/bold green] rows & "
                f"[bold green]{profile_res.column_count}[/bold green] columns in {profiler_duration_ms:.2f} ms "
                f"(Cadence: {cadence_str})"
            )

        # ===================================================================
        # STAGE 2: Mapping Wizard
        # ===================================================================
        if not quiet:
            console.print("[bold blue]► Stage 2/4:[/bold blue] Running Hybrid Mapping Wizard (Two-Tier)...")
        start_map = time.perf_counter()

        # Extract column names and sample values
        col_names = [c.name for c in profile_res.columns]
        mapping_result = await suggest_mappings_async(col_names)
        mapping_duration_ms = (time.perf_counter() - start_map) * 1000.0

        # Translate suggestions to IngestWorker ChannelMappingConfigs
        timestamp_col, device_col, channel_mappings = resolve_channel_mappings(
            profile_result=profile_res,
            mapping_suggestions=mapping_result.suggestions,
            scale_overrides=scale_overrides,
        )

        # Allow preset device_col override if designated
        if preset_config and "device_col" in preset_config:
            device_col = preset_config["device_col"]

        if not quiet:
            console.print(
                f"  ✓ Resolved [bold green]{len(channel_mappings)} telemetry channels[/bold green] in {mapping_duration_ms:.2f} ms "
                f"(Timestamp: '{timestamp_col}', Device: '{device_col or 'N/A'}')"
            )

        # ===================================================================
        # STAGE 3: Ingestion Worker & Realistic Load Processing
        # ===================================================================
        cadence_sec = int(
            profile_res.timestamp_profile.median_interval_seconds
            if (profile_res.timestamp_profile and profile_res.timestamp_profile.median_interval_seconds > 0)
            else 900
        )
        ingest_config = IngestConfig(
            cadence_seconds=cadence_sec,
            batch_size=batch_size,
        )
        worker = IngestWorker(engine=active_engine, config=ingest_config)

        if not quiet:
            load_desc = f" ({simulate_load_workers} concurrent stream load)" if simulate_load_workers > 1 else ""
            console.print(f"[bold blue]► Stage 3/4:[/bold blue] Ingestion Worker & Vectorized QC Engine{load_desc}...")

        start_ingest = time.perf_counter()
        load_simulation_meta: Optional[Dict[str, Any]] = None

        if simulate_load_workers > 1:
            # Simulate realistic multi-stream concurrent load
            async def _worker_task(w_idx: int) -> IngestResult:
                # Use distinct asset prefix for partitioned load verification
                return await worker.ingest_file_async(
                    file_path=target_path,
                    timestamp_col=timestamp_col,
                    mappings=channel_mappings,
                    device_col=device_col,
                    default_asset_id=f"LOAD_STREAM_{w_idx}",
                )

            load_tasks = [_worker_task(i) for i in range(simulate_load_workers)]
            load_results = await asyncio.gather(*load_tasks)
            ingest_res = load_results[0]  # Primary result
            load_total_rows = sum(r.total_rows_processed for r in load_results)
            load_total_obs = sum(r.observations_created for r in load_results)
            load_simulation_meta = {
                "workers_count": simulate_load_workers,
                "total_rows_all_workers": load_total_rows,
                "total_obs_all_workers": load_total_obs,
            }
        else:
            ingest_res = await worker.ingest_file_async(
                file_path=target_path,
                timestamp_col=timestamp_col,
                mappings=channel_mappings,
                device_col=device_col,
            )

        ingest_duration_ms = (time.perf_counter() - start_ingest) * 1000.0

        if not quiet:
            console.print(
                f"  ✓ Ingested [bold green]{ingest_res.total_rows_processed:,} rows[/bold green] -> "
                f"[bold green]{ingest_res.observations_created:,} observations[/bold green] in {ingest_duration_ms:.2f} ms "
                f"([bold yellow]{ingest_res.throughput_rows_per_sec:,.1f} rows/s[/bold yellow])"
            )

        # Stop Heartbeat Monitor
        max_heartbeat_delay_ms = await monitor.stop()

        # ===================================================================
        # STAGE 4: QC Summary Compilation & Job History DB Commit
        # ===================================================================
        if not quiet:
            console.print("[bold blue]► Stage 4/4:[/bold blue] Compiling QC Summary & Writing to Database Job History...")

        extra_meta = {
            "profiler_cadence": profile_res.timestamp_profile.cadence_description if profile_res.timestamp_profile else "unknown",
            "profiler_interval_seconds": profile_res.timestamp_profile.median_interval_seconds if profile_res.timestamp_profile else 0.0,
            "channels_mapped_count": len(channel_mappings),
            "max_event_loop_delay_ms": max_heartbeat_delay_ms,
        }
        qc_summary = build_qc_summary(
            result=ingest_res,
            run_id=active_run_id,
            dataset_name=dataset_display_name,
            extra_metadata=extra_meta,
        )

        # Commit final QC Summary and metrics into JobHistory database table
        persisted_job = await record_job_qc_summary_async(
            engine_or_session=active_engine,
            run_id=active_run_id,
            qc_summary=qc_summary,
            total_rows=ingest_res.total_rows_processed,
            total_observations=ingest_res.observations_created,
            duration_ms=round(ingest_duration_ms, 2),
            throughput_rows_per_sec=ingest_res.throughput_rows_per_sec,
            metadata_json={
                "profiler_duration_ms": round(profiler_duration_ms, 2),
                "mapping_duration_ms": round(mapping_duration_ms, 2),
                "load_simulation": load_simulation_meta,
                "clean_count": ingest_res.clean_count,
                "gap_count": ingest_res.gap_count,
                "flatline_count": ingest_res.flatline_count,
                "range_count": ingest_res.range_count,
                "spike_count": ingest_res.spike_count,
            },
            status="completed",
        )

        # Verify database record persistence
        queried_record = await get_job_record_async(active_engine, active_run_id)
        assert queried_record is not None, "JobHistory record must be queryable after commit"
        assert queried_record.qc_summary is not None, "JobHistory qc_summary must not be empty"

        total_duration_ms = (time.perf_counter() - start_total_time) * 1000.0
        obs_throughput = (
            (ingest_res.observations_created / (ingest_duration_ms / 1000.0))
            if ingest_duration_ms > 0
            else 0.0
        )
        throughput_met = ingest_res.throughput_rows_per_sec >= target_throughput
        event_loop_healthy = max_heartbeat_delay_ms < 250.0
        passed = throughput_met and event_loop_healthy

        run_result = BenchmarkRunResult(
            passed=passed,
            run_id=active_run_id,
            dataset_name=dataset_display_name,
            dataset_path=str(target_path),
            profiler_duration_ms=round(profiler_duration_ms, 2),
            mapping_duration_ms=round(mapping_duration_ms, 2),
            ingest_duration_ms=round(ingest_duration_ms, 2),
            total_duration_ms=round(total_duration_ms, 2),
            total_rows=ingest_res.total_rows_processed,
            observations_created=ingest_res.observations_created,
            throughput_rows_per_sec=ingest_res.throughput_rows_per_sec,
            throughput_obs_per_sec=round(obs_throughput, 1),
            max_heartbeat_delay_ms=max_heartbeat_delay_ms,
            event_loop_healthy=event_loop_healthy,
            qc_summary=qc_summary,
            job_record_id=persisted_job.id,
            job_status=persisted_job.status,
            load_simulation=load_simulation_meta,
        )

        if not quiet:
            _render_benchmark_summary(run_result, target_throughput)

        return run_result

    except Exception as exc:
        await monitor.stop()
        # Record pipeline failure in background job table
        await record_job_failure_async(
            engine_or_session=active_engine,
            run_id=active_run_id,
            error_message=str(exc),
            metadata_json={"exception_type": exc.__class__.__name__},
        )
        raise


def _render_benchmark_summary(res: BenchmarkRunResult, target_throughput: float) -> None:
    """Render Rich visual tables and panels summarizing benchmark outcomes."""
    qc = res.qc_summary

    # 1. Pipeline Stages Performance Table
    perf_table = Table(title="Pipeline Stage Latencies & Ingestion Performance", border_style="cyan")
    perf_table.add_column("Pipeline Stage", style="bold white")
    perf_table.add_column("Duration (ms)", justify="right", style="cyan")
    perf_table.add_column("Throughput", justify="right", style="yellow")
    perf_table.add_column("Status", justify="center")

    t_status = "[green]PASS[/green]" if res.throughput_rows_per_sec >= target_throughput else "[red]FAIL[/red]"
    el_status = "[green]PASS[/green]" if res.event_loop_healthy else "[red]FAIL[/red]"

    perf_table.add_row("1. File Profiler", f"{res.profiler_duration_ms:,.2f} ms", "-", "[green]OK[/green]")
    perf_table.add_row("2. Mapping Wizard", f"{res.mapping_duration_ms:,.2f} ms", "-", "[green]OK[/green]")
    perf_table.add_row(
        "3. Ingestion Worker & QC",
        f"{res.ingest_duration_ms:,.2f} ms",
        f"{res.throughput_rows_per_sec:,.1f} rows/s",
        t_status,
    )
    perf_table.add_row(
        "4. Event Loop Responsiveness",
        f"Max stall: {res.max_heartbeat_delay_ms:.1f} ms",
        "< 250.0 ms target",
        el_status,
    )
    perf_table.add_row(
        "Total Pipeline Wall Time",
        f"{res.total_duration_ms:,.2f} ms ({(res.total_duration_ms / 1000.0):.2f} s)",
        f"{res.throughput_obs_per_sec:,.1f} obs/s",
        "[bold green]COMPLETE[/bold green]",
    )
    console.print(perf_table)

    # 2. QC Summary Anomaly Breakdown Table
    qc_table = Table(title=f"Dataset Quality Control (QC) Summary — Run: {res.run_id[:8]}", border_style="yellow")
    qc_table.add_column("QC Category", style="bold white")
    qc_table.add_column("Anomaly Description", style="dim white")
    qc_table.add_column("Observations Flagged", justify="right", style="cyan")
    qc_table.add_column("Proportion (%)", justify="right", style="magenta")
    qc_table.add_column("Bitmask Flag", justify="center", style="green")

    total_obs = max(1, res.observations_created)
    qc_table.add_row(
        "CLEAN",
        "Nominal reading without detected anomalies",
        f"{qc['clean_count']:,}",
        f"{qc['clean_percentage']:.2f}%",
        "0b0000 (0)",
    )
    qc_table.add_row(
        "GAP",
        "Missing timestamp intervals (> 1.5x expected cadence)",
        f"{qc['gap_count']:,}",
        f"{(qc['gap_count'] / total_obs) * 100.0:.2f}%",
        "0b0001 (1)",
    )
    qc_table.add_row(
        "FLATLINE",
        "Sensor repeating identical non-zero values (k >= 4)",
        f"{qc['flatline_count']:,}",
        f"{(qc['flatline_count'] / total_obs) * 100.0:.2f}%",
        "0b0010 (2)",
    )
    qc_table.add_row(
        "RANGE",
        "Violates physical or nameplate capacity boundary",
        f"{qc['range_count']:,}",
        f"{(qc['range_count'] / total_obs) * 100.0:.2f}%",
        "0b0100 (4)",
    )
    qc_table.add_row(
        "SPIKE",
        "Instantaneous gradient jump exceeding physical limit",
        f"{qc['spike_count']:,}",
        f"{(qc['spike_count'] / total_obs) * 100.0:.2f}%",
        "0b1000 (8)",
    )
    qc_table.add_section()
    qc_table.add_row(
        "[bold]TOTAL ANOMALIES[/bold]",
        "Observations tagged with >= 1 anomaly flag",
        f"[bold yellow]{qc['anomalies_total']:,}[/bold yellow]",
        f"[bold yellow]{qc['anomaly_rate_pct']:.2f}%[/bold yellow]",
        "[bold yellow]TAGGED[/bold yellow]",
    )
    console.print(qc_table)

    # 3. Final Panel
    panel_color = "green" if res.passed else "red"
    title_status = "PASSED" if res.passed else "FAILED"
    console.print(
        Panel(
            f"[bold]Pipeline Benchmark Status:[/bold] [{panel_color}]{title_status}[/{panel_color}]\n"
            f"[bold]Job History Run ID:[/bold] {res.run_id} (DB Record ID: {res.job_record_id})\n"
            f"[bold]Job Status:[/bold] [green]{res.job_status.upper()}[/green] | "
            f"[bold]Database Sync:[/bold] 100% of QC Summary persisted.\n"
            f"[bold]Throughput:[/bold] [{panel_color}]{res.throughput_rows_per_sec:,.1f} rows/s[/{panel_color}] "
            f"(Target: {target_throughput:,.0f} rows/s) | "
            f"[bold]Max Event Loop Stall:[/bold] {res.max_heartbeat_delay_ms:.1f} ms",
            title=f"[bold]Benchmark Result: {title_status}[/bold]",
            border_style=panel_color,
        )
    )


# ---------------------------------------------------------------------------
# CLI Command Entrypoints
# ---------------------------------------------------------------------------


@app.command()
def main(
    dataset: str = typer.Option(
        "surya-a",
        "--dataset",
        "-d",
        help="Target dataset preset (surya-a, surya-a-weather, surya-b, surya-b-weather, pvdaq, all)",
    ),
    file: Optional[Path] = typer.Option(
        None,
        "--file",
        "-f",
        help="Explicit path to custom solar telemetry CSV/Parquet file (overrides --dataset)",
    ),
    run_id: Optional[str] = typer.Option(
        None,
        "--run-id",
        "-r",
        help="Optional custom run ID to assign to the background job record",
    ),
    target_throughput: float = typer.Option(
        10000.0,
        "--target-throughput",
        "-t",
        help="Minimum required rows/sec to pass benchmark requirement",
    ),
    batch_size: int = typer.Option(
        5000,
        "--batch-size",
        "-b",
        help="Database chunk size for bulk upsert operations",
    ),
    db_url: str = typer.Option(
        "sqlite:///:memory:",
        "--db-url",
        help="Database connection string (defaults to sqlite in-memory)",
    ),
    simulate_load: int = typer.Option(
        1,
        "--simulate-load",
        "-l",
        help="Number of concurrent pipeline worker streams to simulate realistic load",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output results as clean JSON without Rich terminal formatting",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Display detailed verbose debug log",
    ),
) -> None:
    """Benchmark end-to-end solar telemetry ingestion pipeline and record QC summary to job history."""
    targets: List[Union[str, Path]] = []

    if file is not None:
        targets = [file]
    elif dataset.lower() == "all":
        targets = ["surya-a", "surya-a-weather", "surya-b", "surya-b-weather", "pvdaq"]
    else:
        targets = [dataset]

    overall_passed = True
    results_list: List[Dict[str, Any]] = []

    for target in targets:
        try:
            res = asyncio.run(
                execute_pipeline_benchmark(
                    dataset_target=target,
                    run_id=run_id if len(targets) == 1 else None,
                    db_url=db_url,
                    batch_size=batch_size,
                    target_throughput=target_throughput,
                    simulate_load_workers=simulate_load,
                    verbose=verbose,
                    quiet=json_output,
                )
            )
            results_list.append(res.to_dict())
            if not res.passed:
                overall_passed = False
        except Exception as e:
            if not json_output:
                console.print(f"[bold red]Pipeline Benchmark Failed for '{target}':[/bold red] {e}")
            results_list.append({"target": str(target), "passed": False, "error": str(e)})
            overall_passed = False

    if json_output:
        out = results_list[0] if len(results_list) == 1 else results_list
        print(json.dumps(out, indent=2, default=str))

    if not overall_passed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
