"""Automated tests for Surya-A seed script.

Task: S1-AI-04
Validates:
- Complete asset tree formation: Plant -> Block-01 -> 22 Inverters + 1 Weather Station.
- Idempotency: Re-running seeder against existing database produces identical row counts and entities.
- Reset: Rebuilding with reset=True cleans up and recreates cleanly.
- Channel aggregation semantics (avg, sum, last) and interval_s = 900.
"""

from datetime import date
from typing import Generator
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.entities import (
    Asset,
    CanonicalSignal,
    Channel,
    Organization,
    Plant,
    User,
)
from scripts.seed_surya import (
    CAPACITY_AC_KW,
    CAPACITY_DC_KWP,
    KAGGLE_P1_INVERTER_SOURCE_KEYS,
    KAGGLE_P1_WEATHER_SOURCE_KEY,
    LATITUDE,
    LONGITUDE,
    PLANT_NAME,
    PLANT_SLUG,
    TARIFF_INR_PER_KWH,
    TIMEZONE,
    seed_surya_data,
)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as session:
        yield session
    engine.dispose()


class TestSuryaASeeder:
    """Test suite for Surya-A asset hierarchy tree seeding."""

    def test_initial_seed_structure(self, db_session: Session) -> None:
        """Verify initial seed creates complete and well-formed asset hierarchy."""
        result = seed_surya_data(session=db_session, reset=False)

        # 1. Verify Organization & Admin User
        org = db_session.get(Organization, result.organization_id)
        assert org is not None
        assert org.name == "Surya Power Corp"
        assert org.slug in ("surya-power", "surya-power-corp")

        admin = db_session.get(User, result.admin_user_id)
        assert admin is not None
        assert admin.email == "admin@surya.plantiq.ai"
        assert admin.is_superuser is True
        assert admin.organization_id == org.id

        # 2. Verify Plant (Surya-A)
        plant = db_session.get(Plant, result.plant_id)
        assert plant is not None
        assert plant.name == PLANT_NAME
        assert plant.slug == PLANT_SLUG
        assert plant.plant_type == "solar"
        assert float(plant.capacity_dc_kwp) == pytest.approx(CAPACITY_DC_KWP)
        assert float(plant.capacity_ac_kw) == pytest.approx(CAPACITY_AC_KW)
        assert float(plant.latitude) == pytest.approx(LATITUDE)
        assert float(plant.longitude) == pytest.approx(LONGITUDE)
        assert plant.timezone == TIMEZONE
        assert float(plant.tariff_inr_per_kwh) == pytest.approx(TARIFF_INR_PER_KWH)
        assert float(plant.expected_pr) == pytest.approx(0.78)
        assert plant.cod_date == date(2019, 3, 31)

        # 3. Verify Synthetic Block-01
        block = db_session.get(Asset, result.block_id)
        assert block is not None
        assert block.name == "Block-01"
        assert block.asset_type == "block"
        assert block.parent_id is None
        assert block.metadata_json is not None
        assert block.metadata_json.get("synthetic") is True

        # 4. Verify Inverters (INV-01 through INV-22)
        inverters = db_session.execute(
            select(Asset).where(Asset.plant_id == plant.id, Asset.asset_type == "inverter")
        ).scalars().all()
        assert len(inverters) == 22

        # Sort inverters by name to check 1:1 mapping
        sorted_invs = sorted(inverters, key=lambda a: a.name)
        for idx, (inv, raw_key) in enumerate(zip(sorted_invs, KAGGLE_P1_INVERTER_SOURCE_KEYS), 1):
            assert inv.name == f"INV-{idx:02d}"
            assert inv.parent_id == block.id
            assert inv.metadata_json is not None
            assert inv.metadata_json["source_key"] == raw_key
            assert inv.metadata_json["rated_dc_kwp"] == pytest.approx(1285.48)
            assert inv.metadata_json["rated_ac_kw"] == pytest.approx(1250.0)

        # 5. Verify Weather Station (WS-01)
        ws = db_session.get(Asset, result.weather_station_id)
        assert ws is not None
        assert ws.name == "WS-01"
        assert ws.asset_type == "weather_station"
        assert ws.parent_id == block.id
        assert ws.metadata_json is not None
        assert ws.metadata_json["source_key"] == KAGGLE_P1_WEATHER_SOURCE_KEY
        assert ws.metadata_json.get("approx_ghi") is True

        # 6. Verify Channels (22*4 + 1*3 = 91 total channels)
        channels = db_session.execute(select(Channel)).scalars().all()
        assert len(channels) == 91

        # Check inverter channel signals and aggregation semantics
        sample_inv = sorted_invs[0]
        inv_channels = db_session.execute(
            select(Channel).where(Channel.asset_id == sample_inv.id)
        ).scalars().all()
        assert len(inv_channels) == 4

        ch_map = {c.canonical_signal_key: c for c in inv_channels}
        assert ch_map["power_dc"].aggregation_method == "avg"
        assert ch_map["power_dc"].source_name == "DC_POWER"
        assert ch_map["power_dc"].interval_s == 900

        assert ch_map["power_ac"].aggregation_method == "avg"
        assert ch_map["power_ac"].source_name == "AC_POWER"

        assert ch_map["energy_ac_daily"].aggregation_method == "sum"
        assert ch_map["energy_ac_daily"].source_name == "DAILY_YIELD"

        assert ch_map["energy_ac_total"].aggregation_method == "last"
        assert ch_map["energy_ac_total"].source_name == "TOTAL_YIELD"

        # Check weather station channel signals
        ws_channels = db_session.execute(
            select(Channel).where(Channel.asset_id == ws.id)
        ).scalars().all()
        assert len(ws_channels) == 3
        ws_map = {c.canonical_signal_key: c for c in ws_channels}
        assert ws_map["irradiance_poa"].aggregation_method == "avg"
        assert ws_map["irradiance_poa"].source_name == "IRRADIATION"
        assert ws_map["temperature_ambient"].aggregation_method == "avg"
        assert ws_map["temperature_module"].aggregation_method == "avg"

    def test_idempotency_second_run_no_duplicates(self, db_session: Session) -> None:
        """Assert that running seeder a second time is a safe no-op with identical row counts."""
        # First Run
        res1 = seed_surya_data(session=db_session, reset=False)

        count_org1 = len(db_session.execute(select(Organization)).scalars().all())
        count_user1 = len(db_session.execute(select(User)).scalars().all())
        count_plant1 = len(db_session.execute(select(Plant)).scalars().all())
        count_asset1 = len(db_session.execute(select(Asset)).scalars().all())
        count_chan1 = len(db_session.execute(select(Channel)).scalars().all())

        # Second Run (Idempotent)
        res2 = seed_surya_data(session=db_session, reset=False)

        count_org2 = len(db_session.execute(select(Organization)).scalars().all())
        count_user2 = len(db_session.execute(select(User)).scalars().all())
        count_plant2 = len(db_session.execute(select(Plant)).scalars().all())
        count_asset2 = len(db_session.execute(select(Asset)).scalars().all())
        count_chan2 = len(db_session.execute(select(Channel)).scalars().all())

        # Assert zero row count drift
        assert count_org1 == count_org2 == 1
        assert count_user1 == count_user2 == 3
        assert count_plant1 == count_plant2 == 1
        assert count_asset1 == count_asset2 == 24
        assert count_chan1 == count_chan2 == 91

        # Assert exact entity identity preservation
        assert res1.organization_id == res2.organization_id
        assert res1.admin_user_id == res2.admin_user_id
        assert res1.plant_id == res2.plant_id
        assert res1.block_id == res2.block_id

    def test_reset_flag_rebuilds_cleanly(self, db_session: Session) -> None:
        """Assert that reset=True safely tears down and recreates plant hierarchy."""
        res1 = seed_surya_data(session=db_session, reset=False)

        # Run with reset=True
        res2 = seed_surya_data(session=db_session, reset=True)

        # Verify new plant and asset IDs generated
        assert res1.plant_id != res2.plant_id
        assert res1.block_id != res2.block_id

        # Row counts must still be exactly 1 plant, 24 assets, 91 channels (no orphan leakage)
        assert len(db_session.execute(select(Plant)).scalars().all()) == 1
        assert len(db_session.execute(select(Asset)).scalars().all()) == 24
        assert len(db_session.execute(select(Channel)).scalars().all()) == 91
