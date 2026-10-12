"""High-Performance File Profiler using Polars and DuckDB.

Task: S2-AI-01
Inspects uploaded solar telemetry files (CSV, Parquet, Excel), extracts schema
and data types, automatically detects timestamp formats and sensor sampling
intervals (cadence), generates column descriptive statistics, and downsamples
sparkline arrays for frontend visualization.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# Ensure project root is in sys.path for direct script execution
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import duckdb
import polars as pl
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

# ---------------------------------------------------------------------------
# Typed Custom Exceptions
# ---------------------------------------------------------------------------


class ProfilerError(Exception):
    """Base exception for file profiling errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class EmptyFileError(ProfilerError):
    """Raised when an inspected file is 0 bytes or contains 0 data rows."""


class UnsupportedFileFormatError(ProfilerError):
    """Raised when an inspected file extension is not supported."""


class TimestampDetectionError(ProfilerError):
    """Raised when timestamp detection fails on an expected datetime column."""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnStatistic:
    """Descriptive statistics and downsampled sparkline for a single column."""

    name: str
    dtype: str
    null_count: int
    null_percentage: float
    distinct_count: int
    min_value: Optional[Union[float, int, str]] = None
    max_value: Optional[Union[float, int, str]] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    sparkline: List[float] = field(default_factory=list)


@dataclass(frozen=True)
class TimestampProfile:
    """Metadata profile for the detected primary timestamp column."""

    column_name: str
    detected_format: str
    start_time: str
    end_time: str
    duration_hours: float
    median_interval_seconds: float
    is_regular_cadence: bool
    cadence_description: str


@dataclass(frozen=True)
class FileProfileResult:
    """Complete profiling output for an inspected telemetry file."""

    file_path: str
    file_name: str
    file_format: str
    file_size_bytes: int
    row_count: int
    column_count: int
    columns: List[ColumnStatistic]
    timestamp_profile: Optional[TimestampProfile]
    profiling_duration_ms: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert profile result to JSON-serializable dictionary."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Known Timestamp Format Candidates
# ---------------------------------------------------------------------------

TIMESTAMP_PATTERNS: List[Tuple[str, str]] = [
    ("ISO-8601 Seconds", "%Y-%m-%d %H:%M:%S"),
    ("ISO-8601 Minutes", "%Y-%m-%d %H:%M"),
    ("ISO-8601 T-Sep Seconds", "%Y-%m-%dT%H:%M:%S"),
    ("ISO-8601 T-Sep Minutes", "%Y-%m-%dT%H:%M"),
    ("Day-First Hyphen Minutes", "%d-%m-%Y %H:%M"),
    ("Day-First Hyphen Seconds", "%d-%m-%Y %H:%M:%S"),
    ("Day-First Slash Minutes", "%d/%m/%Y %H:%M"),
    ("Day-First Slash Seconds", "%d/%m/%Y %H:%M:%S"),
    ("Month-First Slash Minutes", "%m/%d/%Y %H:%M"),
    ("Month-First Slash Seconds", "%m/%d/%Y %H:%M:%S"),
    ("Date Only Hyphen", "%Y-%m-%d"),
    ("Date Only Day-First", "%d-%m-%Y"),
    ("Date Only Slash", "%d/%m/%Y"),
]

TIMESTAMP_NAME_REGEX = re.compile(
    r"(date_time|datetime|timestamp|time|date|ts|datum|zeit)", re.IGNORECASE
)


def _to_float(val: Any, default: float = 0.0) -> float:
    """Safely convert any numeric value or scalar to float."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _to_optional_float(val: Any) -> Optional[float]:
    """Safely convert any numeric value or scalar to float or None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# File Profiler Engine
# ---------------------------------------------------------------------------


class FileProfiler:
    """High-performance file profiler powered by Polars and DuckDB."""

    SUPPORTED_EXTENSIONS = {".csv", ".parquet", ".pq", ".xlsx", ".xls"}

    def __init__(self, duckdb_conn: Optional[duckdb.DuckDBPyConnection] = None) -> None:
        self.duckdb_conn = duckdb_conn or duckdb.connect(database=":memory:")

    def profile(
        self,
        file_path: Union[str, Path],
        sparkline_points: int = 50,
        timestamp_column: Optional[str] = None,
    ) -> FileProfileResult:
        """Synchronously profile a telemetry file.

        Args:
            file_path: Path to the CSV, Parquet, or Excel file.
            sparkline_points: Target resolution points for sparkline downsampling.
            timestamp_column: Optional explicit name of the timestamp column.

        Returns:
            FileProfileResult dataclass.
        """
        start_time = time.perf_counter()
        path = Path(file_path).resolve()

        if not path.exists():
            raise ProfilerError(f"File not found: {path}")

        file_size = path.stat().st_size
        if file_size == 0:
            raise EmptyFileError(f"File is empty (0 bytes): {path.name}")

        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise UnsupportedFileFormatError(
                f"Unsupported file format '{ext}'. Supported formats: {sorted(self.SUPPORTED_EXTENSIONS)}"
            )

        # 1. Load into Polars DataFrame
        df = self._load_dataframe(path, ext)
        if len(df) == 0:
            raise EmptyFileError(f"File contains 0 data rows: {path.name}")

        # 2. Detect & profile timestamp column
        ts_profile: Optional[TimestampProfile] = None
        ts_info = self._detect_timestamp_column(df, override_col=timestamp_column)
        if ts_info:
            col_name, fmt_name, parsed_ts = ts_info
            ts_profile = self._compute_timestamp_profile(col_name, fmt_name, parsed_ts)

        # 3. Compute Column Statistics & Sparklines
        column_stats = self._compute_column_statistics(df, sparkline_points=sparkline_points)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return FileProfileResult(
            file_path=str(path),
            file_name=path.name,
            file_format=ext.lstrip("."),
            file_size_bytes=file_size,
            row_count=len(df),
            column_count=len(df.columns),
            columns=column_stats,
            timestamp_profile=ts_profile,
            profiling_duration_ms=round(duration_ms, 2),
        )

    def _load_dataframe(self, path: Path, ext: str) -> pl.DataFrame:
        """Load tabular file into Polars DataFrame using high-throughput readers."""
        try:
            if ext == ".csv":
                # Use large schema inference to handle transition from nighttime integer 0 to daytime floats
                return pl.read_csv(
                    path,
                    infer_schema_length=10000,
                    ignore_errors=False,
                    truncate_ragged_lines=True,
                )
            if ext in (".parquet", ".pq"):
                return pl.read_parquet(path)
            if ext in (".xlsx", ".xls"):
                res = pl.read_excel(path)
                return pl.DataFrame(res)
            raise UnsupportedFileFormatError(f"Unsupported extension: {ext}")
        except EmptyFileError:
            raise
        except Exception as e:
            # Fallback to DuckDB reader if Polars throws a delimiter or encoding error on CSV
            if ext == ".csv":
                try:
                    rel = self.duckdb_conn.execute(
                        "SELECT * FROM read_csv_auto(?, ignore_errors=true)", [str(path)]
                    )
                    arrow_table = rel.arrow()
                    return pl.DataFrame(arrow_table)  # type: ignore[return-value]
                except Exception as duck_err:
                    raise ProfilerError(
                        f"Failed to read CSV '{path.name}': {e} (DuckDB fallback: {duck_err})"
                    ) from e
            raise ProfilerError(f"Failed to read file '{path.name}': {e}") from e

    def _detect_timestamp_column(
        self, df: pl.DataFrame, override_col: Optional[str] = None
    ) -> Optional[Tuple[str, str, pl.Series]]:
        """Identify timestamp column and return (column_name, format_name, parsed_series)."""
        candidate_cols: List[str] = []

        if override_col:
            if override_col not in df.columns:
                raise TimestampDetectionError(
                    f"Specified timestamp column '{override_col}' not found in file columns: {df.columns}"
                )
            candidate_cols = [override_col]
        else:
            # Check existing datetime/date types first
            for col in df.columns:
                dtype = df.schema[col]
                if dtype.is_temporal():
                    candidate_cols.append(col)

            # Next check name heuristics
            for col in df.columns:
                if col not in candidate_cols and TIMESTAMP_NAME_REGEX.search(col):
                    candidate_cols.append(col)

            # Fallback: check remaining string columns
            for col in df.columns:
                if col not in candidate_cols and df.schema[col] == pl.String:
                    candidate_cols.append(col)

        # Test each candidate column against known timestamp patterns
        for col in candidate_cols:
            series = df[col]

            # If already temporal in Polars
            if series.dtype.is_temporal():
                parsed = series.cast(pl.Datetime)
                return col, "Native Temporal", parsed

            # If string type, try pattern matching
            if series.dtype == pl.String:
                sample = series.drop_nulls()
                if len(sample) == 0:
                    continue

                for fmt_label, fmt_str in TIMESTAMP_PATTERNS:
                    try:
                        parsed = series.str.strptime(pl.Datetime, fmt_str, strict=False)
                        non_null_count = len(parsed.drop_nulls())
                        # If >= 80% successfully parsed, we consider this format valid
                        if non_null_count / max(1, len(sample)) >= 0.8:
                            return col, fmt_label, parsed
                    except Exception:
                        continue

                # Try generic polars ISO parser
                try:
                    parsed = series.str.to_datetime(strict=False)
                    non_null_count = len(parsed.drop_nulls())
                    if non_null_count / max(1, len(sample)) >= 0.8:
                        return col, "ISO-8601 Generic", parsed
                except Exception:
                    pass

        return None

    def _compute_timestamp_profile(
        self, col_name: str, fmt_name: str, ts_series: pl.Series
    ) -> TimestampProfile:
        """Compute time boundaries, duration, and sampling interval cadence."""
        valid_ts = ts_series.drop_nulls()
        if len(valid_ts) == 0:
            raise TimestampDetectionError(f"Timestamp column '{col_name}' contains only null values.")

        min_dt = valid_ts.min()
        max_dt = valid_ts.max()

        start_time_str = str(min_dt)
        end_time_str = str(max_dt)

        # Duration in hours
        duration_hours = 0.0
        if min_dt is not None and max_dt is not None:
            try:
                if hasattr(max_dt, "timestamp") and hasattr(min_dt, "timestamp"):
                    t_max = getattr(max_dt, "timestamp")()
                    t_min = getattr(min_dt, "timestamp")()
                    duration_hours = round(float(t_max - t_min) / 3600.0, 2)
            except Exception:
                pass

        # Cadence detection: sort unique timestamps and compute differences
        unique_sorted = valid_ts.unique().sort()
        median_interval = 0.0
        is_regular = False
        cadence_desc = "unknown"

        if len(unique_sorted) > 1:
            diffs_s = unique_sorted.diff().dt.total_seconds().drop_nulls()
            if len(diffs_s) > 0:
                raw_med = diffs_s.median()
                median_val = _to_float(raw_med, 0.0)
                median_interval = round(median_val, 1)

                # Check regularity: proportion of diffs within 5% of median
                if median_interval > 0:
                    tolerance = max(1.0, median_interval * 0.05)
                    regular_count = diffs_s.filter(
                        (diffs_s >= (median_interval - tolerance))
                        & (diffs_s <= (median_interval + tolerance))
                    ).len()
                    regularity_ratio = regular_count / len(diffs_s)
                    is_regular = regularity_ratio >= 0.85

                cadence_desc = self._format_cadence_description(median_interval)

        return TimestampProfile(
            column_name=col_name,
            detected_format=fmt_name,
            start_time=start_time_str,
            end_time=end_time_str,
            duration_hours=duration_hours,
            median_interval_seconds=median_interval,
            is_regular_cadence=is_regular,
            cadence_description=cadence_desc,
        )

    def _format_cadence_description(self, interval_seconds: float) -> str:
        """Format interval seconds into intuitive engineering strings."""
        if interval_seconds <= 0:
            return "irregular"
        if math.isclose(interval_seconds, 60.0, rel_tol=0.05):
            return "1m"
        if math.isclose(interval_seconds, 300.0, rel_tol=0.05):
            return "5m"
        if math.isclose(interval_seconds, 600.0, rel_tol=0.05):
            return "10m"
        if math.isclose(interval_seconds, 900.0, rel_tol=0.05):
            return "15m"
        if math.isclose(interval_seconds, 1800.0, rel_tol=0.05):
            return "30m"
        if math.isclose(interval_seconds, 3600.0, rel_tol=0.05):
            return "1h"
        if math.isclose(interval_seconds, 86400.0, rel_tol=0.05):
            return "1d"
        return f"{int(interval_seconds)}s"

    def _compute_column_statistics(
        self, df: pl.DataFrame, sparkline_points: int
    ) -> List[ColumnStatistic]:
        """Compute vectorized statistics and downsampled sparklines for every column."""
        stats: List[ColumnStatistic] = []
        total_rows = max(1, len(df))

        for col in df.columns:
            series = df[col]
            dtype_str = str(series.dtype)
            null_count = series.null_count()
            null_pct = round((null_count / total_rows) * 100.0, 2)
            distinct_count = series.n_unique()

            min_val: Optional[Union[float, int, str]] = None
            max_val: Optional[Union[float, int, str]] = None
            mean_val: Optional[float] = None
            median_val: Optional[float] = None
            std_val: Optional[float] = None
            sparkline: List[float] = []

            is_numeric = series.dtype.is_numeric()

            if is_numeric:
                non_nulls = series.drop_nulls()
                if len(non_nulls) > 0:
                    raw_min = non_nulls.min()
                    raw_max = non_nulls.max()
                    raw_mean = non_nulls.mean()
                    raw_median = non_nulls.median()
                    raw_std = non_nulls.std()

                    f_min = _to_optional_float(raw_min)
                    f_max = _to_optional_float(raw_max)
                    f_mean = _to_optional_float(raw_mean)
                    f_med = _to_optional_float(raw_median)
                    f_std = _to_optional_float(raw_std)

                    min_val = round(f_min, 4) if f_min is not None else None
                    max_val = round(f_max, 4) if f_max is not None else None
                    mean_val = round(f_mean, 4) if f_mean is not None else None
                    median_val = round(f_med, 4) if f_med is not None else None
                    std_val = round(f_std, 4) if f_std is not None else None

                    # Generate Downsampled Sparkline
                    sparkline = self._generate_sparkline(series, points=sparkline_points)
            elif series.dtype == pl.String:
                non_nulls = series.drop_nulls()
                if len(non_nulls) > 0:
                    min_val = str(non_nulls.min())
                    max_val = str(non_nulls.max())
            elif series.dtype.is_temporal():
                non_nulls = series.drop_nulls()
                if len(non_nulls) > 0:
                    min_val = str(non_nulls.min())
                    max_val = str(non_nulls.max())

            stats.append(
                ColumnStatistic(
                    name=col,
                    dtype=dtype_str,
                    null_count=null_count,
                    null_percentage=null_pct,
                    distinct_count=distinct_count,
                    min_value=min_val,
                    max_value=max_val,
                    mean=mean_val,
                    median=median_val,
                    std=std_val,
                    sparkline=sparkline,
                )
            )

        return stats

    def _generate_sparkline(self, series: pl.Series, points: int) -> List[float]:
        """Downsample numeric series into `points` representative values for UI mini-charts."""
        n_rows = len(series)
        if n_rows == 0 or points <= 0:
            return []

        # Target points cannot exceed total rows
        target_points = min(points, n_rows)

        # Cast to float and fill nulls with median or 0.0
        s_float = series.cast(pl.Float64)
        raw_med = s_float.drop_nulls().median()
        median_fill = _to_float(raw_med, 0.0)
        s_filled = s_float.fill_null(median_fill)

        temp_df = s_filled.to_frame("val")

        # Vectorized bucket aggregation
        downsampled = (
            temp_df.with_columns(
                bucket=(pl.int_range(0, n_rows) * target_points // n_rows)
            )
            .group_by("bucket")
            .agg(pl.col("val").mean())
            .sort("bucket")["val"]
            .round(3)
            .to_list()
        )

        # Sanitize any residual NaN or Inf values
        cleaned_points: List[float] = []
        for v in downsampled:
            if v is None or math.isnan(v) or math.isinf(v):
                cleaned_points.append(round(median_fill, 3))
            else:
                cleaned_points.append(float(v))

        return cleaned_points


# ---------------------------------------------------------------------------
# Asynchronous Public API
# ---------------------------------------------------------------------------


async def profile_file(
    file_path: Union[str, Path],
    sparkline_points: int = 50,
    timestamp_column: Optional[str] = None,
) -> FileProfileResult:
    """Asynchronously profile a telemetry file in a non-blocking background thread.

    Args:
        file_path: Absolute or relative path to CSV, Parquet, or Excel file.
        sparkline_points: Target resolution points for sparkline downsampling.
        timestamp_column: Optional explicit name of the timestamp column.

    Returns:
        FileProfileResult dataclass.
    """
    profiler = FileProfiler()
    return await asyncio.to_thread(
        profiler.profile,
        file_path=file_path,
        sparkline_points=sparkline_points,
        timestamp_column=timestamp_column,
    )


# ---------------------------------------------------------------------------
# CLI Command Entrypoint
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="file-profiler",
    help="PlantIQ Telemetry File Profiler CLI (Polars & DuckDB)",
    add_completion=False,
)
console = Console()


@app.command()
def main(
    file_path: str = typer.Argument(..., help="Path to telemetry file (CSV, Parquet, Excel)"),
    sparkline_points: int = typer.Option(
        50, "--sparklines", "-s", help="Number of sparkline points to generate"
    ),
    timestamp_col: Optional[str] = typer.Option(
        None, "--timestamp-col", "-t", help="Explicit timestamp column name override"
    ),
) -> None:
    """Inspect and profile a solar telemetry file."""
    profiler = FileProfiler()
    try:
        result = profiler.profile(
            file_path=file_path,
            sparkline_points=sparkline_points,
            timestamp_column=timestamp_col,
        )
    except ProfilerError as pe:
        console.print(f"[bold red]Profiling Error ({pe.__class__.__name__}):[/bold red] {pe.message}")
        raise typer.Exit(code=1)

    # 1. Summary Header
    summary_text = (
        f"[bold cyan]File:[/bold cyan] {result.file_name} ({result.file_format.upper()})\n"
        f"[bold]Path:[/bold] {result.file_path}\n"
        f"[bold]Size:[/bold] {result.file_size_bytes / 1024:.1f} KB | "
        f"[bold]Rows:[/bold] {result.row_count:,} | "
        f"[bold]Columns:[/bold] {result.column_count} | "
        f"[bold]Duration:[/bold] {result.profiling_duration_ms:.2f} ms"
    )
    if result.timestamp_profile:
        tp = result.timestamp_profile
        summary_text += (
            f"\n[bold green]Timestamp Column:[/bold green] '{tp.column_name}' ({tp.detected_format})\n"
            f"[bold]Range:[/bold] {tp.start_time} -> {tp.end_time} ({tp.duration_hours:.1f}h)\n"
            f"[bold]Cadence:[/bold] {tp.median_interval_seconds}s ({tp.cadence_description}) "
            f"| Regular: {'[green]Yes[/green]' if tp.is_regular_cadence else '[yellow]No[/yellow]'}"
        )
    else:
        summary_text += "\n[yellow]Timestamp Column: None detected[/yellow]"

    console.print(Panel.fit(summary_text, title="PlantIQ File Profile Summary", border_style="blue"))

    # 2. Columns Statistics Table
    stats_table = Table(title="Column Schema & Descriptive Statistics", border_style="cyan")
    stats_table.add_column("Column", style="bold white")
    stats_table.add_column("Dtype", style="magenta")
    stats_table.add_column("Nulls", style="yellow")
    stats_table.add_column("Distinct", style="cyan")
    stats_table.add_column("Min", style="green")
    stats_table.add_column("Max", style="green")
    stats_table.add_column("Mean", style="blue")
    stats_table.add_column("Median", style="blue")
    stats_table.add_column("Sparkline (pts)", style="dim white")

    for col in result.columns:
        null_desc = f"{col.null_count} ({col.null_percentage}%)"
        min_s = str(col.min_value) if col.min_value is not None else "-"
        max_s = str(col.max_value) if col.max_value is not None else "-"
        mean_s = f"{col.mean:.2f}" if col.mean is not None else "-"
        median_s = f"{col.median:.2f}" if col.median is not None else "-"
        spark_desc = f"{len(col.sparkline)} pts" if col.sparkline else "-"

        stats_table.add_row(
            col.name,
            col.dtype,
            null_desc,
            str(col.distinct_count),
            min_s,
            max_s,
            mean_s,
            median_s,
            spark_desc,
        )

    console.print(stats_table)


if __name__ == "__main__":
    app()
