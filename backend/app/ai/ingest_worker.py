"""High-Performance Ingestion Worker & Quality Control (QC) Pipeline.

Task: S2-AI-03
Implements:
- Vectorized Unit Conversion transforming source metrics into canonical base units.
- Vectorized Polars QC Bitmask Engine evaluating:
    * GAP (Missing timestamp intervals > 1.5x expected cadence)
    * FLATLINE (Sensor stuck at identical non-zero values across consecutive intervals)
    * RANGE (Physical or dynamic nameplate capacity boundary violations)
    * SPIKE (Instantaneous gradient jumps exceeding realistic physical limits)
- High-Speed Bulk Upsert into database (`observations` table) with conflict resolution.
- Asynchronous non-blocking APIs (`ingest_file`, `ingest_dataframe`, `ingest_records`).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import IntFlag
from pathlib import Path
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import polars as pl
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

# Ensure project root in sys.path
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.core.units import convert
from app.db.session import create_db_engine, get_session_factory, init_db
from app.models.base import generate_uuid
from app.models.entities import Channel, Reading


# ---------------------------------------------------------------------------
# QC Bitmask Definitions
# ---------------------------------------------------------------------------


class QCFlag(IntFlag):
    """Quality Control bitmask flags for telemetry anomaly categorization."""

    CLEAN = 0          # 0b00000000 (0) - Sensor reading is clean; no anomalies detected.
    GAP = 1 << 0       # 0b00000001 (1) - Timestamp gap exceeds expected sampling cadence.
    FLATLINE = 1 << 1  # 0b00000010 (2) - Sensor stuck reporting identical non-zero values.
    RANGE = 1 << 2     # 0b00000100 (4) - Reading violates physical or nameplate bounds.
    SPIKE = 1 << 3     # 0b00001000 (8) - Instantaneous gradient jump beyond physical limit.

    @classmethod
    def to_labels(cls, flag_value: int) -> List[str]:
        """Convert bitmask integer to list of human-readable anomaly labels."""
        if flag_value == 0:
            return ["CLEAN"]
        labels: List[str] = []
        if flag_value & cls.GAP:
            labels.append("GAP")
        if flag_value & cls.FLATLINE:
            labels.append("FLATLINE")
        if flag_value & cls.RANGE:
            labels.append("RANGE")
        if flag_value & cls.SPIKE:
            labels.append("SPIKE")
        return labels

    @classmethod
    def has_flag(cls, flag_value: int, target_flag: QCFlag) -> bool:
        """Check if a specific flag is set in the bitmask."""
        if target_flag == cls.CLEAN:
            return flag_value == 0
        return bool(flag_value & target_flag)


# ---------------------------------------------------------------------------
# Configuration & Mapping Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelMappingConfig:
    """Configuration mapping a raw column to a target channel and canonical signal."""

    raw_column: str
    canonical_key: str
    source_unit: str = ""
    target_unit: str = ""
    min_bound: Optional[float] = None
    max_bound: Optional[float] = None
    max_gradient: Optional[float] = None
    scale_factor: float = 1.0
    channel_id: Optional[str] = None


@dataclass
class IngestConfig:
    """Ingestion pipeline runtime parameters and anomaly detection thresholds."""

    cadence_seconds: int = 900  # Default: 15-minute standard solar interval (900s)
    gap_tolerance_factor: float = 1.5  # Gap flagged if delta > cadence * 1.5 (e.g. > 1350s)
    flatline_min_steps: int = 4  # Flag if >= 4 identical consecutive non-zero intervals (1 hour)
    flatline_min_value_threshold: float = 1.0  # Ignore zeros (nighttime 0W / 0 W/mÂ² is normal)
    batch_size: int = 5000  # Database chunk size for batch upsert
    device_ratings_dc: Dict[str, float] = field(default_factory=dict)  # device_id -> rated_dc_w
    device_ratings_ac: Dict[str, float] = field(default_factory=dict)  # device_id -> rated_ac_w


@dataclass(frozen=True)
class IngestResult:
    """Execution summary and throughput metrics returned by IngestWorker."""

    total_rows_processed: int
    observations_created: int
    channels_count: int
    duration_ms: float
    throughput_rows_per_sec: float
    clean_count: int
    gap_count: int
    flatline_count: int
    range_count: int
    spike_count: int
    anomalies_total: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to JSON-serializable dictionary."""
        return asdict(self)


# Default Canonical Bounds for Standard Solar Telemetry
DEFAULT_CANONICAL_BOUNDS: Dict[str, Tuple[float, float, float]] = {
    # canonical_key: (min_bound, static_max_bound, max_gradient_per_step)
    "power_dc": (0.0, 2000000.0, 1500000.0),      # Up to 2.0 MW per central inverter
    "power_ac": (0.0, 1500000.0, 1300000.0),      # Up to 1.5 MW per central inverter
    "energy_ac_daily": (0.0, 30000000.0, 2000000.0),  # Up to 30 MWh daily
    "energy_ac_total": (0.0, 1e12, 5000000.0),
    "irradiance_poa": (0.0, 1500.0, 1200.0),      # Max 1500 W/mÂ² (POA with cloud-enhancement)
    "irradiance_ghi": (0.0, 1361.0, 1100.0),      # Max solar constant
    "temperature_ambient": (-30.0, 60.0, 15.0),   # -30Â°C to 60Â°C; max 15Â°C jump in 15 mins
    "temperature_module": (-20.0, 90.0, 25.0),    # -20Â°C to 90Â°C; max 25Â°C jump in 15 mins
    "voltage_dc": (0.0, 1500.0, 500.0),
    "current_dc": (0.0, 3000.0, 1000.0),
    "voltage_ac": (0.0, 1000.0, 200.0),
    "current_ac": (0.0, 2500.0, 800.0),
    "frequency_grid": (45.0, 65.0, 5.0),
    "wind_speed": (0.0, 50.0, 20.0),
}


# ---------------------------------------------------------------------------
# Vectorized QC Bitmask Engine (Polars)
# ---------------------------------------------------------------------------


def evaluate_qc_series(
    timestamps: pl.Series,
    values: pl.Series,
    canonical_key: str,
    config: IngestConfig,
    device_id: Optional[str] = None,
    custom_min: Optional[float] = None,
    custom_max: Optional[float] = None,
    custom_gradient: Optional[float] = None,
) -> pl.Series:
    """Vectorized evaluation of QC anomaly bitmask over a chronologically sorted series.

    Computes:
    - GAP: delta > cadence * tolerance_factor
    - FLATLINE: value == shift(1) == shift(2) == shift(3) for value > threshold
    - RANGE: value < min_bound or value > max_bound (using dynamic rated capacities when available)
    - SPIKE: |value - shift(1)| > max_gradient
    """
    n = len(values)
    if n == 0:
        return pl.Series("qc_flag", [], dtype=pl.Int32)

    # 1. GAP Evaluation
    max_gap_seconds = config.cadence_seconds * config.gap_tolerance_factor
    # Compute timestamp differences in seconds
    time_diff_s = timestamps.diff().dt.total_seconds()
    is_gap = (time_diff_s > max_gap_seconds).fill_null(False)

    # 2. FLATLINE Evaluation
    # Sensor repeating identical value for config.flatline_min_steps (e.g. 4 steps)
    min_val_thresh = config.flatline_min_value_threshold
    k = max(2, config.flatline_min_steps)

    # Polars vectorized condition: value equals lag(1)..lag(k-1) and exceeds min_val_thresh
    is_flatline = (values > min_val_thresh).fill_null(False)
    for shift_i in range(1, k):
        is_flatline = is_flatline & (values == values.shift(shift_i)).fill_null(False)

    # 3. RANGE Evaluation
    # Determine bounds
    default_bounds = DEFAULT_CANONICAL_BOUNDS.get(canonical_key, (-1e9, 1e9, 1e9))
    min_b = custom_min if custom_min is not None else default_bounds[0]
    max_b = custom_max if custom_max is not None else default_bounds[1]

    # Apply dynamic capacity bounds if device rating is registered
    if device_id:
        if canonical_key == "power_dc" and device_id in config.device_ratings_dc:
            max_b = 1.20 * config.device_ratings_dc[device_id]
        elif canonical_key == "power_ac" and device_id in config.device_ratings_ac:
            max_b = 1.10 * config.device_ratings_ac[device_id]
        elif canonical_key == "energy_ac_daily" and device_id in config.device_ratings_ac:
            max_b = 24.0 * config.device_ratings_ac[device_id]

    is_range = (values < min_b) | (values > max_b)
    # Null values are considered range/validity anomalies
    is_range = is_range.fill_null(True)

    # 4. SPIKE Evaluation
    max_grad = custom_gradient if custom_gradient is not None else default_bounds[2]
    val_diff = (values - values.shift(1)).abs()
    is_spike = (val_diff > max_grad).fill_null(False)

    # 5. Composite Bitmask Formulation
    qc_mask = (
        (is_gap.cast(pl.Int32) * int(QCFlag.GAP))
        | (is_flatline.cast(pl.Int32) * int(QCFlag.FLATLINE))
        | (is_range.cast(pl.Int32) * int(QCFlag.RANGE))
        | (is_spike.cast(pl.Int32) * int(QCFlag.SPIKE))
    ).alias("qc_flag")

    return qc_mask


# ---------------------------------------------------------------------------
# High-Throughput Ingestion Worker
# ---------------------------------------------------------------------------


class IngestWorker:
    """High-performance data ingestion worker for PlantIQ telemetry."""

    def __init__(
        self,
        engine: Optional[Engine] = None,
        config: Optional[IngestConfig] = None,
    ) -> None:
        """Initialize IngestWorker with target database engine and QC config."""
        self.engine = engine or create_db_engine()
        self.config = config or IngestConfig()
        self.session_factory = get_session_factory(self.engine)
        # Ensure database tables exist
        init_db(self.engine)
        # In-memory channel registry cache: (asset_id, canonical_key) -> channel_id
        self._channel_cache: Dict[Tuple[str, str], str] = {}
        self._sqlite_lock = threading.Lock()
        self._channel_lock = threading.Lock()
        self._refresh_channel_cache()

    def _refresh_channel_cache(self) -> None:
        """Load configured channels from database to avoid per-row queries."""
        try:
            with self.session_factory() as session:
                channels = session.query(Channel).all()
                for ch in channels:
                    self._channel_cache[(ch.asset_id, ch.canonical_signal_key)] = ch.id
                    # Also map source_name if unique
                    self._channel_cache[(ch.source_name, ch.canonical_signal_key)] = ch.id
        except Exception:
            # In unit test or standalone mode where DB may not be seeded, cache starts empty
            pass

    def get_or_create_channel(
        self,
        asset_id: str,
        canonical_key: str,
        source_name: str,
        source_unit: str,
        interval_s: int = 900,
        aggregation_method: str = "avg",
    ) -> str:
        """Lookup cached channel_id or persist a new Channel row."""
        cache_key = (str(asset_id), canonical_key)
        if cache_key in self._channel_cache:
            return self._channel_cache[cache_key]

        import uuid as _uuid_mod
        if isinstance(asset_id, _uuid_mod.UUID):
            asset_uuid = asset_id
        else:
            try:
                asset_uuid = _uuid_mod.UUID(str(asset_id))
            except ValueError:
                asset_uuid = _uuid_mod.uuid5(_uuid_mod.NAMESPACE_DNS, str(asset_id))

        with self._channel_lock:
            if cache_key in self._channel_cache:
                return self._channel_cache[cache_key]

            with self.session_factory() as session:
                # Check existing in DB
                existing = (
                    session.query(Channel)
                    .filter(
                        Channel.asset_id == asset_uuid,
                        Channel.canonical_key == canonical_key,
                    )
                    .first()
                )
                if existing:
                    str_id = str(existing.id)
                    self._channel_cache[cache_key] = str_id
                    return str_id

                # Create new channel
                new_id = generate_uuid()
                new_channel = Channel(
                    id=new_id,
                    asset_id=asset_uuid,
                    canonical_key=canonical_key,
                    source_name=source_name,
                    receive_unit=source_unit,
                    interval_s=interval_s,
                    agg_semantics=aggregation_method,
                )
                session.add(new_channel)
                session.commit()
                str_id = str(new_id)
                self._channel_cache[cache_key] = str_id
                return str_id

    # -----------------------------------------------------------------------
    # Ingestion Core Pipeline
    # -----------------------------------------------------------------------

    def process_telemetry_dataframe(
        self,
        df: pl.DataFrame,
        timestamp_col: str,
        mappings: Sequence[ChannelMappingConfig],
        device_col: Optional[str] = None,
        default_asset_id: str = "DEFAULT_ASSET",
    ) -> pl.DataFrame:
        """Transform raw DataFrame through unit conversion and vectorized QC evaluation.

        Returns normalized narrow DataFrame:
        [channel_id, timestamp, value, raw_value, qc_flag]
        """
        if df.is_empty():
            return pl.DataFrame(
                schema={
                    "channel_id": pl.String,
                    "timestamp": pl.Datetime("us", "UTC"),
                    "value": pl.Float64,
                    "raw_value": pl.Float64,
                    "qc_flag": pl.Int32,
                }
            )

        # 1. Parse Timestamps to UTC Datetime
        ts_series = df[timestamp_col]
        if ts_series.dtype == pl.String:
            # Try ISO standard first, fallback to day-first
            try:
                parsed_ts = ts_series.str.to_datetime(
                    format="%Y-%m-%d %H:%M:%S", time_zone="UTC", strict=False
                )
                if parsed_ts.null_count() > len(df) * 0.5:
                    parsed_ts = ts_series.str.to_datetime(
                        format="%d-%m-%Y %H:%M", time_zone="UTC", strict=False
                    )
            except Exception:
                parsed_ts = ts_series.str.to_datetime(time_zone="UTC", strict=False)
        elif ts_series.dtype.is_temporal():
            parsed_ts = ts_series.dt.replace_time_zone("UTC")
        else:
            raise ValueError(f"Unsupported timestamp column dtype: {ts_series.dtype}")

        df = df.with_columns(parsed_ts.alias("_parsed_timestamp"))

        # 2. Partition by Device for independent chronological QC windowing
        if device_col and device_col in df.columns:
            device_parts = df.partition_by(device_col, as_dict=True)
            device_items = [
                (str(k[0] if isinstance(k, tuple) else k), part.sort("_parsed_timestamp"))
                for k, part in device_parts.items()
            ]
        else:
            device_items = [(default_asset_id, df.sort("_parsed_timestamp"))]

        # 3. Process Each Configured Channel Mapping
        observations_frames: List[pl.DataFrame] = []

        for asset_id, dev_df in device_items:
            dev_ts = dev_df["_parsed_timestamp"]
            for mapping in mappings:
                if mapping.raw_column not in dev_df.columns:
                    continue

                raw_series = dev_df[mapping.raw_column].cast(pl.Float64, strict=False)
                scaled_series = (
                    raw_series * mapping.scale_factor
                    if mapping.scale_factor != 1.0
                    else raw_series
                )

                # Unit Conversion via units.py
                target_unit = mapping.target_unit or self._infer_target_unit(mapping.canonical_key)
                if mapping.source_unit and target_unit and mapping.source_unit != target_unit:
                    try:
                        converted_val = convert(scaled_series, mapping.source_unit, target_unit)
                    except Exception:
                        converted_val = scaled_series
                else:
                    converted_val = scaled_series

                if len(converted_val) == 0:
                    continue

                # Run Vectorized QC Bitmask Engine
                qc_series = evaluate_qc_series(
                    timestamps=dev_ts,
                    values=converted_val,
                    canonical_key=mapping.canonical_key,
                    config=self.config,
                    device_id=asset_id,
                    custom_min=mapping.min_bound,
                    custom_max=mapping.max_bound,
                    custom_gradient=mapping.max_gradient,
                )

                # Resolve channel_id
                channel_id = mapping.channel_id or self.get_or_create_channel(
                    asset_id=asset_id,
                    canonical_key=mapping.canonical_key,
                    source_name=mapping.raw_column,
                    source_unit=mapping.source_unit,
                    interval_s=self.config.cadence_seconds,
                )

                obs_frame = pl.DataFrame({
                    "channel_id": pl.Series("channel_id", [channel_id] * len(converted_val), dtype=pl.String),
                    "timestamp": dev_ts,
                    "value": converted_val,
                    "raw_value": raw_series,
                    "qc_flag": qc_series,
                })
                observations_frames.append(obs_frame)

        if not observations_frames:
            return pl.DataFrame(
                schema={
                    "channel_id": pl.String,
                    "timestamp": pl.Datetime("us", "UTC"),
                    "value": pl.Float64,
                    "raw_value": pl.Float64,
                    "qc_flag": pl.Int32,
                }
            )

        return pl.concat(observations_frames)

    def _infer_target_unit(self, canonical_key: str) -> str:
        """Infer canonical base engineering unit for a given canonical signal."""
        units_map = {
            "power_ac": "W",
            "power_dc": "W",
            "energy_ac_daily": "Wh",
            "energy_ac_total": "Wh",
            "irradiance_poa": "W/mÂ²",
            "irradiance_ghi": "W/mÂ²",
            "temperature_ambient": "degC",
            "temperature_module": "degC",
            "voltage_dc": "V",
            "current_dc": "A",
            "voltage_ac": "V",
            "current_ac": "A",
            "frequency_grid": "Hz",
            "wind_speed": "m/s",
        }
        return units_map.get(canonical_key, "")

    # -----------------------------------------------------------------------
    # Database Bulk Upsert
    # -----------------------------------------------------------------------

    def bulk_upsert_observations(
        self,
        observations_df: pl.DataFrame,
    ) -> int:
        """Execute high-speed bulk upsert of observations into the database.

        Utilizes direct DBAPI cursor executemany in batched chunks with conflict resolution on (channel_id, timestamp).
        """
        if observations_df.is_empty():
            return 0

        total_rows = len(observations_df)
        chunk_size = self.config.batch_size
        dialect_name = self.engine.dialect.name
        now_str = datetime.now(timezone.utc).isoformat()

        # Format narrow DataFrame with all columns ready for cursor.executemany
        formatted_df = observations_df.with_columns([
            observations_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S+00:00").alias("ts"),
            observations_df["qc_flag"].cast(pl.Int32).alias("quality"),
            pl.lit(None, dtype=pl.String).alias("ingestion_job_id"),
        ]).select(["channel_id", "ts", "value", "quality", "ingestion_job_id"])

        # Prepare SQL statement based on dialect (PostgreSQL vs SQLite)
        if dialect_name == "postgresql":
            raw_sql = """
                INSERT INTO readings (channel_id, ts, value, quality, ingestion_job_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (channel_id, ts) DO UPDATE SET
                    value = EXCLUDED.value,
                    quality = EXCLUDED.quality,
                    ingestion_job_id = EXCLUDED.ingestion_job_id
            """
        else:
            raw_sql = """
                INSERT INTO readings (channel_id, ts, value, quality, ingestion_job_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (channel_id, ts) DO UPDATE SET
                    value = excluded.value,
                    quality = excluded.quality,
                    ingestion_job_id = excluded.ingestion_job_id
            """

        written_count = 0

        def _execute_write() -> int:
            nonlocal written_count
            with self.engine.begin() as conn:
                if dialect_name == "sqlite":
                    try:
                        conn.execute(text("PRAGMA synchronous = OFF;"))
                        conn.execute(text("PRAGMA journal_mode = MEMORY;"))
                    except Exception:
                        pass

                cursor = getattr(conn.connection, "cursor", None)
                if cursor is not None:
                    db_cursor = cursor()
                    for offset in range(0, total_rows, chunk_size):
                        chunk_slice = formatted_df.slice(offset, chunk_size)
                        db_cursor.executemany(raw_sql, chunk_slice.iter_rows())
                        written_count += len(chunk_slice)
                else:
                    sa_sql = text("""
                        INSERT INTO readings (channel_id, ts, value, quality, ingestion_job_id)
                        VALUES (:channel_id, :ts, :value, :quality, :ingestion_job_id)
                        ON CONFLICT (channel_id, ts) DO UPDATE SET
                            value = excluded.value,
                            quality = excluded.quality,
                            ingestion_job_id = excluded.ingestion_job_id
                    """)
                    for offset in range(0, total_rows, chunk_size):
                        chunk_slice = formatted_df.slice(offset, chunk_size)
                        records = chunk_slice.to_dicts()
                        conn.execute(sa_sql, records)
                        written_count += len(records)
            return written_count

        if dialect_name == "sqlite":
            with self._sqlite_lock:
                return _execute_write()
        return _execute_write()

    # -----------------------------------------------------------------------
    # Public Ingestion APIs (Sync & Async)
    # -----------------------------------------------------------------------

    def ingest_dataframe(
        self,
        df: pl.DataFrame,
        timestamp_col: str,
        mappings: Sequence[ChannelMappingConfig],
        device_col: Optional[str] = None,
        default_asset_id: str = "DEFAULT_ASSET",
    ) -> IngestResult:
        """Synchronously ingest, convert, QC-flag, and persist a Polars DataFrame."""
        start_time = time.perf_counter()
        raw_rows = len(df)

        # 1. Process transformations and QC flags
        obs_df = self.process_telemetry_dataframe(
            df=df,
            timestamp_col=timestamp_col,
            mappings=mappings,
            device_col=device_col,
            default_asset_id=default_asset_id,
        )

        # 2. Persist to Database
        written_count = self.bulk_upsert_observations(obs_df)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # 3. Compute Aggregate QC Metrics
        if not obs_df.is_empty():
            qc_series = obs_df["qc_flag"]
            gap_count = int((qc_series & int(QCFlag.GAP) > 0).sum())
            flatline_count = int((qc_series & int(QCFlag.FLATLINE) > 0).sum())
            range_count = int((qc_series & int(QCFlag.RANGE) > 0).sum())
            spike_count = int((qc_series & int(QCFlag.SPIKE) > 0).sum())
            clean_count = int((qc_series == int(QCFlag.CLEAN)).sum())
            anomalies_total = written_count - clean_count
            channels_count = obs_df["channel_id"].n_unique()
        else:
            gap_count = flatline_count = range_count = spike_count = clean_count = anomalies_total = channels_count = 0

        throughput = (raw_rows / (duration_ms / 1000.0)) if duration_ms > 0 else 0.0

        return IngestResult(
            total_rows_processed=raw_rows,
            observations_created=written_count,
            channels_count=channels_count,
            duration_ms=round(duration_ms, 2),
            throughput_rows_per_sec=round(throughput, 1),
            clean_count=clean_count,
            gap_count=gap_count,
            flatline_count=flatline_count,
            range_count=range_count,
            spike_count=spike_count,
            anomalies_total=anomalies_total,
        )

    async def ingest_dataframe_async(
        self,
        df: pl.DataFrame,
        timestamp_col: str,
        mappings: Sequence[ChannelMappingConfig],
        device_col: Optional[str] = None,
        default_asset_id: str = "DEFAULT_ASSET",
    ) -> IngestResult:
        """Asynchronously ingest a Polars DataFrame without blocking the event loop."""
        return await asyncio.to_thread(
            self.ingest_dataframe,
            df=df,
            timestamp_col=timestamp_col,
            mappings=mappings,
            device_col=device_col,
            default_asset_id=default_asset_id,
        )

    def ingest_file(
        self,
        file_path: Union[str, Path],
        timestamp_col: str,
        mappings: Sequence[ChannelMappingConfig],
        device_col: Optional[str] = None,
        default_asset_id: str = "DEFAULT_ASSET",
    ) -> IngestResult:
        """Ingest a CSV or Parquet file synchronously."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if path.suffix.lower() == ".csv":
            df = pl.read_csv(path, infer_schema_length=10000)
        elif path.suffix.lower() in (".parquet", ".pq"):
            df = pl.read_parquet(path)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")

        return self.ingest_dataframe(
            df=df,
            timestamp_col=timestamp_col,
            mappings=mappings,
            device_col=device_col,
            default_asset_id=default_asset_id,
        )

    async def ingest_file_async(
        self,
        file_path: Union[str, Path],
        timestamp_col: str,
        mappings: Sequence[ChannelMappingConfig],
        device_col: Optional[str] = None,
        default_asset_id: str = "DEFAULT_ASSET",
    ) -> IngestResult:
        """Asynchronously ingest a file without blocking the event loop."""
        return await asyncio.to_thread(
            self.ingest_file,
            file_path=file_path,
            timestamp_col=timestamp_col,
            mappings=mappings,
            device_col=device_col,
            default_asset_id=default_asset_id,
        )

