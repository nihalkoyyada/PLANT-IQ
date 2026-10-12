"""Comprehensive Test Suite for Copilot Tool Layer & Infrastructure (§10.3, Task S5-AI-01).

Tests:
1. Operational logic for all 12 Copilot SCADA tools.
2. Pydantic schema validation & bounds enforcement.
3. Multi-tenant Org & Plant security scoping isolation.
4. Large array handling via ResultRefStore and ECharts ChartStore caching.
5. Copilot REST API endpoints (/results/{ref_id}, /charts/{chart_id}, /tools, /tools/execute).
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.copilot.context import SecurityScopeError, ToolSecurityContext
from app.copilot.registry import default_tool_registry
from app.copilot.result_store import (
    ResultRefStore,
    default_chart_store,
    default_result_store,
    format_timeseries_result,
)
from app.copilot.schemas import (
    ChannelSelector,
    ChartSeriesSpec,
    ChartSpec,
    CompareAssetsInput,
    ComputeKPIInput,
    DetectOnDemandInput,
    GetDataCoverageInput,
    GetAnomalyInput,
    GetCurrentTimeInput,
    GetPlantSummaryInput,
    ListAnomaliesInput,
    ListAssetsInput,
    ListEventsInput,
    QueryTimeseriesInput,
    RenderChartInput,
)
from app.copilot.tools import (
    tool_compare_assets,
    tool_compute_kpi,
    tool_detect_on_demand,
    tool_get_anomaly,
    tool_get_current_time,
    tool_get_data_coverage,
    tool_get_plant_summary,
    tool_list_anomalies,
    tool_list_assets,
    tool_list_events,
    tool_query_timeseries,
    tool_render_chart,
)
from app.db.database import SessionLocal
from app.main import app
from app.models.entities import (
    Anomaly,
    Asset,
    CanonicalSignal,
    Channel,
    Event,
    Organization,
    Plant,
    Reading,
    User,
)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def copilot_test_db():
    """Setup multi-tenant fixtures for Copilot tool validation."""
    db = SessionLocal()
    try:
        # Organization A & User A
        org_a = db.query(Organization).filter(Organization.name == "Copilot Test Org A").first()
        if not org_a:
            org_a = Organization(name="Copilot Test Org A")
            db.add(org_a)
            db.commit()
            db.refresh(org_a)

        user_a = db.query(User).filter(User.email == "copilot_user_a@test.com").first()
        if not user_a:
            user_a = User(
                org_id=org_a.id,
                email="copilot_user_a@test.com",
                password_hash="pw_hash",
                full_name="Copilot User A",
                role="engineer",
                is_active=True,
            )
            db.add(user_a)
            db.commit()
            db.refresh(user_a)

        # Organization B & User B (Attacker / Cross-tenant)
        org_b = db.query(Organization).filter(Organization.name == "Copilot Test Org B").first()
        if not org_b:
            org_b = Organization(name="Copilot Test Org B")
            db.add(org_b)
            db.commit()
            db.refresh(org_b)

        user_b = db.query(User).filter(User.email == "copilot_user_b@test.com").first()
        if not user_b:
            user_b = User(
                org_id=org_b.id,
                email="copilot_user_b@test.com",
                password_hash="pw_hash",
                full_name="Copilot User B",
                role="engineer",
                is_active=True,
            )
            db.add(user_b)
            db.commit()
            db.refresh(user_b)

        # Plant in Org A
        plant_a = db.query(Plant).filter(Plant.name == "Copilot Solar Plant Alpha", Plant.org_id == org_a.id).first()
        if not plant_a:
            plant_a = Plant(
                org_id=org_a.id,
                name="Copilot Solar Plant Alpha",
                plant_type="solar",
                capacity_ac_kw=2000.0,
                capacity_dc_kwp=2400.0,
                tariff_inr_per_kwh=3.50,
                metadata_json={"timezone": "Asia/Kolkata", "location": {"lat": 28.6, "lon": 77.2}},
            )
            db.add(plant_a)
            db.commit()
            db.refresh(plant_a)

        # Plant in Org B
        plant_b = db.query(Plant).filter(Plant.name == "Copilot Solar Plant Beta", Plant.org_id == org_b.id).first()
        if not plant_b:
            plant_b = Plant(
                org_id=org_b.id,
                name="Copilot Solar Plant Beta",
                plant_type="solar",
                capacity_ac_kw=1000.0,
                capacity_dc_kwp=1200.0,
                tariff_inr_per_kwh=3.00,
            )
            db.add(plant_b)
            db.commit()
            db.refresh(plant_b)

        # Assets in Plant A
        inv1 = db.query(Asset).filter(Asset.name == "INV-COPILOT-01", Asset.plant_id == plant_a.id).first()
        if not inv1:
            inv1 = Asset(
                plant_id=plant_a.id,
                name="INV-COPILOT-01",
                asset_type="inverter",
                rated_kw=1000.0,
                metadata_json={"source_key": "INV_01"},
            )
            db.add(inv1)

        inv2 = db.query(Asset).filter(Asset.name == "INV-COPILOT-02", Asset.plant_id == plant_a.id).first()
        if not inv2:
            inv2 = Asset(
                plant_id=plant_a.id,
                name="INV-COPILOT-02",
                asset_type="inverter",
                rated_kw=1000.0,
                metadata_json={"source_key": "INV_02"},
            )
            db.add(inv2)

        wms = db.query(Asset).filter(Asset.name == "WMS-COPILOT-01", Asset.plant_id == plant_a.id).first()
        if not wms:
            wms = Asset(
                plant_id=plant_a.id,
                name="WMS-COPILOT-01",
                asset_type="weather_station",
                metadata_json={"source_key": "WMS_01"},
            )
            db.add(wms)

        db.commit()
        db.refresh(inv1)
        db.refresh(inv2)
        db.refresh(wms)

        # Ensure canonical signals exist
        for sig_k, sig_unit in [("active_power", "kW"), ("power_dc", "kW"), ("poa_irradiance", "W/m²")]:
            cs = db.query(CanonicalSignal).filter(CanonicalSignal.key == sig_k).first()
            if not cs:
                cs = CanonicalSignal(
                    signal_key=sig_k,
                    display_name=sig_k,
                    category="power" if "power" in sig_k else "weather",
                    unit=sig_unit,
                )
                db.add(cs)
        db.commit()

        # Channels for INV-01
        ch_inv1_pwr = db.query(Channel).filter(Channel.asset_id == inv1.id, Channel.canonical_key == "active_power").first()
        if not ch_inv1_pwr:
            ch_inv1_pwr = Channel(asset_id=inv1.id, source_name="INV1 Active Power", canonical_key="active_power", receive_unit="kW", interval_s=900)
            db.add(ch_inv1_pwr)

        ch_inv1_dc = db.query(Channel).filter(Channel.asset_id == inv1.id, Channel.canonical_key == "power_dc").first()
        if not ch_inv1_dc:
            ch_inv1_dc = Channel(asset_id=inv1.id, source_name="INV1 DC Power", canonical_key="power_dc", receive_unit="kW", interval_s=900)
            db.add(ch_inv1_dc)

        # Channels for INV-02
        ch_inv2_pwr = db.query(Channel).filter(Channel.asset_id == inv2.id, Channel.canonical_key == "active_power").first()
        if not ch_inv2_pwr:
            ch_inv2_pwr = Channel(asset_id=inv2.id, source_name="INV2 Active Power", canonical_key="active_power", receive_unit="kW", interval_s=900)
            db.add(ch_inv2_pwr)

        # Channels for WMS
        ch_poa = db.query(Channel).filter(Channel.asset_id == wms.id, Channel.canonical_key == "poa_irradiance").first()
        if not ch_poa:
            ch_poa = Channel(asset_id=wms.id, source_name="Plane of Array Irradiance", canonical_key="poa_irradiance", receive_unit="W/m²", interval_s=900)
            db.add(ch_poa)

        db.commit()
        db.refresh(ch_inv1_pwr)
        db.refresh(ch_inv1_dc)
        db.refresh(ch_inv2_pwr)
        db.refresh(ch_poa)

        # Telemetry Readings (> 60 points to test both inline & large-array ResultRefStore)
        base_time = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
        existing_readings = db.query(Reading).filter(Reading.channel_id == ch_inv1_pwr.id).count()
        if existing_readings < 70:
            readings_to_add = []
            for i in range(80):  # 80 points (15 min intervals => 20 hours)
                t = base_time + timedelta(minutes=15 * i)
                # Sunlight curve
                solar_factor = max(0.0, 1.0 - abs(i - 40) / 30.0)
                inv1_kw = round(850.0 * solar_factor, 2)
                inv2_kw = round(750.0 * solar_factor, 2)
                poa_val = round(950.0 * solar_factor, 1)

                readings_to_add.append(Reading(channel_id=ch_inv1_pwr.id, ts=t, value=inv1_kw))
                readings_to_add.append(Reading(channel_id=ch_inv1_dc.id, ts=t, value=inv1_kw * 1.03))
                readings_to_add.append(Reading(channel_id=ch_inv2_pwr.id, ts=t, value=inv2_kw))
                readings_to_add.append(Reading(channel_id=ch_poa.id, ts=t, value=poa_val))

            db.bulk_save_objects(readings_to_add)
            db.commit()

        # Seed Sample Anomaly
        anom = db.query(Anomaly).filter(Anomaly.plant_id == plant_a.id).first()
        if not anom:
            anom = Anomaly(
                plant_id=plant_a.id,
                asset_id=inv1.id,
                start_time=base_time + timedelta(hours=4),
                end_time=base_time + timedelta(hours=6),
                status="open",
                severity="high",
                source="d3_irradiance_residual",
                summary="Soiling detected on INV-COPILOT-01",
                details={
                    "detector_method": "d3_irradiance_residual",
                    "loss_kwh": 320.5,
                    "total_financial_loss_inr": 1121.75,
                    "root_cause": "Module soiling and string clipping",
                    "peer_inverters": [str(inv2.id)],
                },
                rca_narrative={
                    "root_cause": "Module soiling and string clipping",
                },
            )
            db.add(anom)
            db.commit()
            db.refresh(anom)

        # Seed Sample Event
        event = db.query(Event).filter(Event.plant_id == plant_a.id, Event.event_type == "warning").first()
        if not event:
            event = Event(
                plant_id=plant_a.id,
                asset_id=inv1.id,
                event_type="warning",
                severity="warning",
                start_time=base_time + timedelta(hours=2),
                description="DC bus overvoltage transient detected.",
            )
            db.add(event)
            db.commit()
            db.refresh(event)

        yield {
            "db": db,
            "org_a": org_a,
            "user_a": user_a,
            "token_a": create_access_token({"sub": str(user_a.id), "org_id": str(org_a.id), "role": user_a.role}),
            "org_b": org_b,
            "user_b": user_b,
            "token_b": create_access_token({"sub": str(user_b.id), "org_id": str(org_b.id), "role": user_b.role}),
            "plant_a": plant_a,
            "plant_b": plant_b,
            "inv1": inv1,
            "inv2": inv2,
            "wms": wms,
            "ch_inv1_pwr": ch_inv1_pwr,
            "anomaly": anom,
            "event": event,
            "base_time": base_time,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. Multi-Tenant Security Scoping Tests
# ---------------------------------------------------------------------------

def test_security_context_cross_tenant_plant_denied(copilot_test_db):
    """Verify ToolSecurityContext blocks access when Org B attempts to query Plant A."""
    ctx_b = ToolSecurityContext(
        org_id=copilot_test_db["org_b"].id,
        user_id=copilot_test_db["user_b"].id,
        user_role="engineer",
    )
    with pytest.raises(SecurityScopeError, match="Plant .* not found or access denied"):
        ctx_b.validate_plant_access(copilot_test_db["plant_a"].id, copilot_test_db["db"])


def test_security_context_cross_tenant_asset_denied(copilot_test_db):
    """Verify ToolSecurityContext blocks cross-tenant asset access."""
    ctx_b = ToolSecurityContext(
        org_id=copilot_test_db["org_b"].id,
        user_id=copilot_test_db["user_b"].id,
        user_role="engineer",
    )
    with pytest.raises(SecurityScopeError, match="Asset .* not found or access denied"):
        ctx_b.validate_asset_access(copilot_test_db["inv1"].id, copilot_test_db["db"])


def test_security_context_cross_tenant_anomaly_denied(copilot_test_db):
    """Verify ToolSecurityContext blocks cross-tenant anomaly access."""
    ctx_b = ToolSecurityContext(
        org_id=copilot_test_db["org_b"].id,
        user_id=copilot_test_db["user_b"].id,
        user_role="engineer",
    )
    with pytest.raises(SecurityScopeError, match="Anomaly .* not found or access denied"):
        ctx_b.validate_anomaly_access(copilot_test_db["anomaly"].id, copilot_test_db["db"])


# ---------------------------------------------------------------------------
# 2. ResultRefStore Large Array Caching Tests
# ---------------------------------------------------------------------------

def test_result_ref_store_caching_and_lru():
    """Verify ResultRefStore caching, retrieval, expiration, and formatting."""
    store = ResultRefStore(max_entries=3, default_ttl_seconds=10)

    # Put and get
    ref1 = store.put([1, 2, 3], prefix="test")
    assert ref1.startswith("test_")
    assert store.get(ref1) == [1, 2, 3]

    # Test format_timeseries_result with inline data (<= 5 points)
    small_series = [{"name": "small", "data": [[1000, 10.0], [2000, 20.0]]}]
    res_small = store.format_timeseries_result(small_series, max_inline_points=5)
    assert "data" in res_small
    assert res_small["total_points"] == 2
    assert res_small["series_summaries"][0]["min"] == 10.0
    assert res_small["series_summaries"][0]["max"] == 20.0

    # Test format_timeseries_result with large data (> 5 points)
    large_points = [[i * 100, float(i)] for i in range(10)]
    large_series = [{"name": "large", "data": large_points}]
    res_large = store.format_timeseries_result(large_series, max_inline_points=5)
    assert "data" not in res_large  # Must not return inline to save context window
    assert "result_ref" in res_large
    assert res_large["total_points"] == 10
    assert "preview" in res_large["series_summaries"][0]
    # Check that original full coordinates can be retrieved from store
    full_cached = store.get(res_large["result_ref"])
    assert full_cached == large_series


# ---------------------------------------------------------------------------
# 3. Pydantic Schema Validation Tests
# ---------------------------------------------------------------------------

def test_pydantic_schema_validation_guards():
    """Verify strict validation guards across Copilot schemas."""
    # query_timeseries end must be > start
    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(Exception):
        QueryTimeseriesInput(
            channel_selector=[ChannelSelector(asset_name="INV-01", canonical_signal="active_power")],
            start=t0,
            end=t0,  # Invalid: end == start
        )

    # compare_assets must require >= 2 assets
    with pytest.raises(Exception):
        CompareAssetsInput(
            target="active_power",
            asset_ids=[uuid4()],  # Only 1 asset
            start_date=t0,
            end_date=t0 + timedelta(days=1),
        )

    # chart must require at least one series
    with pytest.raises(Exception):
        ChartSpec(title="Empty Chart", series=[])


def test_registry_tool_definitions_generated():
    """Verify CopilotToolRegistry exports all 12 tools with valid JSON schemas."""
    definitions = default_tool_registry.get_tool_definitions()
    assert len(definitions) == 12

    names = {d.name for d in definitions}
    expected_12 = {
        "get_plant_summary",
        "list_assets",
        "query_timeseries",
        "compute_kpi",
        "compare_assets",
        "list_anomalies",
        "get_anomaly",
        "list_events",
        "detect_on_demand",
        "render_chart",
        "get_data_coverage",
        "get_current_time",
    }
    assert names == expected_12

    for d in definitions:
        assert d.description
        assert "properties" in d.parameters
        assert d.parameters.get("type") == "object"


# ---------------------------------------------------------------------------
# 4. Operational Backend Execution Tests (All 12 Tools)
# ---------------------------------------------------------------------------

def test_tool_1_get_plant_summary(copilot_test_db):
    """Test Tool 1: get_plant_summary."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = GetPlantSummaryInput(
        plant_id=copilot_test_db["plant_a"].id,
        start_date=copilot_test_db["base_time"],
        end_date=copilot_test_db["base_time"] + timedelta(days=1),
    )
    res = tool_get_plant_summary(params, ctx, copilot_test_db["db"])

    assert res["plant_id"] == str(copilot_test_db["plant_a"].id)
    assert res["name"] == "Copilot Solar Plant Alpha"
    assert res["capacity_ac_kw"] == 2000.0
    assert res["asset_summary"]["inverters"] >= 2
    assert "total_energy_kwh" in res["performance_summary"]
    assert "total_open" in res["anomalies"]


def test_tool_2_list_assets(copilot_test_db):
    """Test Tool 2: list_assets."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = ListAssetsInput(
        plant_id=copilot_test_db["plant_a"].id,
        asset_type="inverter",
    )
    res = tool_list_assets(params, ctx, copilot_test_db["db"])

    assert res["total_count"] >= 2
    inverter_names = [a["name"] for a in res["assets"]]
    assert "INV-COPILOT-01" in inverter_names
    assert "INV-COPILOT-02" in inverter_names
    assert "active_power" in res["assets"][0]["available_signals"]


def test_tool_3_query_timeseries_large_array_ref(copilot_test_db):
    """Test Tool 3: query_timeseries caching > 50 points into ResultRefStore."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = QueryTimeseriesInput(
        channel_selector=[
            ChannelSelector(asset_id=copilot_test_db["inv1"].id, canonical_signal="active_power"),
        ],
        start=copilot_test_db["base_time"],
        end=copilot_test_db["base_time"] + timedelta(hours=20),
        resolution="raw",
    )
    res = tool_query_timeseries(params, ctx, copilot_test_db["db"])

    # Over 50 points seeded, so data should not be returned inline
    assert res["total_points"] > 50
    assert "data" not in res
    assert "result_ref" in res
    ref_id = res["result_ref"]
    assert ref_id.startswith("ref_ts_")

    # Fetch full coordinates from default_result_store
    cached_data = default_result_store.get(ref_id)
    assert cached_data is not None
    assert len(cached_data[0]["data"]) == res["total_points"]


def test_tool_4_compute_kpi(copilot_test_db):
    """Test Tool 4: compute_kpi adhering to IEC 61724-1 standards."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = ComputeKPIInput(
        kpi_key="cuf",
        scope="plant",
        id=copilot_test_db["plant_a"].id,
        period="custom",
        start_date=copilot_test_db["base_time"],
        end_date=copilot_test_db["base_time"] + timedelta(days=1),
    )
    res = tool_compute_kpi(params, ctx, copilot_test_db["db"])

    assert res["kpi_key"] == "cuf"
    assert "value" in res
    assert res["unit"] == "%"
    assert res["standard"] == "IEC 61724-1"


def test_tool_5_compare_assets(copilot_test_db):
    """Test Tool 5: compare_assets ranking."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = CompareAssetsInput(
        target="active_power",
        asset_ids=[copilot_test_db["inv1"].id, copilot_test_db["inv2"].id],
        start_date=copilot_test_db["base_time"],
        end_date=copilot_test_db["base_time"] + timedelta(hours=10),
        stat="avg",
    )
    res = tool_compare_assets(params, ctx, copilot_test_db["db"])

    assert res["target"] == "active_power"
    assert len(res["ranked_assets"]) == 2
    # INV-01 was seeded with higher generation than INV-02
    assert res["ranked_assets"][0]["rank"] == 1
    assert res["ranked_assets"][0]["name"] == "INV-COPILOT-01"


def test_tool_6_list_anomalies(copilot_test_db):
    """Test Tool 6: list_anomalies."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = ListAnomaliesInput(
        plant_id=copilot_test_db["plant_a"].id,
        status="open",
        severity="high",
    )
    res = tool_list_anomalies(params, ctx, copilot_test_db["db"])

    assert res["total_returned"] >= 1
    assert res["anomalies"][0]["anomaly_id"] == str(copilot_test_db["anomaly"].id)
    assert res["anomalies"][0]["root_cause"] == "Module soiling and string clipping"


def test_tool_7_get_anomaly(copilot_test_db):
    """Test Tool 7: get_anomaly with in-depth context and peer pointers."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = GetAnomalyInput(anomaly_id=copilot_test_db["anomaly"].id)
    res = tool_get_anomaly(params, ctx, copilot_test_db["db"])

    assert res["anomaly_id"] == str(copilot_test_db["anomaly"].id)
    assert res["root_cause"] == "Module soiling and string clipping"
    assert "surrounding_context" in res
    assert "peer_comparison" in res["surrounding_context"]


def test_tool_8_list_events(copilot_test_db):
    """Test Tool 8: list_events."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = ListEventsInput(
        plant_id=copilot_test_db["plant_a"].id,
        event_type="warning",
    )
    res = tool_list_events(params, ctx, copilot_test_db["db"])

    assert res["total_returned"] >= 1
    assert res["events"][0]["message"] == "DC bus overvoltage transient detected."


def test_tool_9_detect_on_demand(copilot_test_db):
    """Test Tool 9: detect_on_demand ad-hoc algorithm execution."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = DetectOnDemandInput(
        method="zscore",
        channel_selector=ChannelSelector(
            asset_id=copilot_test_db["inv1"].id,
            canonical_signal="active_power",
        ),
        start_date=copilot_test_db["base_time"],
        end_date=copilot_test_db["base_time"] + timedelta(hours=10),
    )
    res = tool_detect_on_demand(params, ctx, copilot_test_db["db"])

    assert res["method"] == "zscore"
    assert res["points_evaluated"] > 0
    assert "detected_anomalies" in res
    assert res["execution_mode"] == "ephemeral_simulation"


def test_tool_10_render_chart_resolves_data_ref(copilot_test_db):
    """Test Tool 10: render_chart resolving data_ref from ResultRefStore."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)

    # Step 1: Query timeseries to produce a result_ref
    ts_params = QueryTimeseriesInput(
        channel_selector=[
            ChannelSelector(asset_id=copilot_test_db["inv1"].id, canonical_signal="active_power"),
        ],
        start=copilot_test_db["base_time"],
        end=copilot_test_db["base_time"] + timedelta(hours=5),
        resolution="raw",
    )
    ts_res = tool_query_timeseries(ts_params, ctx, copilot_test_db["db"])
    ref_id = ts_res["result_ref"]

    # Step 2: Render chart referencing that ref_id
    chart_spec = ChartSpec(
        title="INV-01 Daily Generation Curve",
        chart_type="line",
        series=[
            ChartSeriesSpec(
                name="INV-01 AC Power",
                data_ref=ref_id,
                color="#f59e0b",
            )
        ],
    )
    chart_input = RenderChartInput(spec=chart_spec)
    render_res = tool_render_chart(chart_input, ctx, copilot_test_db["db"])

    assert render_res["status"] == "rendered"
    chart_id = render_res["chart_id"]
    assert chart_id.startswith("chart_")

    # Verify chart is cached in default_chart_store with resolved coordinates
    cached_chart = default_chart_store.get(chart_id)
    assert cached_chart is not None
    assert cached_chart["title"] == "INV-01 Daily Generation Curve"
    assert len(cached_chart["series"][0]["data"]) > 0


def test_tool_11_get_data_coverage(copilot_test_db):
    """Test Tool 11: get_data_coverage telemetry completeness."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = GetDataCoverageInput(
        plant_id=copilot_test_db["plant_a"].id,
        start_date=copilot_test_db["base_time"],
        end_date=copilot_test_db["base_time"] + timedelta(hours=10),
        canonical_signals=["active_power", "poa_irradiance"],
    )
    res = tool_get_data_coverage(params, ctx, copilot_test_db["db"])

    assert res["plant_id"] == str(copilot_test_db["plant_a"].id)
    assert "active_power" in res["signals"]
    assert res["signals"]["active_power"]["completeness_pct"] > 0.0


def test_tool_12_get_current_time(copilot_test_db):
    """Test Tool 12: get_current_time timezone and daylight calculation."""
    ctx = ToolSecurityContext(copilot_test_db["org_a"].id)
    params = GetCurrentTimeInput(plant_id=copilot_test_db["plant_a"].id)
    res = tool_get_current_time(params, ctx, copilot_test_db["db"])

    assert res["plant_timezone"] == "Asia/Kolkata"
    assert "server_time_utc" in res
    assert "plant_local_time" in res
    assert "is_daylight" in res
    assert "solar_elevation_deg" in res


# ---------------------------------------------------------------------------
# 5. REST API Integration Tests
# ---------------------------------------------------------------------------

def test_api_list_tools(client, copilot_test_db):
    """Test GET /api/v1/copilot/tools."""
    headers = {"Authorization": f"Bearer {copilot_test_db['token_a']}"}
    resp = client.get("/copilot/tools", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 12
    tool_names = [t["name"] for t in data["tools"]]
    assert "query_timeseries" in tool_names
    assert "render_chart" in tool_names


def test_api_execute_tool_success(client, copilot_test_db):
    """Test POST /api/v1/copilot/tools/execute with valid payload."""
    headers = {"Authorization": f"Bearer {copilot_test_db['token_a']}"}
    payload = {
        "tool": "get_current_time",
        "plant_id": str(copilot_test_db["plant_a"].id),
        "arguments": {"plant_id": str(copilot_test_db["plant_a"].id)},
    }
    resp = client.post("/copilot/tools/execute", json=payload, headers=headers)
    assert resp.status_code == 200
    res = resp.json()
    assert res["success"] is True
    assert res["tool"] == "get_current_time"
    assert res["data"]["plant_timezone"] == "Asia/Kolkata"


def test_api_execute_tool_cross_org_forbidden(client, copilot_test_db):
    """Test POST /api/v1/copilot/tools/execute cross-tenant rejection returns 403."""
    # User B attempts to access Plant A
    headers = {"Authorization": f"Bearer {copilot_test_db['token_b']}"}
    payload = {
        "tool": "get_plant_summary",
        "plant_id": str(copilot_test_db["plant_a"].id),
        "arguments": {"plant_id": str(copilot_test_db["plant_a"].id)},
    }
    resp = client.post("/copilot/tools/execute", json=payload, headers=headers)
    assert resp.status_code == 403


def test_api_cached_result_and_chart_endpoints(client, copilot_test_db):
    """Test GET /api/v1/copilot/results/{ref_id} and /charts/{chart_id}."""
    headers = {"Authorization": f"Bearer {copilot_test_db['token_a']}"}

    # Store dummy result
    ref_id = default_result_store.put([{"x": 1, "y": 2}], prefix="ref_ts")
    resp_res = client.get(f"/copilot/results/{ref_id}", headers=headers)
    assert resp_res.status_code == 200
    assert resp_res.json() == [{"x": 1, "y": 2}]

    # Store dummy chart
    chart_id = default_chart_store.put({"title": "Test Chart", "series": []}, prefix="chart")
    resp_chart = client.get(f"/copilot/charts/{chart_id}", headers=headers)
    assert resp_chart.status_code == 200
    assert resp_chart.json()["title"] == "Test Chart"
