"""Idempotent remediation script to attach WS-01 weather station and ingest POA readings.

Target plant: d253760d-d8ad-4a18-b655-fc22a5222d59
Source: datasets/Plant_1_Weather_Sensor_Data.csv
"""

from datetime import datetime, timezone
import csv
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import create_db_engine, get_session_factory
from app.models.entities import Asset, Channel, Plant, Reading


TARGET_PLANT_ID = UUID("d253760d-d8ad-4a18-b655-fc22a5222d59")
KAGGLE_P1_WEATHER_SOURCE_KEY = "HmiyD2TTLFNqkNe"


def remediate_poa_data(plant_id: Optional[UUID] = None) -> Dict[str, any]:
    engine = create_db_engine()
    sf = get_session_factory(engine)

    # Locate weather CSV
    possible_paths = [
        Path(__file__).resolve().parents[2] / "datasets" / "Plant_1_Weather_Sensor_Data.csv",
        Path.cwd() / "datasets" / "Plant_1_Weather_Sensor_Data.csv",
        Path.cwd().parent / "datasets" / "Plant_1_Weather_Sensor_Data.csv",
    ]
    csv_path = next((p for p in possible_paths if p.is_file()), None)
    if not csv_path:
        print(f"Weather sensor data not found in {possible_paths}")
        return {"error": "Weather sensor data file not found"}

    print(f"Loading weather readings from: {csv_path}")

    with sf() as session:
        # 1. Confirm target plant exists
        plant = None
        if plant_id is not None:
            plant = session.get(Plant, plant_id)
        if plant is None:
            plant = session.get(Plant, TARGET_PLANT_ID)
        if plant is None:
            plant = session.execute(
                select(Plant).where(Plant.name.ilike("%surya%"))
            ).scalars().first()
        if plant is None:
            plant = session.execute(select(Plant)).scalars().first()

        if plant is None:
            print("No plant found in database for POA remediation.")
            return {"error": "No plant found"}

        print(f"Target Plant: '{plant.name}' (ID: {plant.id})")

        # 2. Find or create WS-01 asset
        ws_asset = session.execute(
            select(Asset).where(
                Asset.plant_id == plant.id,
                Asset.name == "WS-01",
            )
        ).scalar_one_or_none()

        if ws_asset is None:
            ws_asset = Asset(
                plant_id=plant.id,
                name="WS-01",
                asset_type="weather_station",
                metadata_={
                    "source_key": KAGGLE_P1_WEATHER_SOURCE_KEY,
                    "sensor_type": "pyranometer_and_rtd",
                    "mounting_geometry": "UNKNOWN",
                    "approx_ghi": True,
                    "poa_assumed": True,
                },
            )
            session.add(ws_asset)
            session.flush()
            print(f"Created Asset 'WS-01' (ID: {ws_asset.id})")
        else:
            print(f"Found existing Asset 'WS-01' (ID: {ws_asset.id})")

        # 3. Find or create irradiance_poa channel
        poa_channel = session.execute(
            select(Channel).where(
                Channel.asset_id == ws_asset.id,
                Channel.canonical_key == "irradiance_poa",
            )
        ).scalar_one_or_none()

        if poa_channel is None:
            poa_channel = Channel(
                asset_id=ws_asset.id,
                canonical_key="irradiance_poa",
                source_name="IRRADIATION",
                receive_unit="kW/m²",
                interval_s=900,
                agg_semantics="avg",
            )
            session.add(poa_channel)
            session.flush()
            print(f"Created Channel 'irradiance_poa' (ID: {poa_channel.id})")
        else:
            print(f"Found existing Channel 'irradiance_poa' (ID: {poa_channel.id})")

        # Check existing readings count for fast-path return
        existing_count = session.execute(
            select(func.count(Reading.ts)).where(Reading.channel_id == poa_channel.id)
        ).scalar() or 0

        if existing_count > 0:
            print(f"Plant '{plant.name}' already has {existing_count} POA irradiance readings.")
            return {
                "plant_id": str(plant.id),
                "plant_name": plant.name,
                "ws_asset_id": str(ws_asset.id),
                "poa_channel_id": str(poa_channel.id),
                "poa_readings_count": existing_count,
            }

        session.commit()

        # 4. Read CSV rows
        weather_readings: List[Dict] = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dt_str = row.get("DATE_TIME", "").strip()
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                irrad_val = float(row["IRRADIATION"]) if row.get("IRRADIATION") else 0.0
                weather_readings.append({
                    "channel_id": poa_channel.id,
                    "ts": dt,
                    "value": irrad_val,
                    "quality": 100,
                })

        print(f"Parsed {len(weather_readings)} rows from weather CSV")

        # 5. Idempotent bulk upsert into readings table
        # PostgreSQL ON CONFLICT (channel_id, ts) DO UPDATE
        batch_size = 1000
        total_inserted = 0
        for i in range(0, len(weather_readings), batch_size):
            batch = weather_readings[i : i + batch_size]
            stmt = pg_insert(Reading).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["channel_id", "ts"],
                set_={
                    "value": stmt.excluded.value,
                    "quality": stmt.excluded.quality,
                },
            )
            session.execute(stmt)
            total_inserted += len(batch)

        session.commit()
        print(f"Persisted/Upserted {total_inserted} readings successfully.")

        # 6. Verification queries
        poa_count = session.execute(
            select(func.count(Reading.ts)).where(Reading.channel_id == poa_channel.id)
        ).scalar()

        min_max_poa = session.execute(
            select(func.min(Reading.ts), func.max(Reading.ts)).where(Reading.channel_id == poa_channel.id)
        ).first()

        inv_readings_count = session.execute(
            select(func.count(Reading.ts))
            .join(Channel, Reading.channel_id == Channel.id)
            .join(Asset, Channel.asset_id == Asset.id)
            .where(Asset.plant_id == plant.id, Asset.asset_type == "inverter")
        ).scalar()

        total_db_readings = session.execute(select(func.count(Reading.ts))).scalar()

        result = {
            "plant_id": str(plant.id),
            "plant_name": plant.name,
            "ws_asset_id": str(ws_asset.id),
            "poa_channel_id": str(poa_channel.id),
            "poa_readings_count": poa_count,
            "poa_time_min": str(min_max_poa[0]) if min_max_poa else None,
            "poa_time_max": str(min_max_poa[1]) if min_max_poa else None,
            "inverter_readings_count": inv_readings_count,
            "total_readings_in_db": total_db_readings,
        }

        print("\n=== POST-REMEDIATION VERIFICATION ===")
        for k, v in result.items():
            print(f"  {k}: {v}")

        return result


if __name__ == "__main__":
    remediate_poa_data()
