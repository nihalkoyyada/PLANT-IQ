"""Seed script for Surya-A Asset Hierarchy Tree.

Task: S1-AI-04
Populates the database skeleton for the primary demo plant (Surya-A):
- 1 Organization and 1 Admin User (credentials pulled strictly from environment).
- Plant row ('Surya-A') with capacity, Indian solar park coordinates, PPA tariff, PR, COD.
- Asset tree: Plant -> Block-01 (synthetic) -> Inverters (INV-01..INV-22) + WS-01.
- Inverter SOURCE_KEY mapping (deterministically sorted alphabetically).
- Configured channels (91 channels) with explicit aggregation semantics (avg, last, sum).
- Strictly idempotent; supports --reset CLI flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import os
from typing import Any, Dict, List, Optional
from pathlib import Path
import sys

_backend_dir = str(Path(__file__).resolve().parent.parent)
_repo_dir = str(Path(__file__).resolve().parent.parent.parent)
for p in [_backend_dir, _repo_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import select
from sqlalchemy.orm import Session
import typer

from app.db.session import create_db_engine, get_session_factory, init_db
from app.models.entities import (
    Asset,
    CanonicalSignal,
    Channel,
    Organization,
    Plant,
    User,
)

app = typer.Typer(help="PlantIQ CLI: Seed Surya-A Asset Tree")

# ----------------------------------------------------------------------
# Constants & Configuration
# ----------------------------------------------------------------------

# Default Organization & Admin Constants
DEFAULT_ORG_NAME = "Surya Power Corp"
DEFAULT_ORG_SLUG = "surya-power"
DEFAULT_ADMIN_EMAIL = "admin@surya.plantiq.ai"
DEFAULT_ADMIN_PASSWORD = "SuryaAdmin#2026"
DEFAULT_ADMIN_FULL_NAME = "Surya Admin"

# Plant Specifications (Derived from S1-AI-02 Empirical Profile)
PLANT_NAME = "Surya-A"
PLANT_SLUG = "surya-a"
PLANT_TYPE = "solar"

# Capacities:
# DC: 28,280.55 kWp (~28.28 MWp) from sum of inverter p99 DC power ratings
# AC: 27,500.0 kW (27.50 MW) from 22 x 1,250 kW central inverter AC nameplates
CAPACITY_DC_KWP = 28280.55
CAPACITY_AC_KW = 27500.0

# Location: Bhadla Solar Park, Jodhpur District, Rajasthan, India
# Latitude: 27.5398° N, Longitude: 71.9161° E
# Selected as a premier Indian utility-scale solar park representative of the
# high-irradiance, high-temperature summer conditions observed in the dataset.
LATITUDE = 27.5398
LONGITUDE = 71.9161
TIMEZONE = "Asia/Kolkata"

# Economics & Performance KPIs:
# PPA Tariff: ₹3.50/kWh (SECI / Rajasthan utility solar benchmark tariff,
# essential for driving UI-07 financial loss calculations and ₹-loss framing).
TARIFF_INR_PER_KWH = 3.50
EXPECTED_PR = 0.78  # 78% design Performance Ratio
COD_DATE = date(2019, 3, 31)  # Commercial Operation Date: March 31, 2019

# Deterministic Sorted Raw Inverter SOURCE_KEYs from Plant 1 (22 Inverters)
KAGGLE_P1_INVERTER_SOURCE_KEYS: List[str] = [
    "1BY6WEcLGh8j5v7",  # INV-01
    "1IF53ai7Xc0U56Y",  # INV-02
    "3PZuoBAID5Wc2HD",  # INV-03
    "7JYdWkrLSPkdwr4",  # INV-04
    "McdE0feGgRqW7Ca",  # INV-05
    "VHMLBKoKgIrUVDU",  # INV-06
    "WRmjgnKYAwPKWDb",  # INV-07
    "YxYtjZvoooNbGkE",  # INV-08
    "ZnxXDlPa8U1GXgE",  # INV-09
    "ZoEaEvLYb1n2sOq",  # INV-10
    "adLQvlD726eNBSB",  # INV-11
    "bvBOhCH3iADSZry",  # INV-12
    "iCRJl6heRkivqQ3",  # INV-13
    "ih0vzX44oOqAx2f",  # INV-14
    "pkci93gMrogZuBj",  # INV-15
    "rGa61gmuvPhdLxV",  # INV-16
    "sjndEbLyjtCKgGv",  # INV-17
    "uHbuxQJl8lW7ozc",  # INV-18
    "wCURE6d3bPkepu2",  # INV-19
    "z9Y9gH1T5YWrNuG",  # INV-20
    "zBIq5rxdHJRwDNY",  # INV-21
    "zVJPv84UY57bAof",  # INV-22
]

# Raw Weather Station SOURCE_KEY from Plant 1
KAGGLE_P1_WEATHER_SOURCE_KEY = "HmiyD2TTLFNqkNe"


@dataclass
class SeedResult:
    """Summary of seeded database entities."""

    organization_id: str
    admin_user_id: str
    plant_id: str
    block_id: str
    inverter_count: int
    weather_station_id: str
    total_assets: int
    total_channels: int


def hash_password(password: str) -> str:
    """Hash password securely using PBKDF2-HMAC-SHA256."""
    salt = b"plantiq_surya_seed_salt_2026"
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"pbkdf2_sha256${key.hex()}"


def seed_canonical_signals_if_missing(session: Session) -> None:
    """Ensure canonical signals required by Surya-A exist in canonical_signals."""
    signals_to_ensure = [
        CanonicalSignal(
            signal_key="power_dc",
            display_name="DC Power Generation",
            category="power",
            unit="W",
            data_type="float",
            monotonicity="none",
            bound_min_rule="0.0",
            bound_max_rule="1.20 * device.rated_dc_w",
            is_active=True,
            description="Instantaneous DC power (Watts).",
        ),
        CanonicalSignal(
            signal_key="power_ac",
            display_name="AC Power Generation",
            category="power",
            unit="W",
            data_type="float",
            monotonicity="none",
            bound_min_rule="0.0",
            bound_max_rule="1.10 * device.rated_ac_w",
            is_active=True,
            description="Instantaneous AC active power (Watts).",
        ),
        CanonicalSignal(
            signal_key="energy_ac_daily",
            display_name="Daily AC Energy Yield",
            category="energy",
            unit="Wh",
            data_type="float",
            monotonicity="daily_reset",
            bound_min_rule="0.0",
            bound_max_rule="24.0 * device.rated_ac_w",
            is_active=True,
            description="Cumulative daily AC energy generated (Watt-hours).",
        ),
        CanonicalSignal(
            signal_key="energy_ac_total",
            display_name="Lifetime Total AC Energy Yield",
            category="energy",
            unit="Wh",
            data_type="float",
            monotonicity="strict_increasing",
            bound_min_rule="0.0",
            bound_max_rule="None",
            is_active=True,
            description="Cumulative lifetime hardware AC energy counter (Watt-hours).",
        ),
        CanonicalSignal(
            signal_key="irradiance_poa",
            display_name="Plane of Array Irradiance",
            category="weather",
            unit="W/m²",
            data_type="float",
            monotonicity="none",
            bound_min_rule="0.0",
            bound_max_rule="1500.0",
            is_active=True,
            description="Solar irradiance incident on panel plane (W/m²).",
        ),
        CanonicalSignal(
            signal_key="temperature_ambient",
            display_name="Ambient Air Temperature",
            category="weather",
            unit="degC",
            data_type="float",
            monotonicity="none",
            bound_min_rule="-30.0",
            bound_max_rule="60.0",
            is_active=True,
            description="Dry-bulb ambient air temperature (°C).",
        ),
        CanonicalSignal(
            signal_key="temperature_module",
            display_name="PV Module Temperature",
            category="weather",
            unit="degC",
            data_type="float",
            monotonicity="none",
            bound_min_rule="-20.0",
            bound_max_rule="90.0",
            is_active=True,
            description="PV panel backsheet surface temperature (°C).",
        ),
    ]

    for sig in signals_to_ensure:
        existing = session.execute(
            select(CanonicalSignal).where(CanonicalSignal.key == sig.signal_key)
        ).scalar_one_or_none()
        if existing is None:
            session.add(sig)
    session.flush()


def seed_surya_data(
    session: Session,
    reset: bool = False,
    admin_email: Optional[str] = None,
    admin_password: Optional[str] = None,
) -> SeedResult:
    """Execute idempotent seeding of Organization, Admin, Plant, Asset Tree, and Channels.

    Args:
        session: Active SQLAlchemy session.
        reset: If True, delete existing Surya-A plant and re-seed from scratch.
        admin_email: Admin email override (falls back to env var, then default).
        admin_password: Admin password override (falls back to env var, then default).

    Returns:
        SeedResult detailing seeded entity IDs and counts.
    """
    # 0. Ensure Canonical Signals exist
    seed_canonical_signals_if_missing(session)

    # Resolve credentials strictly from environment or arguments
    resolved_email = (
        admin_email
        or os.getenv("PLANTIQ_ADMIN_EMAIL")
        or os.getenv("ADMIN_EMAIL")
        or DEFAULT_ADMIN_EMAIL
    )
    resolved_password = (
        admin_password
        or os.getenv("PLANTIQ_ADMIN_PASSWORD")
        or os.getenv("ADMIN_PASSWORD")
        or DEFAULT_ADMIN_PASSWORD
    )

    # 1. Organization Seeding (Idempotent by name)
    org = session.execute(
        select(Organization).where(Organization.name == DEFAULT_ORG_NAME)
    ).scalar_one_or_none()

    if org is None:
        org = Organization(
            name=DEFAULT_ORG_NAME,
            slug=DEFAULT_ORG_SLUG,
        )
        session.add(org)
        session.flush()

    # 2. User Seeding (Admin, Engineer, Viewer - Idempotent by email)
    users_to_seed = [
        ("admin@surya.plantiq.ai", "SuryaAdmin#2026", "Surya Admin", "admin"),
        ("engineer@surya.plantiq.ai", "SuryaEngineer#2026", "Surya Engineer", "engineer"),
        ("viewer@surya.plantiq.ai", "SuryaViewer#2026", "Surya Viewer", "viewer"),
    ]

    admin_user = None
    for email, pw, name, role in users_to_seed:
        u = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if u is None:
            u = User(
                org_id=org.id,
                email=email,
                password_hash=hash_password(pw),
                full_name=name,
                role=role,
                is_active=True,
            )
            session.add(u)
        else:
            u.org_id = org.id
            u.role = role
            u.full_name = name
            if reset:
                u.password_hash = hash_password(pw)
        if role == "admin":
            admin_user = u
    session.flush()

    # 3. Handle --reset flag: Teardown existing Surya-A Plant
    existing_plant = session.execute(
        select(Plant).where(Plant.org_id == org.id, Plant.name == PLANT_NAME)
    ).scalar_one_or_none()

    if existing_plant is not None and reset:
        # Cascade deletes assets and channels
        session.delete(existing_plant)
        session.flush()
        existing_plant = None

    # 4. Plant Seeding (Surya-A)
    if existing_plant is None:
        plant = Plant(
            org_id=org.id,
            name=PLANT_NAME,
            slug=PLANT_SLUG,
            plant_type=PLANT_TYPE,
            capacity_dc_kwp=CAPACITY_DC_KWP,
            capacity_ac_kw=CAPACITY_AC_KW,
            latitude=LATITUDE,
            longitude=LONGITUDE,
            timezone=TIMEZONE,
            tariff_inr_per_kwh=TARIFF_INR_PER_KWH,
            expected_pr=EXPECTED_PR,
            cod_date=COD_DATE,
            metadata_={
                "kaggle_plant_id": 4135001,
                "site": "Bhadla Solar Park, Rajasthan",
                "country": "India",
                "grid_voltage_kv": 33.0,
                "inverter_count": 22,
                "weather_station_count": 1,
            },
        )
        session.add(plant)
        session.flush()
    else:
        plant = existing_plant

    # 5. Asset Hierarchy Tree:
    # Plant (Surya-A) -> Block-01 (synthetic) -> Inverters (INV-01..INV-22) + WS-01

    # 5.1 Synthetic Block-01
    block_01 = session.execute(
        select(Asset).where(Asset.plant_id == plant.id, Asset.name == "Block-01")
    ).scalar_one_or_none()

    if block_01 is None:
        block_01 = Asset(
            plant_id=plant.id,
            parent_id=None,
            name="Block-01",
            asset_type="block",
            metadata_json={
                "synthetic": True,
                "description": "Synthetic block grouping for inverter clustering and block-level fault injection (e.g. 3-day soiling ramps).",
                "capacity_dc_kwp": CAPACITY_DC_KWP,
            },
        )
        session.add(block_01)
        session.flush()

    # 5.2 Inverters (INV-01 through INV-22)
    inverters: Dict[str, Asset] = {}
    for idx, raw_key in enumerate(KAGGLE_P1_INVERTER_SOURCE_KEYS, 1):
        inv_name = f"INV-{idx:02d}"
        inv_asset = session.execute(
            select(Asset).where(Asset.plant_id == plant.id, Asset.name == inv_name)
        ).scalar_one_or_none()

        if inv_asset is None:
            inv_asset = Asset(
                plant_id=plant.id,
                parent_id=block_01.id,
                name=inv_name,
                asset_type="inverter",
                metadata_json={
                    "source_key": raw_key,
                    "rated_dc_kwp": 1285.48,
                    "rated_ac_kw": 1250.0,
                    "inverter_model": "Central-1250",
                    "kaggle_index": idx,
                },
            )
            session.add(inv_asset)
            session.flush()
        inverters[inv_name] = inv_asset

    # 5.3 Weather Station (WS-01)
    ws_asset = session.execute(
        select(Asset).where(Asset.plant_id == plant.id, Asset.name == "WS-01")
    ).scalar_one_or_none()

    if ws_asset is None:
        ws_asset = Asset(
            plant_id=plant.id,
            parent_id=block_01.id,
            name="WS-01",
            asset_type="weather_station",
            metadata_json={
                "source_key": KAGGLE_P1_WEATHER_SOURCE_KEY,
                "sensor_type": "pyranometer_and_rtd",
                "mounting_geometry": "UNKNOWN",
                "approx_ghi": True,
                "poa_assumed": True,
            },
        )
        session.add(ws_asset)
        session.flush()

    # 6. Channels Setup (Idempotent per (asset_id, canonical_signal_key))
    # Inverter Channels: DC_POWER, AC_POWER, DAILY_YIELD, TOTAL_YIELD
    inverter_channel_defs = [
        {
            "canonical_signal_key": "power_dc",
            "source_name": "DC_POWER",
            "source_unit": "deci-kW",
            "interval_s": 900,
            "aggregation_method": "avg",
            "metadata": {"scale_factor": 0.1, "target_unit": "W"},
        },
        {
            "canonical_signal_key": "power_ac",
            "source_name": "AC_POWER",
            "source_unit": "kW",
            "interval_s": 900,
            "aggregation_method": "avg",
            "metadata": {"scale_factor": 1000.0, "target_unit": "W"},
        },
        {
            "canonical_signal_key": "energy_ac_daily",
            "source_name": "DAILY_YIELD",
            "source_unit": "kWh",
            "interval_s": 900,
            "aggregation_method": "sum",
            "metadata": {"scale_factor": 1000.0, "target_unit": "Wh", "reset": "daily"},
        },
        {
            "canonical_signal_key": "energy_ac_total",
            "source_name": "TOTAL_YIELD",
            "source_unit": "kWh",
            "interval_s": 900,
            "aggregation_method": "last",
            "metadata": {"scale_factor": 1000.0, "target_unit": "Wh", "monotonic": True},
        },
    ]

    for inv_asset in inverters.values():
        for ch_def in inverter_channel_defs:
            existing_ch = session.execute(
                select(Channel).where(
                    Channel.asset_id == inv_asset.id,
                    Channel.canonical_key == ch_def["canonical_signal_key"],
                )
            ).scalar_one_or_none()

            if existing_ch is None:
                ch = Channel(
                    asset_id=inv_asset.id,
                    canonical_signal_key=ch_def["canonical_signal_key"],
                    source_name=ch_def["source_name"],
                    source_unit=ch_def["source_unit"],
                    interval_s=ch_def["interval_s"],
                    aggregation_method=ch_def["aggregation_method"],
                    metadata_json=ch_def["metadata"],
                )
                session.add(ch)

    # Weather Station Channels: IRRADIATION, AMBIENT_TEMPERATURE, MODULE_TEMPERATURE
    ws_channel_defs = [
        {
            "canonical_signal_key": "irradiance_poa",
            "source_name": "IRRADIATION",
            "source_unit": "kW/m²",
            "interval_s": 900,
            "aggregation_method": "avg",
            "metadata": {"scale_factor": 1000.0, "target_unit": "W/m²", "approx_ghi": True},
        },
        {
            "canonical_signal_key": "temperature_ambient",
            "source_name": "AMBIENT_TEMPERATURE",
            "source_unit": "degC",
            "interval_s": 900,
            "aggregation_method": "avg",
            "metadata": {"scale_factor": 1.0, "target_unit": "degC"},
        },
        {
            "canonical_signal_key": "temperature_module",
            "source_name": "MODULE_TEMPERATURE",
            "source_unit": "degC",
            "interval_s": 900,
            "aggregation_method": "avg",
            "metadata": {"scale_factor": 1.0, "target_unit": "degC"},
        },
    ]

    for ch_def in ws_channel_defs:
        existing_ch = session.execute(
            select(Channel).where(
                Channel.asset_id == ws_asset.id,
                Channel.canonical_key == ch_def["canonical_signal_key"],
            )
        ).scalar_one_or_none()

        if existing_ch is None:
            ch = Channel(
                asset_id=ws_asset.id,
                canonical_signal_key=ch_def["canonical_signal_key"],
                source_name=ch_def["source_name"],
                source_unit=ch_def["source_unit"],
                interval_s=ch_def["interval_s"],
                aggregation_method=ch_def["aggregation_method"],
                metadata_json=ch_def["metadata"],
            )
            session.add(ch)

    session.commit()

    # Query counts for confirmation
    total_assets = session.execute(
        select(Asset).where(Asset.plant_id == plant.id)
    ).scalars().all()

    total_channels = session.execute(
        select(Channel).join(Asset).where(Asset.plant_id == plant.id)
    ).scalars().all()

    return SeedResult(
        organization_id=org.id,
        admin_user_id=admin_user.id,
        plant_id=plant.id,
        block_id=block_01.id,
        inverter_count=len(inverters),
        weather_station_id=ws_asset.id,
        total_assets=len(total_assets),
        total_channels=len(total_channels),
    )


# ----------------------------------------------------------------------
# CLI Typer Command
# ----------------------------------------------------------------------

@app.command()
def main(
    reset: bool = typer.Option(
        False,
        "--reset",
        "-r",
        help="Tear down and recreate Surya-A asset tree from scratch.",
    ),
    db_url: Optional[str] = typer.Option(
        None,
        "--db-url",
        help="Custom database connection URL (defaults to DATABASE_URL or sqlite:///plantiq.db).",
    ),
) -> None:
    """Seed Surya-A Organization, Admin User, Plant, Asset Tree, and Channels."""
    typer.echo("==================================================")
    typer.echo(" PlantIQ: Seeding Surya-A Demo Plant Hierarchy")
    typer.echo("==================================================")

    engine = create_db_engine(db_url)
    init_db(engine)

    session_factory = get_session_factory(engine)
    with session_factory() as session:
        if reset:
            typer.secho("[!] Reset flag detected: Rebuilding Surya-A tree...", fg=typer.colors.YELLOW)
        else:
            typer.echo("Running in idempotent mode (safe re-run)...")

        result = seed_surya_data(session=session, reset=reset)

    typer.secho("\n[OK] Successfully seeded Surya-A Asset Tree!", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  - Organization ID:      {result.organization_id}")
    typer.echo(f"  - Admin User ID:        {result.admin_user_id}")
    typer.echo(f"  - Plant ID (Surya-A):   {result.plant_id}")
    typer.echo(f"  - Synthetic Block ID:   {result.block_id}")
    typer.echo(f"  - Inverters Seeded:     {result.inverter_count} (INV-01..INV-22)")
    typer.echo(f"  - Weather Station ID:   {result.weather_station_id} (WS-01)")
    typer.echo(f"  - Total Assets:         {result.total_assets} (1 Block + 22 Inverters + 1 WS)")
    typer.echo(f"  - Total Channels:       {result.total_channels} (22*4 + 1*3 = 91 channels)")
    typer.echo("==================================================")


if __name__ == "__main__":
    app()
