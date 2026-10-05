from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    CanonicalSignal,
    Channel,
    File,
    IngestionJob,
    MappingTemplate,
    Plant,
    Reading,
)

CANONICAL_KEY_ALIAS_MAP = {
    "ac_power": "power_ac",
    "power_ac": "power_ac",
    "dc_power": "power_dc",
    "power_dc": "power_dc",
    "daily_energy": "energy_ac_daily",
    "energy_ac_daily": "energy_ac_daily",
    "daily_yield": "energy_ac_daily",
    "total_energy": "energy_ac_total",
    "energy_ac_total": "energy_ac_total",
    "total_yield": "energy_ac_total",
    "irradiance": "irradiance_poa",
    "irradiance_poa": "irradiance_poa",
    "module_temperature": "temperature_module",
    "ambient_temperature": "temperature_ambient",
    "temperature": "temperature_module",
    "wind_speed": "wind_speed",
    "wind_direction": "wind_direction",
    "voltage": "voltage",
    "current": "current",
}


def parse_template_mappings(
    mappings: Dict[str, Any],
    df_columns: Sequence[str],
) -> Tuple[str, str, Dict[str, str]]:
    """
    Parses mapping template JSON into:
    - timestamp_column: str
    - source_key_column: str
    - telemetry_mappings: Dict[str, str]  # CSV column name -> canonical_signal_key
    """
    col_to_signal: Dict[str, str] = {}
    signal_to_col: Dict[str, str] = {}

    for k, v in mappings.items():
        if isinstance(v, dict):
            # Format: { "CSV_COL": { "canonical_signal": "signal_key" } }
            csv_col = str(k)
            sig_key = str(v.get("canonical_signal", ""))
            if csv_col and sig_key:
                col_to_signal[csv_col] = sig_key
                signal_to_col[sig_key] = csv_col
        elif isinstance(v, str):
            # Could be { "CSV_COL": "signal_key" } OR { "signal_key": "CSV_COL" }
            if k in df_columns:
                col_to_signal[k] = v
                signal_to_col[v] = k
            elif v in df_columns:
                col_to_signal[v] = k
                signal_to_col[k] = v
            else:
                col_to_signal[k] = v
                signal_to_col[k] = v
                col_to_signal[v] = k
                signal_to_col[v] = k

    # 1. Resolve Timestamp Column
    timestamp_column: Optional[str] = None
    for ts_alias in ["timestamp", "date_time", "datetime", "time", "ts"]:
        if ts_alias in signal_to_col and signal_to_col[ts_alias] in df_columns:
            timestamp_column = signal_to_col[ts_alias]
            break

    if not timestamp_column:
        for col, sig in col_to_signal.items():
            if sig.lower() in ["timestamp", "date_time", "datetime", "time", "ts"] and col in df_columns:
                timestamp_column = col
                break

    if not timestamp_column:
        for col in df_columns:
            if col.lower() in ["date_time", "datetime", "timestamp", "time", "ts"]:
                timestamp_column = col
                break

    if not timestamp_column:
        raise ValueError("Mapping template does not contain a timestamp mapping")

    # 2. Resolve Source Key Column
    source_key_column: Optional[str] = None
    for sk_alias in ["source_key", "source_key_name", "source", "inverter_id", "device_id"]:
        if sk_alias in signal_to_col and signal_to_col[sk_alias] in df_columns:
            source_key_column = signal_to_col[sk_alias]
            break

    if not source_key_column:
        for col, sig in col_to_signal.items():
            if sig.lower() in ["source_key", "source_key_name", "source"] and col in df_columns:
                source_key_column = col
                break

    if not source_key_column:
        for col in df_columns:
            if col.upper() in ["SOURCE_KEY", "SOURCE_KEY_NAME", "INVERTER_ID", "DEVICE_ID", "SOURCE"]:
                source_key_column = col
                break

    if not source_key_column:
        raise ValueError("Mapping template does not contain a source_key mapping")

    # 3. Resolve Telemetry Signals
    telemetry_mappings: Dict[str, str] = {}
    ignored_cols = {
        "plant_id", "plant_id (global ref)", "plant_ref", "plant", "plant_id",
        "date_time", "timestamp", "datetime", "source_key", "source_key (asset inverter)",
        "device_id", "inverter_id", "source"
    }
    for col, sig in col_to_signal.items():
        if col in df_columns and col != timestamp_column and col != source_key_column:
            if col.lower() in ignored_cols or str(sig).lower() in ignored_cols:
                continue
            telemetry_mappings[col] = sig

    return timestamp_column, source_key_column, telemetry_mappings


def get_or_create_channel(
    db: Session,
    asset_id: UUID,
    canonical_key: str,
    source_name: str,
) -> Channel:
    normalized_key = CANONICAL_KEY_ALIAS_MAP.get(canonical_key.lower(), canonical_key)

    cs = db.get(CanonicalSignal, normalized_key)
    target_key = normalized_key if cs is not None else "power_ac"

    channel = db.execute(
        select(Channel).where(
            Channel.asset_id == asset_id,
            Channel.canonical_key == target_key,
            Channel.source_name == source_name,
        )
    ).scalars().first()

    if channel is None:
        unit = cs.unit if cs is not None else None

        channel = Channel(
            asset_id=asset_id,
            canonical_key=target_key,
            source_name=source_name,
            receive_unit=unit,
            interval_s=300,
            agg_semantics="avg",
        )
        db.add(channel)
        db.flush()

    return channel


def process_ingestion_job(
    db: Session,
    job_id: UUID,
) -> IngestionJob:
    job = db.get(IngestionJob, job_id)

    if job is None:
        raise ValueError("Ingestion job not found")

    if job.status in ("done", "completed"):
        return job

    # Transition status to profiling
    job.status = "profiling"
    job.started_at = datetime.now(timezone.utc)
    job.error = None
    job.qc_summary = {}
    db.commit()

    try:
        file_record = db.get(File, job.file_id)
        if file_record is None:
            raise ValueError("File not found")

        template = db.get(MappingTemplate, job.template_id)
        if template is None:
            raise ValueError("Mapping template not found")

        file_path = Path(file_record.path)
        if not file_path.exists():
            backend_root = Path(__file__).resolve().parents[2]
            file_path = backend_root / file_record.path

        if not file_path.exists():
            project_root = Path(__file__).resolve().parents[3]
            fname = Path(file_record.path).name
            if (project_root / "datasets" / fname).exists():
                file_path = project_root / "datasets" / fname
            elif (backend_root / "datasets" / fname).exists():
                file_path = backend_root / "datasets" / fname

        if not file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_record.path}")

        df = pd.read_csv(file_path)
        if df.empty:
            raise ValueError("CSV file contains no rows")

        timestamp_column, source_key_column, telemetry_mappings = parse_template_mappings(
            template.mappings or {}, list(df.columns)
        )

        # Transition status to ingesting
        job.status = "ingesting"
        db.commit()

        df[timestamp_column] = pd.to_datetime(
            df[timestamp_column],
            dayfirst=True,
            errors="coerce",
        )

        df[source_key_column] = (
            df[source_key_column]
            .astype("string")
            .str.strip()
        )

        for col in telemetry_mappings.keys():
            df[col] = pd.to_numeric(df[col], errors="coerce")

        valid_df = df[
            df[timestamp_column].notna() & df[source_key_column].notna()
        ].copy()

        if valid_df.empty:
            raise ValueError("No valid timestamp and source_key rows found in CSV")

        # Resolve Assets strictly for target organization
        plants = db.execute(
            select(Plant).where(Plant.org_id == template.org_id)
        ).scalars().all()

        if not plants:
            # Create plant for template.org_id if none exists
            from datetime import date
            target_plant = Plant(
                org_id=template.org_id,
                name="Surya Solar Farm - 50MW",
                plant_type="solar",
                capacity_dc_kwp=28280.55,
                capacity_ac_kw=27500.0,
                latitude=27.5398,
                longitude=71.9161,
                timezone="Asia/Kolkata",
                tariff_inr_per_kwh=3.5,
                expected_pr=0.78,
                cod_date=date(2019, 3, 31),
                metadata_={
                    "site": "Bhadla Solar Park, Rajasthan",
                    "country": "India",
                    "inverter_count": 22,
                },
            )
            db.add(target_plant)
            db.flush()
            plants = [target_plant]

        plant_ids = [p.id for p in plants]

        assets = db.execute(
            select(Asset).where(Asset.plant_id.in_(plant_ids))
        ).scalars().all() if plant_ids else []

        asset_by_source_key: Dict[str, Asset] = {}
        for asset in assets:
            metadata = asset.metadata_ or {}
            sk = metadata.get("source_key")
            if sk:
                asset_by_source_key[str(sk)] = asset
            if asset.name:
                asset_by_source_key[str(asset.name)] = asset
                if str(asset.name).startswith("Inverter "):
                    trimmed = str(asset.name).replace("Inverter ", "").strip()
                    asset_by_source_key[trimmed] = asset

        unique_source_keys = [str(sk) for sk in valid_df[source_key_column].unique() if pd.notna(sk)]

        if plants:
            target_plant = plants[0]
            for sk in unique_source_keys:
                if sk not in asset_by_source_key:
                    name = f"Inverter {sk}"
                    existing_by_name = db.execute(
                        select(Asset).where(
                            Asset.plant_id == target_plant.id,
                            Asset.name == name,
                        )
                    ).scalars().first()

                    if existing_by_name:
                        meta = dict(existing_by_name.metadata_ or {})
                        meta["source_key"] = sk
                        existing_by_name.metadata_ = meta
                        asset_by_source_key[sk] = existing_by_name
                    else:
                        unassigned_asset = None
                        for a in assets:
                            a_sk = (a.metadata_ or {}).get("source_key")
                            if not a_sk and a.id not in [mapped_a.id for mapped_a in asset_by_source_key.values()]:
                                unassigned_asset = a
                                break

                        if unassigned_asset:
                            meta = dict(unassigned_asset.metadata_ or {})
                            meta["source_key"] = sk
                            unassigned_asset.metadata_ = meta
                            asset_by_source_key[sk] = unassigned_asset
                        else:
                            new_asset = Asset(
                                plant_id=target_plant.id,
                                name=name,
                                asset_type="inverter",
                                metadata_={"source_key": sk, "source": "csv_ingestion"},
                            )
                            db.add(new_asset)
                            db.flush()
                            assets.append(new_asset)
                            asset_by_source_key[sk] = new_asset

        # Pre-create / cache channels for all mapped columns across assets
        channel_cache: Dict[Tuple[UUID, str], Channel] = {}
        for asset in asset_by_source_key.values():
            for col, sig_key in telemetry_mappings.items():
                cache_k = (asset.id, col)
                if cache_k not in channel_cache:
                    channel_cache[cache_k] = get_or_create_channel(db, asset.id, sig_key, col)

        dialect_name = db.bind.dialect.name
        if dialect_name == "postgresql":
            upsert_sql = text("""
                INSERT INTO readings (channel_id, ts, value, quality, ingestion_job_id)
                VALUES (:channel_id, :ts, :value, :quality, :ingestion_job_id)
                ON CONFLICT (channel_id, ts) DO UPDATE SET
                    value = EXCLUDED.value,
                    quality = EXCLUDED.quality,
                    ingestion_job_id = EXCLUDED.ingestion_job_id
            """)
        else:
            upsert_sql = text("""
                INSERT INTO readings (channel_id, ts, value, quality, ingestion_job_id)
                VALUES (:channel_id, :ts, :value, :quality, :ingestion_job_id)
                ON CONFLICT (channel_id, ts) DO UPDATE SET
                    value = excluded.value,
                    quality = excluded.quality,
                    ingestion_job_id = excluded.ingestion_job_id
            """)

        total_rows = len(valid_df)
        inserted = 0
        skipped = 0
        rows_processed = 0
        min_time = None
        max_time = None

        readings_batch: List[Dict[str, Any]] = []

        for row in valid_df.itertuples(index=False):
            row_dict = row._asdict()
            rows_processed += 1

            raw_ts = row_dict[timestamp_column]
            sk_val = str(row_dict[source_key_column]).strip()

            asset = asset_by_source_key.get(sk_val)
            if asset is None:
                skipped += 1
                continue

            if isinstance(raw_ts, pd.Timestamp):
                ts_dt = raw_ts.to_pydatetime()
            else:
                ts_dt = raw_ts

            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=timezone.utc)

            if min_time is None or ts_dt < min_time:
                min_time = ts_dt
            if max_time is None or ts_dt > max_time:
                max_time = ts_dt

            for col in telemetry_mappings.keys():
                raw_val = row_dict.get(col)
                if raw_val is None or pd.isna(raw_val):
                    continue

                try:
                    val = float(raw_val)
                except (ValueError, TypeError):
                    continue

                ch = channel_cache.get((asset.id, col))
                if not ch:
                    continue

                inserted += 1
                readings_batch.append({
                    "channel_id": str(ch.id),
                    "ts": ts_dt,
                    "value": val,
                    "quality": 0,
                    "ingestion_job_id": str(job_id),
                })

                if len(readings_batch) >= 5000:
                    db.execute(upsert_sql, readings_batch)
                    readings_batch.clear()

            # Periodically update real-time progress for frontend polling
            if rows_processed % 10000 == 0:
                job.qc_summary = {
                    "progress": round(rows_processed / total_rows, 2),
                    "rows_processed": rows_processed,
                    "rows_total": total_rows,
                    "readings_inserted": inserted,
                    "assets_created": len(asset_by_source_key),
                    "channels_created": len(channel_cache),
                }
                db.commit()

        if readings_batch:
            db.execute(upsert_sql, readings_batch)
            readings_batch.clear()

        # Commit readings batch
        db.commit()

        channel_ids = [c.id for c in channel_cache.values()]
        verified_reading_count = db.scalar(
            select(func.count(Reading.ts)).where(Reading.channel_id.in_(channel_ids))
        ) or 0

        if verified_reading_count == 0 and inserted > 0:
            raise ValueError(f"Post-commit database verification failed: expected {inserted} readings, but database returned 0.")

        job.status = "done"
        job.rows_total = len(df)
        job.time_min = min_time
        job.time_max = max_time
        job.qc_summary = {
            "progress": 1.0,
            "rows_processed": rows_processed,
            "rows_total": len(df),
            "rows_valid": len(valid_df),
            "rows_inserted": verified_reading_count,
            "readings_inserted": verified_reading_count,
            "rows_skipped": skipped,
            "assets_created": len(asset_by_source_key),
            "channels_created": len(channel_cache),
            "unique_source_keys": len(unique_source_keys),
            "telemetry_columns": list(telemetry_mappings.keys()),
            "verified_in_db": True,
        }
        job.finished_at = datetime.now(timezone.utc)
        job.error = None

        db.commit()
        db.refresh(job)

        return job

    except Exception as exc:
        db.rollback()
        job = db.get(IngestionJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(job)
        raise exc
