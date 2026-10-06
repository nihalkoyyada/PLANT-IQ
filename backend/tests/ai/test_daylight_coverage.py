"""Unit & Integration Tests for Daylight Filtering, Coverage Logic & Flag Semantics (§11, Task S3-AI-02).

Validates:
1. Daylight Filtering:
   - Threshold checks (POA > 50 W/m² cutoff, NaN/None guards).
   - Boolean daylight masks and series filtering (filtering out nighttime zero-values).
   - Daylight duration (H_daylight) calculation.
   - Daylight-filtered Performance Ratio (PR) vs raw unweighted.
   - Zero daylight hours guard (returns None with 'insufficient_data', never silent zero).
   - Daylight CUF (CUF_daylight) vs 24h CUF hand-computed fixtures.

2. Coverage Percentages:
   - Expected vs actual interval coverage computation.
   - Daylight-specific coverage calculation.
   - Bounds and precision enforcement [0.0, 1.0].

3. Flag Semantics & Data Quality Enforcement:
   - Missing or sparse data rule: NEVER silently output a zero.
   - Coverage < 70% tags 'low_confidence'.
   - Required coverage threshold (< 70%) tags 'insufficient_data' and nullifies value.
   - approx_ghi flag presence when using horizontal pyranometer.
   - enforce_data_quality helper function.
"""

from __future__ import annotations

import math
from typing import List, Optional

import pytest

from app.ai.kpi_engine import (
    DEFAULT_DAYLIGHT_THRESHOLD_WM2,
    FLAG_APPROX_GHI,
    FLAG_INSUFFICIENT_DATA,
    FLAG_LOW_CONFIDENCE,
    MIN_CONFIDENCE_COVERAGE_THRESHOLD,
    MIN_COVERAGE_THRESHOLD,
    KPIKey,
    KPIResult,
    calculate_availability,
    calculate_cuf,
    calculate_daylight_cuf,
    calculate_daylight_hours,
    calculate_daylight_pr,
    calculate_energy_ac,
    calculate_performance_ratio,
    calculate_specific_yield,
    compute_coverage,
    compute_daylight_coverage,
    compute_inverter_solar_kpis,
    enforce_data_quality,
    evaluate_coverage_flags,
    filter_daylight_series,
    get_daylight_mask,
    is_daylight,
)


# ===========================================================================
# 1. Daylight Filtering Pure Functions (§11, S3-AI-02)
# ===========================================================================


def test_is_daylight_threshold_and_guards() -> None:
    """Verify daylight thresholding (> 50 W/m²) and edge guards."""
    assert is_daylight(50.1) is True
    assert is_daylight(100.0) is True
    assert is_daylight(50.0) is False   # Exact threshold is not strictly greater
    assert is_daylight(49.9) is False
    assert is_daylight(0.0) is False
    assert is_daylight(-1.0) is False
    assert is_daylight(None) is False
    assert is_daylight(float("nan")) is False

    # Custom threshold
    assert is_daylight(25.0, threshold_wm2=20.0) is True
    assert is_daylight(15.0, threshold_wm2=20.0) is False


def test_get_daylight_mask_and_filter_series() -> None:
    """Verify boolean masking and series filtering for telemetry."""
    # 8 intervals: 2 night, 4 day, 2 night
    poa_wm2: List[Optional[float]] = [0.0, 20.0, 100.0, 500.0, 800.0, 60.0, 30.0, 0.0]
    power_kw: List[Optional[float]] = [0.0, 0.0, 100.0, 500.0, 800.0, 50.0, 0.0, 0.0]

    mask = get_daylight_mask(poa_wm2, threshold_wm2=50.0)
    assert mask == [False, False, True, True, True, True, False, False]

    filtered_power, filtered_poa = filter_daylight_series(power_kw, poa_wm2, threshold_wm2=50.0)
    assert filtered_power == [100.0, 500.0, 800.0, 50.0]
    assert filtered_poa == [100.0, 500.0, 800.0, 60.0]


def test_calculate_daylight_hours() -> None:
    """Verify active daylight duration calculation (0.25h cadence)."""
    # 40 daylight intervals = 10.0 hours
    poa_wm2 = [0.0] * 20 + [200.0] * 40 + [0.0] * 36
    daylight_hours = calculate_daylight_hours(poa_wm2, interval_hours=0.25)
    assert daylight_hours == 10.0


def test_daylight_pr_hand_computed() -> None:
    """Hand-computed fixture: Daylight-filtered PR filters out night zeros.

    Plant:
        P_dc,rated = 1,000 kWp.
        Cadence = 0.25 h (15 min).
    Profile:
        - 20 nighttime intervals: P_ac = 0 kW, POA = 0 W/m².
        - 40 daylight intervals:  P_ac = 780 kW, POA = 1000 W/m² (1.0 kW/m²).
        - 36 nighttime intervals: P_ac = 0 kW, POA = 0 W/m².

    Manual Math:
        Daylight Energy E_ac = 780 kW * 0.25 h * 40 = 7,800 kWh.
        Daylight Irradiation G_poa = 1.0 kW/m² * 0.25 h * 40 = 10.0 kWh/m².
        Reference Energy = 1,000 kWp * (10.0 / 1.0) = 10,000 kWh.
        PR = 7,800 / 10,000 = 0.78 (78.0%).
    """
    power_w = [0.0] * 20 + [780_000.0] * 40 + [0.0] * 36
    poa_wm2 = [0.0] * 20 + [1000.0] * 40 + [0.0] * 36

    res = calculate_daylight_pr(
        power_ac=power_w,
        irradiance_poa_wm2=poa_wm2,
        capacity_dc_kwp=1000.0,
        interval_hours=0.25,
        power_unit="W",
    )

    assert res.value == 0.78
    assert res.unit == "ratio"
    assert res.flags == []
    assert res.details["daylight_intervals"] == 40
    assert res.details["daylight_hours"] == 10.0


def test_daylight_pr_zero_daylight_guard() -> None:
    """Fixture: Polar night or disconnected pyranometer -> zero daylight intervals.

    Must return value=None and tag 'insufficient_data', NEVER silent zero.
    """
    power_w = [0.0] * 96
    poa_wm2 = [0.0] * 96  # All 0 W/m² <= 50 W/m²

    res = calculate_daylight_pr(
        power_ac=power_w,
        irradiance_poa_wm2=poa_wm2,
        capacity_dc_kwp=1000.0,
    )

    assert res.value is None
    assert FLAG_INSUFFICIENT_DATA in res.flags
    assert res.is_valid is False
    assert res.details["daylight_intervals"] == 0


def test_daylight_cuf_hand_computed() -> None:
    """Hand-computed fixture: 24h CUF vs Daylight CUF.

    Plant:
        P_ac,rated = 1,000 kW.
        E_ac = 4,000 kWh generated over 8 daylight hours (H_daylight = 8.0 h).

    Manual Math:
        Standard 24h CUF = 4,000 / (1,000 * 24.0) = 0.1667 (16.67%).
        Daylight CUF     = 4,000 / (1,000 * 8.0)  = 0.5000 (50.00%).
    """
    # 1. Standard 24h CUF
    res_24h = calculate_cuf(
        energy_ac_kwh=4000.0,
        capacity_ac_kw=1000.0,
        period_hours=24.0,
        daylight_only=False,
    )
    assert res_24h.kpi_key == KPIKey.CUF.value
    assert res_24h.value == 0.1667

    # 2. Daylight CUF via calculate_daylight_cuf
    res_dl = calculate_daylight_cuf(
        energy_ac_kwh=4000.0,
        capacity_ac_kw=1000.0,
        daylight_hours=8.0,
    )
    assert res_dl.kpi_key == KPIKey.CUF_DAYLIGHT.value
    assert res_dl.value == 0.5000
    assert res_dl.details["effective_hours"] == 8.0
    assert res_dl.details["daylight_only"] is True


def test_daylight_cuf_zero_daylight_hours_guard() -> None:
    """Fixture: H_daylight = 0.0 -> must return None with 'insufficient_data', NEVER zero."""
    res = calculate_daylight_cuf(
        energy_ac_kwh=100.0,
        capacity_ac_kw=1000.0,
        daylight_hours=0.0,
    )
    assert res.value is None
    assert FLAG_INSUFFICIENT_DATA in res.flags
    assert res.is_valid is False


# ===========================================================================
# 2. Coverage Percentages Logic (§11, S3-AI-02)
# ===========================================================================


def test_compute_coverage_fractions() -> None:
    """Verify input coverage percentage computation."""
    # 96 expected intervals (15-min over 24h)
    assert compute_coverage(96, 96) == 1.0
    assert compute_coverage(72, 96) == 0.75
    assert compute_coverage(48, 96) == 0.50
    assert compute_coverage(0, 96) == 0.0

    # Bounds checking
    assert compute_coverage(100, 96) == 1.0  # Capped at 1.0
    assert compute_coverage(0, 0) == 0.0
    assert compute_coverage(5, 0) == 1.0


def test_compute_daylight_coverage() -> None:
    """Verify daylight-specific coverage computation."""
    # 40 expected daylight intervals, 30 readings arrived
    assert compute_daylight_coverage(30, 40) == 0.75
    assert compute_daylight_coverage(40, 40) == 1.0
    assert compute_daylight_coverage(10, 40) == 0.25


# ===========================================================================
# 3. Flag Semantics & Data Quality Enforcement (§11, S3-AI-02)
# ===========================================================================


def test_evaluate_coverage_flags_semantics() -> None:
    """Verify flag tagging across coverage boundaries."""
    # 1. High coverage (>= 70%) -> Clean flags
    flags_high = evaluate_coverage_flags(0.85)
    assert flags_high == []

    # 2. Boundary coverage (exact 70%) -> Clean flags
    flags_boundary = evaluate_coverage_flags(0.70)
    assert flags_boundary == []

    # 3. Sparse data (< 70%) -> 'low_confidence' flag
    flags_sparse = evaluate_coverage_flags(0.69)
    assert flags_sparse == [FLAG_LOW_CONFIDENCE]

    flags_half = evaluate_coverage_flags(0.50)
    assert flags_half == [FLAG_LOW_CONFIDENCE]

    # 4. Strict threshold enforcement (< 70%) -> 'insufficient_data' flag
    flags_enforced = evaluate_coverage_flags(
        0.65, min_insufficient_threshold=0.70
    )
    assert FLAG_INSUFFICIENT_DATA in flags_enforced

    # 5. Existing flags preservation (e.g. approx_ghi)
    flags_combined = evaluate_coverage_flags(
        0.50, base_flags=[FLAG_APPROX_GHI]
    )
    assert FLAG_APPROX_GHI in flags_combined
    assert FLAG_LOW_CONFIDENCE in flags_combined


def test_never_silently_output_zero_on_missing_inputs() -> None:
    """Enforce the project rule: missing or sparse data must NEVER silently output a zero (§11, S3-AI-02)."""
    # 1. AC Energy with empty readings
    res_energy = calculate_energy_ac([])
    assert res_energy.value is None
    assert res_energy.value != 0.0
    assert FLAG_INSUFFICIENT_DATA in res_energy.flags

    # 2. Specific Yield with None energy
    res_yield = calculate_specific_yield(energy_ac_kwh=None, capacity_dc_kwp=1000.0)
    assert res_yield.value is None
    assert FLAG_INSUFFICIENT_DATA in res_yield.flags

    # 3. PR with missing irradiance
    res_pr = calculate_performance_ratio(
        energy_ac_kwh=1000.0, capacity_dc_kwp=1000.0, irradiation_poa_kwh_m2=None
    )
    assert res_pr.value is None
    assert FLAG_INSUFFICIENT_DATA in res_pr.flags

    # 4. CUF with missing energy
    res_cuf = calculate_cuf(energy_ac_kwh=None, capacity_ac_kw=1000.0)
    assert res_cuf.value is None
    assert FLAG_INSUFFICIENT_DATA in res_cuf.flags

    # 5. Availability with zero daylight
    res_avail = calculate_availability(irradiance_poa_wm2=[0.0] * 10, power_ac_w=[0.0] * 10)
    assert res_avail.value is None
    assert FLAG_INSUFFICIENT_DATA in res_avail.flags


def test_enforce_data_quality_nullifies_sparse_data() -> None:
    """Verify enforce_data_quality nullifies metrics with coverage below threshold (< 70%)."""
    # Metric with 50% coverage (< 70% threshold)
    low_cov_kpi = KPIResult(
        kpi_key="pr",
        value=0.75,
        coverage=0.50,
        flags=[FLAG_LOW_CONFIDENCE],
        unit="ratio",
    )

    enforced = enforce_data_quality(low_cov_kpi, min_coverage_threshold=0.70)

    # Must be nullified and tagged as insufficient_data
    assert enforced.value is None
    assert FLAG_INSUFFICIENT_DATA in enforced.flags
    assert enforced.is_valid is False
    assert enforced.details["sparse_data_nullified"] is True

    # High coverage metric (85% >= 70%) remains intact
    high_cov_kpi = KPIResult(
        kpi_key="pr",
        value=0.78,
        coverage=0.85,
        flags=[],
        unit="ratio",
    )
    intact = enforce_data_quality(high_cov_kpi, min_coverage_threshold=0.70)
    assert intact.value == 0.78
    assert intact.flags == []
    assert intact.is_valid is True


def test_compute_inverter_solar_kpis_with_daylight_filtering() -> None:
    """Verify compute_inverter_solar_kpis computes daylight-filtered metrics and daylight coverage."""
    # 40 daylight intervals (06:00 - 16:00), 56 night intervals
    poa_wm2 = [0.0] * 20 + [800.0] * 40 + [0.0] * 36
    power_ac_w = [0.0] * 20 + [1000_000.0] * 40 + [0.0] * 36

    kpis = compute_inverter_solar_kpis(
        power_ac_w=power_ac_w,
        irradiance_poa_wm2=poa_wm2,
        capacity_dc_kwp=1250.0,
        capacity_ac_kw=1250.0,
        filter_daylight=True,
    )

    # Standard 24h CUF: 10,000 / (1250 * 24) = 0.3333
    assert kpis[KPIKey.CUF.value].value == 0.3333

    # Details must report active daylight duration & daylight CUF
    cuf_details = kpis[KPIKey.CUF.value].details
    assert cuf_details["daylight_hours"] == 10.0
    # Daylight CUF: 10,000 / (1250 * 10) = 0.8000
    assert cuf_details["daylight_cuf"] == 0.8000

    # Availability has 0 downtime during daylight -> 1.0
    assert kpis[KPIKey.AVAILABILITY.value].value == 1.0
    assert kpis[KPIKey.AVAILABILITY.value].details["daylight_hours"] == 10.0
