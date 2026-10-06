"""Unit Tests for Solar KPI Pure Functions (§11, Task S3-AI-01).

Validates:
- Energy (E_ac): Riemann sums, energy counters, interval scaling, and coverage percentages.
- Specific Yield (Y): Y = E_ac / P_dc,rated math and division-by-zero guards.
- Performance Ratio (PR): PR = E_ac / (P_dc,rated * G_poa / G_stc) math and approx_ghi flag semantics.
- Capacity Utilization Factor (CUF): CUF = E_ac / (P_ac,rated * H) on AC capacity basis.
- Time-based Availability (A): Daylight filtering (POA > 50 W/m²), debounce trip windows (> 2 intervals), and explicit status offline.
- Inverter Efficiency (η): η = E_ac / E_dc and missing DC channel guards.
- Estimated Energy Loss (L): L = (PR_expected - PR_actual) * P_dc,rated * G_poa / G_stc and zero-floor bounding.
- Input Coverage Flags: Low confidence (< 70%) and insufficient data (None instead of zero).
"""

from __future__ import annotations

import math
from typing import List, Optional
import pytest

from app.ai.kpi_engine import (
    FLAG_APPROX_GHI,
    FLAG_INSUFFICIENT_DATA,
    FLAG_LOW_CONFIDENCE,
    KPIKey,
    calculate_availability,
    calculate_cuf,
    calculate_energy_ac,
    calculate_energy_ac_from_counter,
    calculate_energy_loss,
    calculate_inverter_efficiency,
    calculate_performance_ratio,
    calculate_specific_yield,
    compute_coverage,
    compute_inverter_solar_kpis,
    compute_plant_solar_kpis,
    evaluate_coverage_flags,
    integrate_irradiation_kwh_m2,
)


# ---------------------------------------------------------------------------
# 1. Energy (E_ac) Pure Function Tests
# ---------------------------------------------------------------------------


def test_energy_ac_constant_power_hand_computed() -> None:
    """Fixture: 4 intervals (1 hr) at constant 1,000,000 W (1000 kW) with 15m cadence (0.25h).

    Manual Math:
        E_ac = 1000 kW * 0.25 h * 4 intervals = 1,000.0 kWh.
    """
    power_watts = [1_000_000.0, 1_000_000.0, 1_000_000.0, 1_000_000.0]
    res = calculate_energy_ac(power_watts, interval_hours=0.25, unit="W", expected_count=4)

    assert res.value == 1000.0
    assert res.coverage == 1.0
    assert res.flags == []
    assert res.unit == "kWh"
    assert res.is_valid is True


def test_energy_ac_triangle_profile_hand_computed() -> None:
    """Fixture: 5 readings at [0, 500, 1000, 500, 0] kW.

    Manual Math:
        E_ac = (0*0.25 + 500*0.25 + 1000*0.25 + 500*0.25 + 0*0.25) = 500.0 kWh.
    """
    power_kw = [0.0, 500.0, 1000.0, 500.0, 0.0]
    res = calculate_energy_ac(power_kw, interval_hours=0.25, unit="kW", expected_count=5)

    assert res.value == 500.0
    assert res.coverage == 1.0
    assert res.flags == []


def test_energy_ac_counter_reset_and_monotonic() -> None:
    """Fixture: Monotonic daily counter (Wh) resetting at midnight.

    Manual Math:
        Counter starts at 0, ends at 1,500,000 Wh -> 1,500.0 kWh.
    """
    counter_wh = [0.0, 300_000.0, 800_000.0, 1_500_000.0]
    res = calculate_energy_ac_from_counter(counter_wh, unit="Wh", expected_count=4)

    assert res.value == 1500.0
    assert res.coverage == 1.0
    assert res.unit == "kWh"


def test_energy_ac_counter_with_rollover() -> None:
    """Fixture: Counter experiences firmware restart / reset mid-day."""
    counter_kwh = [100.0, 150.0, 10.0, 60.0]
    # Delta 1: 150 - 100 = 50
    # Reset at step 2: 10
    # Delta 3: 60 - 10 = 50
    # Total = 50 + 10 + 50 = 110 kWh
    res = calculate_energy_ac_from_counter(counter_kwh, unit="kWh", expected_count=4)
    assert res.value == 110.0


def test_energy_ac_low_confidence_flag() -> None:
    """Fixture: 48 readings present out of 96 expected (50% coverage < 70%)."""
    power_kw: List[Optional[float]] = [100.0] * 48
    res = calculate_energy_ac(power_kw, interval_hours=0.25, unit="kW", expected_count=96)

    assert res.coverage == 0.50
    assert FLAG_LOW_CONFIDENCE in res.flags
    assert res.is_low_confidence is True
    assert res.value == 100.0 * 0.25 * 48  # 1200.0 kWh


def test_energy_ac_empty_input_insufficient_data() -> None:
    """Fixture: Zero readings present -> must return None and insufficient_data flag, NEVER zero."""
    res = calculate_energy_ac([], expected_count=96)

    assert res.value is None
    assert res.coverage == 0.0
    assert FLAG_INSUFFICIENT_DATA in res.flags
    assert res.is_valid is False


# ---------------------------------------------------------------------------
# 2. Specific Yield (Y) Pure Function Tests
# ---------------------------------------------------------------------------


def test_specific_yield_hand_computed() -> None:
    """Fixture: E_ac = 5,500 kWh, P_dc,rated = 1,000 kWp.

    Manual Math:
        Y = 5500 / 1000 = 5.50 kWh/kWp (Kaggle Surya-A summer benchmark).
    """
    res = calculate_specific_yield(energy_ac_kwh=5500.0, capacity_dc_kwp=1000.0)

    assert res.value == 5.50
    assert res.unit == "kWh/kWp"
    assert res.flags == []
    assert res.coverage == 1.0


def test_specific_yield_zero_capacity_guard() -> None:
    """Fixture: P_dc,rated = 0 -> insufficient_data, value is None."""
    res = calculate_specific_yield(energy_ac_kwh=5500.0, capacity_dc_kwp=0.0)

    assert res.value is None
    assert FLAG_INSUFFICIENT_DATA in res.flags


def test_specific_yield_none_energy_guard() -> None:
    """Fixture: Upstream energy calculation failed (E_ac is None)."""
    res = calculate_specific_yield(energy_ac_kwh=None, capacity_dc_kwp=1250.0)

    assert res.value is None
    assert FLAG_INSUFFICIENT_DATA in res.flags


# ---------------------------------------------------------------------------
# 3. Performance Ratio (PR) Pure Function Tests
# ---------------------------------------------------------------------------


def test_performance_ratio_hand_computed() -> None:
    """Fixture: E_ac = 4,290 kWh, P_dc,rated = 1,000 kWp, G_poa = 5.5 kWh/m².

    Manual Math:
        E_expected = 1,000 kWp * (5.5 / 1.0) = 5,500 kWh.
        PR = 4,290 / 5,500 = 0.78 (78.0%).
    """
    res = calculate_performance_ratio(
        energy_ac_kwh=4290.0,
        capacity_dc_kwp=1000.0,
        irradiation_poa_kwh_m2=5.5,
    )

    assert res.value == 0.78
    assert res.unit == "ratio"
    assert res.flags == []
    assert res.details["expected_energy_kwh"] == 5500.0


def test_performance_ratio_approx_ghi_flag() -> None:
    """Fixture: Horizontal pyranometer (GHI) used instead of POA tilt."""
    res = calculate_performance_ratio(
        energy_ac_kwh=4290.0,
        capacity_dc_kwp=1000.0,
        irradiation_poa_kwh_m2=5.5,
        is_ghi=True,
    )

    assert res.value == 0.78
    assert FLAG_APPROX_GHI in res.flags


def test_performance_ratio_nighttime_zero_irradiance() -> None:
    """Fixture: G_poa = 0.0 -> insufficient_data, value is None."""
    res = calculate_performance_ratio(
        energy_ac_kwh=0.0,
        capacity_dc_kwp=1000.0,
        irradiation_poa_kwh_m2=0.0,
    )

    assert res.value is None
    assert FLAG_INSUFFICIENT_DATA in res.flags


# ---------------------------------------------------------------------------
# 4. Capacity Utilization Factor (CUF) Pure Function Tests
# ---------------------------------------------------------------------------


def test_cuf_hand_computed() -> None:
    """Fixture: E_ac = 5,280 kWh, P_ac,rated = 1,000 kW, H = 24.0 hours.

    Manual Math:
        Max energy = 1,000 * 24 = 24,000 kWh.
        CUF = 5,280 / 24,000 = 0.22 (22.0%).
    """
    res = calculate_cuf(
        energy_ac_kwh=5280.0,
        capacity_ac_kw=1000.0,
        period_hours=24.0,
    )

    assert res.value == 0.22
    assert res.unit == "ratio"
    assert res.flags == []


def test_cuf_zero_period_or_capacity_guard() -> None:
    """Fixture: Zero capacity or zero period hours."""
    res = calculate_cuf(energy_ac_kwh=100.0, capacity_ac_kw=0.0)
    assert res.value is None
    assert FLAG_INSUFFICIENT_DATA in res.flags


# ---------------------------------------------------------------------------
# 5. Time-based Availability (A) Pure Function Tests
# ---------------------------------------------------------------------------


def test_availability_hand_computed_with_inverter_trip() -> None:
    """Fixture (§11):
    - 40 daylight intervals (POA > 50 W/m²). Cadence 0.25h -> 10.0 daylight hours.
    - Intervals 0..19: Normal generation (1000 W).
    - Intervals 20..23 (4 consecutive intervals): Inverter trips, P_ac = 0 W.
      Since run length 4 > 2 threshold, all 4 intervals count as downtime (1.0 hour).
    - Intervals 24..34: Normal generation.
    - Interval 35 (1 isolated interval): P_ac = 0 W, then normal at 36..39.
      Since run length 1 <= 2 debounce threshold, NOT counted as downtime.

    Manual Math:
        Downtime = 4 intervals * 0.25 h = 1.0 h.
        Daylight = 40 intervals * 0.25 h = 10.0 h.
        A = 1 - (1.0 / 10.0) = 0.90 (90.0%).
    """
    poa_wm2 = [100.0] * 40
    power_w = [1000.0] * 20 + [0.0] * 4 + [1000.0] * 11 + [0.0] * 1 + [1000.0] * 4

    res = calculate_availability(
        irradiance_poa_wm2=poa_wm2,
        power_ac_w=power_w,
        interval_hours=0.25,
        expected_count=40,
    )

    assert res.value == 0.90
    assert res.unit == "ratio"
    assert res.details["downtime_hours"] == 1.0
    assert res.details["daylight_hours"] == 10.0


def test_availability_explicit_status_offline() -> None:
    """Fixture: Inverter explicitly tagged offline for 8 daylight intervals.

    Manual Math:
        Daylight intervals = 40 (10.0 h).
        Downtime intervals = 8 (2.0 h).
        A = 1 - (2.0 / 10.0) = 0.80 (80.0%).
    """
    poa_wm2 = [200.0] * 40
    power_w = [500.0] * 40
    status_offline = [False] * 32 + [True] * 8

    res = calculate_availability(
        irradiance_poa_wm2=poa_wm2,
        power_ac_w=power_w,
        status_offline=status_offline,
        interval_hours=0.25,
        expected_count=40,
    )

    assert res.value == 0.80
    assert res.details["downtime_hours"] == 2.0


def test_availability_zero_daylight_hours_guard() -> None:
    """Fixture: All readings at night (POA < 50 W/m²)."""
    poa_wm2 = [10.0] * 40
    power_w = [0.0] * 40

    res = calculate_availability(
        irradiance_poa_wm2=poa_wm2,
        power_ac_w=power_w,
    )

    assert res.value is None
    assert FLAG_INSUFFICIENT_DATA in res.flags


# ---------------------------------------------------------------------------
# 6. Inverter Efficiency (η) Pure Function Tests
# ---------------------------------------------------------------------------


def test_inverter_efficiency_hand_computed() -> None:
    """Fixture: E_ac = 4,892.5 kWh, E_dc = 5,000.0 kWh.

    Manual Math:
        η = 4,892.5 / 5,000.0 = 0.9785 (97.85% commercial central inverter efficiency).
    """
    res = calculate_inverter_efficiency(energy_ac_kwh=4892.5, energy_dc_kwh=5000.0)

    assert res.value == 0.9785
    assert res.unit == "ratio"
    assert res.flags == []


def test_inverter_efficiency_missing_dc_channel_guard() -> None:
    """Fixture: No DC channel available (energy_dc_kwh is None or 0)."""
    res = calculate_inverter_efficiency(energy_ac_kwh=4892.5, energy_dc_kwh=None)

    assert res.value is None
    assert FLAG_INSUFFICIENT_DATA in res.flags


# ---------------------------------------------------------------------------
# 7. Estimated Energy Loss (L) Pure Function Tests
# ---------------------------------------------------------------------------


def test_energy_loss_hand_computed() -> None:
    """Fixture:
    - PR_expected = 0.78 (78%)
    - PR_actual = 0.70 (70%)
    - P_dc,rated = 1,000 kWp
    - G_poa = 5.5 kWh/m²
    - G_stc = 1.0 kW/m²

    Manual Math:
        Expected Energy = 1,000 * 5.5 = 5,500 kWh.
        Delta PR = 0.78 - 0.70 = 0.08 (8%).
        Loss L = 0.08 * 5,500 = 440.0 kWh.
    """
    res = calculate_energy_loss(
        pr_actual=0.70,
        pr_expected=0.78,
        capacity_dc_kwp=1000.0,
        irradiation_poa_kwh_m2=5.5,
    )

    assert res.value == 440.0
    assert res.unit == "kWh"
    assert res.flags == []


def test_energy_loss_overperforming_bounded_zero() -> None:
    """Fixture: Plant outperforms target (PR_actual 0.82 >= PR_expected 0.78).

    Loss must be floored at 0.0 kWh.
    """
    res = calculate_energy_loss(
        pr_actual=0.82,
        pr_expected=0.78,
        capacity_dc_kwp=1000.0,
        irradiation_poa_kwh_m2=5.5,
        floor_zero=True,
    )

    assert res.value == 0.0


def test_energy_loss_missing_pr_guard() -> None:
    """Fixture: Missing actual PR -> insufficient_data."""
    res = calculate_energy_loss(
        pr_actual=None,
        pr_expected=0.78,
        capacity_dc_kwp=1000.0,
        irradiation_poa_kwh_m2=5.5,
    )

    assert res.value is None
    assert FLAG_INSUFFICIENT_DATA in res.flags


# ---------------------------------------------------------------------------
# 8. Integrated Inverter & Plant Rollup Tests
# ---------------------------------------------------------------------------


def test_integrate_irradiation_kwh_m2() -> None:
    """Fixture: 4 readings at 1000 W/m² (1 kW/m²) at 0.25h cadence -> 1.0 kWh/m²."""
    irr_wm2 = [1000.0, 1000.0, 1000.0, 1000.0]
    total_kwh_m2, count = integrate_irradiation_kwh_m2(irr_wm2, interval_hours=0.25)

    assert total_kwh_m2 == 1.0
    assert count == 4


def test_compute_inverter_solar_kpis_integrated() -> None:
    """Verify integrated computation of all 7 KPIs for an inverter."""
    power_ac = [1000_000.0] * 40 + [0.0] * 56  # 40 intervals of 1000 kW
    power_dc = [1020_000.0] * 40 + [0.0] * 56  # 40 intervals of 1020 kW
    poa_wm2 = [800.0] * 40 + [0.0] * 56        # 40 intervals of 800 W/m²

    kpis = compute_inverter_solar_kpis(
        power_ac_w=power_ac,
        power_dc_w=power_dc,
        irradiance_poa_wm2=poa_wm2,
        capacity_dc_kwp=1250.0,
        capacity_ac_kw=1250.0,
        expected_pr=0.78,
        interval_hours=0.25,
        expected_count=96,
    )

    # 1. Energy: 1000 kW * 0.25 h * 40 = 10,000 kWh
    assert kpis[KPIKey.ENERGY_AC.value].value == 10000.0
    # 2. Specific yield: 10,000 / 1250 = 8.0 kWh/kWp
    assert kpis[KPIKey.SPECIFIC_YIELD.value].value == 8.0
    # 3. PR: POA = 800 * 0.25 * 40 / 1000 = 8.0 kWh/m²; Expected = 1250 * 8.0 = 10,000 kWh -> PR = 1.0
    assert kpis[KPIKey.PERFORMANCE_RATIO.value].value == 1.0
    # 4. CUF: 10,000 / (1250 * 24) = 10,000 / 30,000 = 0.3333
    assert kpis[KPIKey.CUF.value].value == 0.3333
    # 5. Availability: no downtime during daylight -> 1.0
    assert kpis[KPIKey.AVAILABILITY.value].value == 1.0
    # 6. Efficiency: 10,000 / 10,200 = 0.9804
    assert kpis[KPIKey.INVERTER_EFFICIENCY.value].value == 0.9804
    # 7. Energy Loss: PR actual 1.0 > expected 0.78 -> 0.0
    assert kpis[KPIKey.ENERGY_LOSS.value].value == 0.0


def test_compute_plant_solar_kpis_rollup() -> None:
    """Verify multi-inverter rollup to plant level."""
    power_ac_1 = [500_000.0] * 40 + [0.0] * 56
    power_ac_2 = [500_000.0] * 40 + [0.0] * 56
    poa_wm2 = [800.0] * 40 + [0.0] * 56

    inv1 = compute_inverter_solar_kpis(
        power_ac_w=power_ac_1,
        irradiance_poa_wm2=poa_wm2,
        capacity_dc_kwp=625.0,
        capacity_ac_kw=625.0,
        expected_pr=0.78,
    )
    inv2 = compute_inverter_solar_kpis(
        power_ac_w=power_ac_2,
        irradiance_poa_wm2=poa_wm2,
        capacity_dc_kwp=625.0,
        capacity_ac_kw=625.0,
        expected_pr=0.78,
    )

    plant_kpis = compute_plant_solar_kpis(
        inverter_kpis={"INV-01": inv1, "INV-02": inv2},
        plant_capacity_dc_kwp=1250.0,
        plant_capacity_ac_kw=1250.0,
        plant_expected_pr=0.78,
        irradiation_poa_kwh_m2=8.0,
    )

    # Combined energy: 5000 + 5000 = 10,000 kWh
    assert plant_kpis[KPIKey.ENERGY_AC.value].value == 10000.0
    # Combined specific yield: 10,000 / 1250 = 8.0 kWh/kWp
    assert plant_kpis[KPIKey.SPECIFIC_YIELD.value].value == 8.0
    # Combined PR: 1.0
    assert plant_kpis[KPIKey.PERFORMANCE_RATIO.value].value == 1.0
    # Combined Availability: 1.0
    assert plant_kpis[KPIKey.AVAILABILITY.value].value == 1.0
