"""Solar Performance KPI Engine (§11).

Task: S3-AI-01
Implements pure Python functions for Solar Pack v1 KPIs:
- Energy (E_ac): AC energy (kWh) over period from Riemann-sum integrated AC power or energy counters.
- Specific Yield (Y): Y = E_ac / P_dc,rated (kWh/kWp).
- Performance Ratio (PR): PR = E_ac / (P_dc,rated * G_poa / G_stc), with approx_ghi flag support.
- Capacity Utilization Factor (CUF): CUF = E_ac / (P_ac,rated * H), AC capacity basis over period hours H.
- Time-based Availability (A): A = 1 - (downtime during daylight / daylight hours),
  where downtime = status offline OR (POA > 50 W/m² AND P_ac ≈ 0 for > 2 intervals).
- Inverter Efficiency (η): η = E_ac / E_dc, daylight-filtered where DC power channel exists.
- Estimated Energy Loss (L): L = (PR_expected - PR_actual) * P_dc,rated * G_poa / G_stc.

Follows Section §11 rules:
- Daylight-filtered data where relevant.
- All KPIs computed in plant-local timezone.
- Every KPI value stored with input coverage % (expected vs actual readings present).
- Coverage < 70% flagged as 'low_confidence'.
- Missing or insufficient inputs marked as 'insufficient_data', never silently zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import polars as pl


# ---------------------------------------------------------------------------
# Constants & Flags (§11, S3-AI-01, S3-AI-02)
# ---------------------------------------------------------------------------

FLAG_INSUFFICIENT_DATA: str = "insufficient_data"
FLAG_LOW_CONFIDENCE: str = "low_confidence"
FLAG_APPROX_GHI: str = "approx_ghi"

# Coverage thresholds (§11, S3-AI-01, S3-AI-02)
# Below 70% is flagged as 'low_confidence'. When strict threshold is enforced,
# sparse data (< 70%) is tagged as 'insufficient_data'.
MIN_CONFIDENCE_COVERAGE_THRESHOLD: float = 0.70
MIN_COVERAGE_THRESHOLD: float = 0.70
MIN_INSUFFICIENT_COVERAGE_THRESHOLD: float = 0.70

# Solar reference standards
G_STC_KW_M2: float = 1.0       # Standard Test Condition solar irradiance: 1.0 kW/m² (1000 W/m²)
G_STC_W_M2: float = 1000.0     # 1000 W/m²

# Daylight irradiance threshold for availability & daylight filtering (§11: POA > 50 W/m²)
DEFAULT_DAYLIGHT_THRESHOLD_WM2: float = 50.0

# Zero generation power threshold for offline inverter detection (Watts)
DEFAULT_OFFLINE_POWER_THRESHOLD_W: float = 1.0

# Consecutive offline intervals required before qualifying as downtime (> 2 intervals)
DEFAULT_MIN_OFFLINE_INTERVALS_TRIP: int = 2


class KPIKey(str, Enum):
    """Canonical KPI Keys matching database schema and §11 definitions."""

    ENERGY_AC = "energy_ac"
    SPECIFIC_YIELD = "specific_yield"
    PERFORMANCE_RATIO = "pr"
    CUF = "cuf"
    CUF_DAYLIGHT = "cuf_daylight"
    AVAILABILITY = "availability"
    INVERTER_EFFICIENCY = "inverter_efficiency"
    ENERGY_LOSS = "energy_loss"


@dataclass(frozen=True)
class KPIResult:
    """Immutable result structure for a calculated KPI value."""

    kpi_key: str
    value: Optional[float]
    coverage: float
    flags: List[str]
    unit: str
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        """True if the KPI calculation succeeded with sufficient input data."""
        return self.value is not None and FLAG_INSUFFICIENT_DATA not in self.flags

    @property
    def is_low_confidence(self) -> bool:
        """True if calculation had low input coverage (< 70%)."""
        return FLAG_LOW_CONFIDENCE in self.flags

    def as_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "kpi_key": self.kpi_key,
            "value": self.value,
            "coverage": self.coverage,
            "flags": list(self.flags),
            "unit": self.unit,
            "details": dict(self.details),
        }


# ---------------------------------------------------------------------------
# Pure Helper Functions: Daylight Filtering & Coverage Logic (S3-AI-02)
# ---------------------------------------------------------------------------


def is_daylight(
    irradiance_wm2: Optional[float],
    threshold_wm2: float = DEFAULT_DAYLIGHT_THRESHOLD_WM2,
) -> bool:
    """Check if irradiance reading qualifies as active daylight (POA > 50 W/m²)."""
    return (
        irradiance_wm2 is not None
        and not math.isnan(irradiance_wm2)
        and irradiance_wm2 > threshold_wm2
    )


def get_daylight_mask(
    irradiance_wm2: Sequence[Optional[float]],
    threshold_wm2: float = DEFAULT_DAYLIGHT_THRESHOLD_WM2,
) -> List[bool]:
    """Generate boolean mask for active daylight intervals across a period."""
    return [is_daylight(g, threshold_wm2) for g in irradiance_wm2]


def filter_daylight_series(
    data: Sequence[Optional[float]],
    irradiance_wm2: Sequence[Optional[float]],
    threshold_wm2: float = DEFAULT_DAYLIGHT_THRESHOLD_WM2,
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """Filter telemetry values and irradiance to include only active daylight intervals (§11, S3-AI-02).

    Filters out nighttime zero-values where irradiance <= threshold_wm2.

    Returns:
        Tuple of (filtered_data, filtered_irradiance) containing only entries where
        irradiance > threshold_wm2.
    """
    n = min(len(data), len(irradiance_wm2))
    filtered_data: List[Optional[float]] = []
    filtered_irr: List[Optional[float]] = []

    for i in range(n):
        irr = irradiance_wm2[i]
        if is_daylight(irr, threshold_wm2):
            filtered_data.append(data[i])
            filtered_irr.append(irr)

    return filtered_data, filtered_irr


def calculate_daylight_hours(
    irradiance_wm2: Sequence[Optional[float]],
    interval_hours: float = 0.25,
    threshold_wm2: float = DEFAULT_DAYLIGHT_THRESHOLD_WM2,
) -> float:
    """Calculate total active daylight duration in hours over the period."""
    daylight_intervals = sum(1 for g in irradiance_wm2 if is_daylight(g, threshold_wm2))
    return round(daylight_intervals * interval_hours, 4)


def compute_coverage(
    actual_count: int,
    expected_count: int,
) -> float:
    """Compute input coverage fraction [0.0, 1.0]."""
    if expected_count <= 0:
        return 1.0 if actual_count > 0 else 0.0
    coverage = float(actual_count) / float(expected_count)
    return max(0.0, min(1.0, round(coverage, 4)))


def compute_daylight_coverage(
    actual_daylight_count: int,
    expected_daylight_count: int,
) -> float:
    """Compute data coverage specifically across active daylight intervals."""
    return compute_coverage(actual_daylight_count, expected_daylight_count)


def evaluate_coverage_flags(
    coverage: float,
    base_flags: Optional[Sequence[str]] = None,
    min_confidence_threshold: float = MIN_CONFIDENCE_COVERAGE_THRESHOLD,
    min_insufficient_threshold: Optional[float] = None,
) -> List[str]:
    """Evaluate quality flags based on coverage percentage (§11, S3-AI-02).

    - Adds 'insufficient_data' if coverage is below min_insufficient_threshold.
    - Adds 'low_confidence' if coverage is below min_confidence_threshold (default 70%).
    """
    flags: List[str] = list(base_flags) if base_flags else []
    if min_insufficient_threshold is not None and coverage < min_insufficient_threshold:
        if FLAG_INSUFFICIENT_DATA not in flags:
            flags.append(FLAG_INSUFFICIENT_DATA)
    if coverage < min_confidence_threshold and FLAG_INSUFFICIENT_DATA not in flags:
        if FLAG_LOW_CONFIDENCE not in flags:
            flags.append(FLAG_LOW_CONFIDENCE)
    return sorted(list(set(flags)))


def enforce_data_quality(
    result: KPIResult,
    min_coverage_threshold: float = MIN_COVERAGE_THRESHOLD,
) -> KPIResult:
    """Enforce data quality rule (§11, S3-AI-02):

    Missing or sparse data must never silently output a zero or unflagged metric.
    If data coverage falls below min_coverage_threshold (e.g. below 70%),
    explicitly nullify the value and tag as 'insufficient_data'.
    """
    if result.coverage < min_coverage_threshold or result.value is None:
        flags = list(result.flags)
        if FLAG_INSUFFICIENT_DATA not in flags:
            flags.append(FLAG_INSUFFICIENT_DATA)
        return KPIResult(
            kpi_key=result.kpi_key,
            value=None,  # Never silently output zero for sparse or missing data
            coverage=result.coverage,
            flags=sorted(list(set(flags))),
            unit=result.unit,
            details={
                **result.details,
                "sparse_data_nullified": True,
                "coverage_threshold": min_coverage_threshold,
            },
        )
    return result


# ---------------------------------------------------------------------------
# 1. AC Energy (E_ac) Pure Functions
# ---------------------------------------------------------------------------


def calculate_energy_ac(
    power_ac: Sequence[Optional[float]],
    interval_hours: float = 0.25,
    unit: str = "W",
    expected_count: int = 96,
    irradiance_wm2: Optional[Sequence[Optional[float]]] = None,
    daylight_only: bool = False,
    daylight_threshold_wm2: float = DEFAULT_DAYLIGHT_THRESHOLD_WM2,
    min_coverage_threshold: Optional[float] = None,
) -> KPIResult:
    """Calculate AC energy generation (E_ac) in kWh over period.

    Formula:
        E_ac = Σ(power_ac * Δt)

    Args:
        power_ac: Sequence of power readings across the period.
        interval_hours: Sampling cadence in hours (0.25 h for 15-minute intervals).
        unit: Power unit ('W' or 'kW').
        expected_count: Expected number of readings across the period (default 96 for 24h at 15m).
        irradiance_wm2: Optional paired irradiance series for daylight filtering (§11, S3-AI-02).
        daylight_only: If True, filter out nighttime zero-values where irradiance <= 50 W/m².
        daylight_threshold_wm2: Minimum irradiance qualifying as daylight (default 50.0 W/m²).
        min_coverage_threshold: Optional strict threshold (e.g. 0.70) below which value is
                                nullified and tagged as 'insufficient_data'.

    Returns:
        KPIResult containing energy in kWh, coverage fraction, and flags.
    """
    series_to_process = list(power_ac)
    daylight_filtered = False

    # Apply daylight filtering if requested and irradiance is provided
    if daylight_only and irradiance_wm2 is not None:
        filtered_power, _ = filter_daylight_series(
            series_to_process, irradiance_wm2, threshold_wm2=daylight_threshold_wm2
        )
        series_to_process = filtered_power
        daylight_filtered = True

    valid_power = [p for p in series_to_process if p is not None and not math.isnan(p)]
    actual_count = len(valid_power)
    coverage = compute_coverage(actual_count, expected_count)

    flags = evaluate_coverage_flags(
        coverage, min_insufficient_threshold=min_coverage_threshold
    )

    if actual_count == 0 or (min_coverage_threshold is not None and coverage < min_coverage_threshold):
        if FLAG_INSUFFICIENT_DATA not in flags:
            flags.append(FLAG_INSUFFICIENT_DATA)
        return KPIResult(
            kpi_key=KPIKey.ENERGY_AC.value,
            value=None,  # Never silently zero for missing or sparse data
            coverage=coverage,
            flags=sorted(list(set(flags))),
            unit="kWh",
            details={
                "actual_count": actual_count,
                "expected_count": expected_count,
                "daylight_filtered": daylight_filtered,
            },
        )

    # Unit conversion: if W, convert to kW by dividing by 1000.0
    scale = 0.001 if unit.upper() == "W" else 1.0

    # Riemann sum: E_ac (kWh) = Σ (P_kw * Δt_h)
    energy_kwh = sum(max(0.0, p) * scale * interval_hours for p in valid_power)
    energy_kwh = round(energy_kwh, 4)

    return KPIResult(
        kpi_key=KPIKey.ENERGY_AC.value,
        value=energy_kwh,
        coverage=coverage,
        flags=flags,
        unit="kWh",
        details={
            "actual_count": actual_count,
            "expected_count": expected_count,
            "interval_hours": interval_hours,
            "unit": unit,
            "daylight_filtered": daylight_filtered,
        },
    )


def calculate_energy_ac_from_counter(
    counter_values: Sequence[Optional[float]],
    unit: str = "Wh",
    expected_count: int = 96,
    min_coverage_threshold: Optional[float] = None,
) -> KPIResult:
    """Calculate AC energy generation (E_ac) in kWh from energy counter readings.

    Formula:
        E_ac = max(counter) - min(counter) (with reset/rollover handling)

    Args:
        counter_values: Sequence of counter readings across the period.
        unit: Counter unit ('Wh' or 'kWh').
        expected_count: Expected number of readings.
        min_coverage_threshold: Optional strict threshold below which data is insufficient.

    Returns:
        KPIResult containing energy in kWh, coverage fraction, and flags.
    """
    valid_counters = [c for c in counter_values if c is not None and not math.isnan(c)]
    actual_count = len(valid_counters)
    coverage = compute_coverage(actual_count, expected_count)

    flags = evaluate_coverage_flags(
        coverage, min_insufficient_threshold=min_coverage_threshold
    )

    if actual_count < 2 or (min_coverage_threshold is not None and coverage < min_coverage_threshold):
        if FLAG_INSUFFICIENT_DATA not in flags:
            flags.append(FLAG_INSUFFICIENT_DATA)
        return KPIResult(
            kpi_key=KPIKey.ENERGY_AC.value,
            value=None,
            coverage=coverage,
            flags=sorted(list(set(flags))),
            unit="kWh",
            details={"actual_count": actual_count, "expected_count": expected_count},
        )

    scale = 0.001 if unit.upper() == "WH" else 1.0

    # Handle daily counter (resets at start of day) or lifetime monotonic
    first_val = valid_counters[0]
    last_val = valid_counters[-1]
    max_val = max(valid_counters)
    min_val = min(valid_counters)

    # If strictly monotonic
    if last_val >= first_val:
        delta = last_val - first_val
    else:
        # Rollover or reset occurred: sum positive deltas
        delta = 0.0
        for i in range(1, len(valid_counters)):
            step = valid_counters[i] - valid_counters[i - 1]
            if step >= 0:
                delta += step
            else:
                # Reset occurred, take the new reading as new increment
                delta += valid_counters[i]

    energy_kwh = round(delta * scale, 4)

    return KPIResult(
        kpi_key=KPIKey.ENERGY_AC.value,
        value=energy_kwh,
        coverage=coverage,
        flags=flags,
        unit="kWh",
        details={
            "actual_count": actual_count,
            "expected_count": expected_count,
            "min_val": min_val,
            "max_val": max_val,
            "unit": unit,
        },
    )


# ---------------------------------------------------------------------------
# 2. Specific Yield (Y) Pure Function
# ---------------------------------------------------------------------------


def calculate_specific_yield(
    energy_ac_kwh: Optional[float],
    capacity_dc_kwp: float,
    coverage: float = 1.0,
    base_flags: Optional[Sequence[str]] = None,
    min_coverage_threshold: Optional[float] = None,
) -> KPIResult:
    """Calculate Specific Yield (Y) in kWh/kWp.

    Formula:
        Y = E_ac / P_dc,rated

    Args:
        energy_ac_kwh: AC energy generation in kWh.
        capacity_dc_kwp: Rated DC capacity in kWp.
        coverage: Input coverage fraction.
        base_flags: Flags passed from upstream energy calculation.
        min_coverage_threshold: Strict coverage threshold for 'insufficient_data'.

    Returns:
        KPIResult containing Specific Yield in kWh/kWp.
    """
    flags = list(base_flags) if base_flags else []

    if (
        energy_ac_kwh is None
        or capacity_dc_kwp <= 0.0
        or math.isnan(capacity_dc_kwp)
        or (min_coverage_threshold is not None and coverage < min_coverage_threshold)
    ):
        if FLAG_INSUFFICIENT_DATA not in flags:
            flags.append(FLAG_INSUFFICIENT_DATA)
        return KPIResult(
            kpi_key=KPIKey.SPECIFIC_YIELD.value,
            value=None,
            coverage=coverage,
            flags=sorted(list(set(flags))),
            unit="kWh/kWp",
            details={
                "energy_ac_kwh": energy_ac_kwh,
                "capacity_dc_kwp": capacity_dc_kwp,
            },
        )

    yield_val = round(energy_ac_kwh / capacity_dc_kwp, 4)
    flags = evaluate_coverage_flags(
        coverage, flags, min_insufficient_threshold=min_coverage_threshold
    )

    return KPIResult(
        kpi_key=KPIKey.SPECIFIC_YIELD.value,
        value=yield_val,
        coverage=coverage,
        flags=flags,
        unit="kWh/kWp",
        details={
            "energy_ac_kwh": energy_ac_kwh,
            "capacity_dc_kwp": capacity_dc_kwp,
        },
    )


# ---------------------------------------------------------------------------
# 3. Performance Ratio (PR) Pure Functions (with Daylight Filtering)
# ---------------------------------------------------------------------------


def calculate_performance_ratio(
    energy_ac_kwh: Optional[float],
    capacity_dc_kwp: float,
    irradiation_poa_kwh_m2: Optional[float],
    g_stc_kw_m2: float = G_STC_KW_M2,
    is_ghi: bool = False,
    coverage: float = 1.0,
    base_flags: Optional[Sequence[str]] = None,
    min_coverage_threshold: Optional[float] = None,
) -> KPIResult:
    """Calculate Performance Ratio (PR) according to IEC 61724-1.

    Formula:
        PR = E_ac / (P_dc,rated * (G_poa / G_stc))

    Args:
        energy_ac_kwh: AC energy generated in kWh over period.
        capacity_dc_kwp: Rated DC capacity in kWp.
        irradiation_poa_kwh_m2: Plane-of-array solar irradiation in kWh/m².
        g_stc_kw_m2: STC reference irradiance (default 1.0 kW/m²).
        is_ghi: True if irradiation is horizontal (GHI) rather than POA tilt,
                which sets the 'approx_ghi' flag (§11, S3-AI-02).
        coverage: Combined input coverage fraction.
        base_flags: Pre-existing flags.
        min_coverage_threshold: Strict coverage threshold for 'insufficient_data'.

    Returns:
        KPIResult containing PR ratio [0.0 - 1.0+].
    """
    flags = list(base_flags) if base_flags else []
    if is_ghi and FLAG_APPROX_GHI not in flags:
        flags.append(FLAG_APPROX_GHI)

    if (
        energy_ac_kwh is None
        or irradiation_poa_kwh_m2 is None
        or capacity_dc_kwp <= 0.0
        or irradiation_poa_kwh_m2 <= 0.0
        or math.isnan(capacity_dc_kwp)
        or math.isnan(irradiation_poa_kwh_m2)
        or (min_coverage_threshold is not None and coverage < min_coverage_threshold)
    ):
        if FLAG_INSUFFICIENT_DATA not in flags:
            flags.append(FLAG_INSUFFICIENT_DATA)
        return KPIResult(
            kpi_key=KPIKey.PERFORMANCE_RATIO.value,
            value=None,
            coverage=coverage,
            flags=sorted(list(set(flags))),
            unit="ratio",
            details={
                "energy_ac_kwh": energy_ac_kwh,
                "capacity_dc_kwp": capacity_dc_kwp,
                "irradiation_poa_kwh_m2": irradiation_poa_kwh_m2,
                "g_stc_kw_m2": g_stc_kw_m2,
            },
        )

    # Expected reference yield energy in kWh: P_dc,rated * (G_poa / G_stc)
    expected_energy_kwh = capacity_dc_kwp * (irradiation_poa_kwh_m2 / g_stc_kw_m2)

    if expected_energy_kwh <= 0.0:
        if FLAG_INSUFFICIENT_DATA not in flags:
            flags.append(FLAG_INSUFFICIENT_DATA)
        return KPIResult(
            kpi_key=KPIKey.PERFORMANCE_RATIO.value,
            value=None,
            coverage=coverage,
            flags=sorted(list(set(flags))),
            unit="ratio",
            details={"expected_energy_kwh": expected_energy_kwh},
        )

    pr_val = round(energy_ac_kwh / expected_energy_kwh, 4)
    flags = evaluate_coverage_flags(
        coverage, flags, min_insufficient_threshold=min_coverage_threshold
    )

    return KPIResult(
        kpi_key=KPIKey.PERFORMANCE_RATIO.value,
        value=pr_val,
        coverage=coverage,
        flags=flags,
        unit="ratio",
        details={
            "energy_ac_kwh": energy_ac_kwh,
            "expected_energy_kwh": round(expected_energy_kwh, 4),
            "capacity_dc_kwp": capacity_dc_kwp,
            "irradiation_poa_kwh_m2": irradiation_poa_kwh_m2,
        },
    )


def calculate_daylight_pr(
    power_ac: Sequence[Optional[float]],
    irradiance_poa_wm2: Sequence[Optional[float]],
    capacity_dc_kwp: float,
    interval_hours: float = 0.25,
    power_unit: str = "W",
    g_stc_kw_m2: float = G_STC_KW_M2,
    daylight_threshold_wm2: float = DEFAULT_DAYLIGHT_THRESHOLD_WM2,
    is_ghi: bool = False,
    expected_count: int = 96,
    min_coverage_threshold: Optional[float] = None,
) -> KPIResult:
    """Calculate Performance Ratio (PR) strictly on daylight-filtered telemetry (§11, S3-AI-02).

    Filters out nighttime zero-values where POA <= 50 W/m².
    Integrates daylight AC energy and daylight POA irradiation, then computes PR.
    If zero daylight intervals are observed, returns value=None with 'insufficient_data'.
    """
    filtered_power, filtered_poa = filter_daylight_series(
        power_ac, irradiance_poa_wm2, threshold_wm2=daylight_threshold_wm2
    )

    daylight_intervals = len(filtered_poa)
    daylight_hours = round(daylight_intervals * interval_hours, 4)

    if daylight_intervals == 0:
        flags = [FLAG_INSUFFICIENT_DATA]
        if is_ghi:
            flags.append(FLAG_APPROX_GHI)
        return KPIResult(
            kpi_key=KPIKey.PERFORMANCE_RATIO.value,
            value=None,
            coverage=0.0,
            flags=sorted(flags),
            unit="ratio",
            details={
                "reason": "no active daylight intervals (POA > 50 W/m²)",
                "daylight_intervals": 0,
                "daylight_hours": 0.0,
            },
        )

    # 1. Daylight AC Energy
    res_e = calculate_energy_ac(
        power_ac=filtered_power,
        interval_hours=interval_hours,
        unit=power_unit,
        expected_count=daylight_intervals,
    )

    # 2. Daylight POA Irradiation
    poa_kwh_m2, valid_poa = integrate_irradiation_kwh_m2(
        filtered_poa, interval_hours=interval_hours
    )
    poa_cov = compute_coverage(valid_poa, daylight_intervals)
    combined_cov = min(res_e.coverage, poa_cov)

    res_pr = calculate_performance_ratio(
        energy_ac_kwh=res_e.value,
        capacity_dc_kwp=capacity_dc_kwp,
        irradiation_poa_kwh_m2=poa_kwh_m2 if poa_kwh_m2 > 0 else None,
        g_stc_kw_m2=g_stc_kw_m2,
        is_ghi=is_ghi,
        coverage=combined_cov,
        base_flags=res_e.flags,
        min_coverage_threshold=min_coverage_threshold,
    )

    return KPIResult(
        kpi_key=res_pr.kpi_key,
        value=res_pr.value,
        coverage=res_pr.coverage,
        flags=res_pr.flags,
        unit=res_pr.unit,
        details={
            **res_pr.details,
            "daylight_filtered": True,
            "daylight_intervals": daylight_intervals,
            "daylight_hours": daylight_hours,
            "daylight_coverage": combined_cov,
        },
    )


# ---------------------------------------------------------------------------
# 4. Capacity Utilization Factor (CUF) Pure Functions (24h & Daylight)
# ---------------------------------------------------------------------------


def calculate_cuf(
    energy_ac_kwh: Optional[float],
    capacity_ac_kw: float,
    period_hours: float = 24.0,
    daylight_hours: Optional[float] = None,
    daylight_only: bool = False,
    coverage: float = 1.0,
    base_flags: Optional[Sequence[str]] = None,
    min_coverage_threshold: Optional[float] = None,
) -> KPIResult:
    """Calculate Capacity Utilization Factor (CUF) on AC capacity basis (§11, S3-AI-02).

    Formulas:
        Standard CUF (24h basis):  CUF = E_ac / (P_ac,rated * 24.0)
        Daylight CUF (sun active): CUF_daylight = E_ac / (P_ac,rated * H_daylight)

    Args:
        energy_ac_kwh: Total AC energy generated in kWh over period.
        capacity_ac_kw: Rated AC plant or inverter capacity in kW.
        period_hours: Total hours in period (default 24.0 for standard daily rollup).
        daylight_hours: Active sunlight hours (POA > 50 W/m²) for daylight filtering.
        daylight_only: If True, evaluates CUF strictly over active daylight duration.
        coverage: Input coverage fraction.
        base_flags: Pre-existing flags.
        min_coverage_threshold: Strict coverage threshold for 'insufficient_data'.

    Returns:
        KPIResult containing CUF ratio [0.0 - 1.0].
    """
    flags = list(base_flags) if base_flags else []
    effective_hours = daylight_hours if (daylight_only and daylight_hours is not None) else period_hours
    target_key = KPIKey.CUF_DAYLIGHT.value if daylight_only else KPIKey.CUF.value

    if (
        energy_ac_kwh is None
        or capacity_ac_kw <= 0.0
        or effective_hours <= 0.0
        or math.isnan(capacity_ac_kw)
        or (min_coverage_threshold is not None and coverage < min_coverage_threshold)
    ):
        if FLAG_INSUFFICIENT_DATA not in flags:
            flags.append(FLAG_INSUFFICIENT_DATA)
        return KPIResult(
            kpi_key=target_key,
            value=None,
            coverage=coverage,
            flags=sorted(list(set(flags))),
            unit="ratio",
            details={
                "energy_ac_kwh": energy_ac_kwh,
                "capacity_ac_kw": capacity_ac_kw,
                "period_hours": period_hours,
                "effective_hours": effective_hours,
                "daylight_only": daylight_only,
            },
        )

    max_possible_energy = capacity_ac_kw * effective_hours
    cuf_val = round(energy_ac_kwh / max_possible_energy, 4)
    flags = evaluate_coverage_flags(
        coverage, flags, min_insufficient_threshold=min_coverage_threshold
    )

    return KPIResult(
        kpi_key=target_key,
        value=cuf_val,
        coverage=coverage,
        flags=flags,
        unit="ratio",
        details={
            "energy_ac_kwh": energy_ac_kwh,
            "capacity_ac_kw": capacity_ac_kw,
            "period_hours": period_hours,
            "effective_hours": effective_hours,
            "max_possible_energy": max_possible_energy,
            "daylight_only": daylight_only,
        },
    )


def calculate_daylight_cuf(
    energy_ac_kwh: Optional[float],
    capacity_ac_kw: float,
    daylight_hours: float,
    coverage: float = 1.0,
    base_flags: Optional[Sequence[str]] = None,
    min_coverage_threshold: Optional[float] = None,
) -> KPIResult:
    """Calculate Daylight Capacity Utilization Factor (CUF_daylight) (§11, S3-AI-02).

    Evaluates generation strictly during active solar hours, filtering out
    the nighttime non-generating intervals.

    Formula:
        CUF_daylight = E_ac / (P_ac,rated * H_daylight)
    """
    return calculate_cuf(
        energy_ac_kwh=energy_ac_kwh,
        capacity_ac_kw=capacity_ac_kw,
        period_hours=daylight_hours,
        daylight_hours=daylight_hours,
        daylight_only=True,
        coverage=coverage,
        base_flags=base_flags,
        min_coverage_threshold=min_coverage_threshold,
    )


# ---------------------------------------------------------------------------
# 5. Time-based Availability (A) Pure Function
# ---------------------------------------------------------------------------


def calculate_availability(
    irradiance_poa_wm2: Sequence[Optional[float]],
    power_ac_w: Sequence[Optional[float]],
    status_offline: Optional[Sequence[Optional[bool]]] = None,
    interval_hours: float = 0.25,
    daylight_threshold_wm2: float = DEFAULT_DAYLIGHT_THRESHOLD_WM2,
    offline_power_threshold_w: float = DEFAULT_OFFLINE_POWER_THRESHOLD_W,
    min_consecutive_trip_intervals: int = DEFAULT_MIN_OFFLINE_INTERVALS_TRIP,
    expected_count: int = 96,
    min_coverage_threshold: Optional[float] = None,
) -> KPIResult:
    """Calculate Time-based Availability (A) on daylight-filtered telemetry (§11, S3-AI-02).

    Formula:
        A = 1 - (Σ downtime during daylight / daylight hours)

    Definition of Downtime (§11):
        Downtime = status offline OR (POA > 50 W/m² AND P_ac ≈ 0 for > 2 intervals)

    Args:
        irradiance_poa_wm2: Time-series of plane-of-array irradiance readings in W/m².
        power_ac_w: Time-series of inverter active AC power generation in Watts.
        status_offline: Optional explicit boolean flag indicating inverter offline state.
        interval_hours: Sampling cadence in hours (default 0.25 h for 15 min).
        daylight_threshold_wm2: Minimum irradiance qualifying as daylight (default 50.0 W/m²).
        offline_power_threshold_w: Threshold below which inverter is generating near zero (default 1.0 W).
        min_consecutive_trip_intervals: Consecutive intervals threshold before downtime is counted (> 2 intervals).
        expected_count: Expected total intervals across the calendar day.
        min_coverage_threshold: Strict coverage threshold for 'insufficient_data'.

    Returns:
        KPIResult containing Availability ratio [0.0 - 1.0].
    """
    n = min(len(irradiance_poa_wm2), len(power_ac_w))
    if n == 0:
        return KPIResult(
            kpi_key=KPIKey.AVAILABILITY.value,
            value=None,
            coverage=0.0,
            flags=[FLAG_INSUFFICIENT_DATA],
            unit="ratio",
            details={"reason": "empty input arrays"},
        )

    coverage = compute_coverage(n, expected_count)

    if min_coverage_threshold is not None and coverage < min_coverage_threshold:
        return KPIResult(
            kpi_key=KPIKey.AVAILABILITY.value,
            value=None,
            coverage=coverage,
            flags=evaluate_coverage_flags(coverage, min_insufficient_threshold=min_coverage_threshold),
            unit="ratio",
            details={"reason": "coverage below threshold"},
        )

    # 1. Identify daylight intervals (POA > 50 W/m²)
    daylight_mask: List[bool] = []
    for i in range(n):
        poa = irradiance_poa_wm2[i]
        is_dl = poa is not None and not math.isnan(poa) and poa > daylight_threshold_wm2
        daylight_mask.append(is_dl)

    daylight_intervals = sum(1 for d in daylight_mask if d)
    if daylight_intervals == 0:
        # Zero daylight hours observed (night or missing sensor data)
        return KPIResult(
            kpi_key=KPIKey.AVAILABILITY.value,
            value=None,
            coverage=coverage,
            flags=[FLAG_INSUFFICIENT_DATA],
            unit="ratio",
            details={
                "daylight_intervals": 0,
                "daylight_hours": 0.0,
                "total_intervals": n,
            },
        )

    # 2. Identify candidate downtime conditions during daylight
    # Condition A: Explicit status offline
    # Condition B: P_ac ≈ 0 during daylight for > min_consecutive_trip_intervals
    zero_power_run_length = 0
    zero_power_run_indices: List[int] = []

    # Map each daylight interval to whether it is downtime
    is_downtime = [False] * n

    for i in range(n):
        if not daylight_mask[i]:
            # Reset run when nighttime / below threshold
            if zero_power_run_length > min_consecutive_trip_intervals:
                for idx in zero_power_run_indices:
                    is_downtime[idx] = True
            zero_power_run_length = 0
            zero_power_run_indices = []
            continue

        # Check explicit offline status
        explicit_offline = False
        if status_offline is not None and i < len(status_offline):
            st = status_offline[i]
            if st is True:
                explicit_offline = True

        if explicit_offline:
            is_downtime[i] = True
            # Also flush any current run
            if zero_power_run_length > min_consecutive_trip_intervals:
                for idx in zero_power_run_indices:
                    is_downtime[idx] = True
            zero_power_run_length = 0
            zero_power_run_indices = []
            continue

        # Check power near zero during daylight
        p_val = power_ac_w[i]
        is_zero_power = p_val is None or math.isnan(p_val) or p_val <= offline_power_threshold_w

        if is_zero_power:
            zero_power_run_length += 1
            zero_power_run_indices.append(i)
        else:
            if zero_power_run_length > min_consecutive_trip_intervals:
                for idx in zero_power_run_indices:
                    is_downtime[idx] = True
            zero_power_run_length = 0
            zero_power_run_indices = []

    # Flush end of daylight run
    if zero_power_run_length > min_consecutive_trip_intervals:
        for idx in zero_power_run_indices:
            is_downtime[idx] = True

    # Count downtime intervals during daylight only
    downtime_count = sum(1 for i in range(n) if daylight_mask[i] and is_downtime[i])
    daylight_hours = daylight_intervals * interval_hours
    downtime_hours = downtime_count * interval_hours

    availability_val = max(0.0, min(1.0, 1.0 - (downtime_hours / daylight_hours)))
    availability_val = round(availability_val, 4)

    flags = evaluate_coverage_flags(
        coverage, min_insufficient_threshold=min_coverage_threshold
    )

    return KPIResult(
        kpi_key=KPIKey.AVAILABILITY.value,
        value=availability_val,
        coverage=coverage,
        flags=flags,
        unit="ratio",
        details={
            "daylight_intervals": daylight_intervals,
            "daylight_hours": round(daylight_hours, 2),
            "downtime_intervals": downtime_count,
            "downtime_hours": round(downtime_hours, 2),
            "interval_hours": interval_hours,
        },
    )


# ---------------------------------------------------------------------------
# 6. Inverter Efficiency (η) Pure Function
# ---------------------------------------------------------------------------


def calculate_inverter_efficiency(
    energy_ac_kwh: Optional[float],
    energy_dc_kwh: Optional[float],
    coverage: float = 1.0,
    base_flags: Optional[Sequence[str]] = None,
    min_coverage_threshold: Optional[float] = None,
) -> KPIResult:
    """Calculate Inverter Efficiency (η).

    Formula:
        η = E_ac / E_dc

    Notes (§11):
        "Only where DC power channel exists"
        Daylight-filtered non-zero generation periods.

    Args:
        energy_ac_kwh: Total AC generation energy in kWh over period.
        energy_dc_kwh: Total DC generation energy in kWh over period.
        coverage: Input coverage fraction.
        base_flags: Upstream flags.
        min_coverage_threshold: Strict coverage threshold for 'insufficient_data'.

    Returns:
        KPIResult containing Inverter Efficiency ratio [0.0 - 1.0].
    """
    flags = list(base_flags) if base_flags else []

    if (
        energy_ac_kwh is None
        or energy_dc_kwh is None
        or energy_dc_kwh <= 0.0
        or math.isnan(energy_dc_kwh)
        or math.isnan(energy_ac_kwh)
        or (min_coverage_threshold is not None and coverage < min_coverage_threshold)
    ):
        if FLAG_INSUFFICIENT_DATA not in flags:
            flags.append(FLAG_INSUFFICIENT_DATA)
        return KPIResult(
            kpi_key=KPIKey.INVERTER_EFFICIENCY.value,
            value=None,
            coverage=coverage,
            flags=sorted(list(set(flags))),
            unit="ratio",
            details={
                "energy_ac_kwh": energy_ac_kwh,
                "energy_dc_kwh": energy_dc_kwh,
            },
        )

    # Inverter conversion efficiency
    efficiency_val = round(energy_ac_kwh / energy_dc_kwh, 4)
    flags = evaluate_coverage_flags(
        coverage, flags, min_insufficient_threshold=min_coverage_threshold
    )

    return KPIResult(
        kpi_key=KPIKey.INVERTER_EFFICIENCY.value,
        value=efficiency_val,
        coverage=coverage,
        flags=flags,
        unit="ratio",
        details={
            "energy_ac_kwh": energy_ac_kwh,
            "energy_dc_kwh": energy_dc_kwh,
        },
    )


# ---------------------------------------------------------------------------
# 7. Estimated Energy Loss (L) Pure Function
# ---------------------------------------------------------------------------


def calculate_energy_loss(
    pr_actual: Optional[float],
    pr_expected: float,
    capacity_dc_kwp: float,
    irradiation_poa_kwh_m2: Optional[float],
    g_stc_kw_m2: float = G_STC_KW_M2,
    floor_zero: bool = True,
    coverage: float = 1.0,
    base_flags: Optional[Sequence[str]] = None,
    min_coverage_threshold: Optional[float] = None,
) -> KPIResult:
    """Calculate Estimated Energy Loss (L) in kWh.

    Formula (§11):
        L = (PR_expected - PR_actual) * P_dc,rated * (G_poa / G_stc)

    Notes:
        PR_expected = plant metadata (default 0.80) or trailing 30-day median.
        If floor_zero=True, losses are bounded at 0.0 (no negative losses when PR exceeds expected).

    Args:
        pr_actual: Actual calculated Performance Ratio.
        pr_expected: Design target or expected Performance Ratio (e.g. 0.78 or 0.80).
        capacity_dc_kwp: Rated DC capacity in kWp.
        irradiation_poa_kwh_m2: POA irradiation in kWh/m².
        g_stc_kw_m2: STC solar irradiance constant (1.0 kW/m²).
        floor_zero: Bounded at 0.0 if actual PR meets or exceeds target.
        coverage: Combined input coverage fraction.
        base_flags: Upstream flags.
        min_coverage_threshold: Strict coverage threshold for 'insufficient_data'.

    Returns:
        KPIResult containing estimated energy loss in kWh.
    """
    flags = list(base_flags) if base_flags else []

    if (
        pr_actual is None
        or irradiation_poa_kwh_m2 is None
        or capacity_dc_kwp <= 0.0
        or irradiation_poa_kwh_m2 <= 0.0
        or math.isnan(pr_actual)
        or math.isnan(capacity_dc_kwp)
        or math.isnan(irradiation_poa_kwh_m2)
        or (min_coverage_threshold is not None and coverage < min_coverage_threshold)
    ):
        if FLAG_INSUFFICIENT_DATA not in flags:
            flags.append(FLAG_INSUFFICIENT_DATA)
        return KPIResult(
            kpi_key=KPIKey.ENERGY_LOSS.value,
            value=None,
            coverage=coverage,
            flags=sorted(list(set(flags))),
            unit="kWh",
            details={
                "pr_actual": pr_actual,
                "pr_expected": pr_expected,
                "capacity_dc_kwp": capacity_dc_kwp,
                "irradiation_poa_kwh_m2": irradiation_poa_kwh_m2,
            },
        )

    # Expected reference generation
    expected_energy_kwh = capacity_dc_kwp * (irradiation_poa_kwh_m2 / g_stc_kw_m2)
    delta_pr = pr_expected - pr_actual

    raw_loss_kwh = delta_pr * expected_energy_kwh
    loss_kwh = max(0.0, raw_loss_kwh) if floor_zero else raw_loss_kwh
    loss_kwh = round(loss_kwh, 4)

    flags = evaluate_coverage_flags(
        coverage, flags, min_insufficient_threshold=min_coverage_threshold
    )

    return KPIResult(
        kpi_key=KPIKey.ENERGY_LOSS.value,
        value=loss_kwh,
        coverage=coverage,
        flags=flags,
        unit="kWh",
        details={
            "delta_pr": round(delta_pr, 4),
            "pr_actual": pr_actual,
            "pr_expected": pr_expected,
            "expected_energy_kwh": round(expected_energy_kwh, 4),
            "raw_loss_kwh": round(raw_loss_kwh, 4),
        },
    )


# ---------------------------------------------------------------------------
# Integrated Inverter & Plant KPI Rollup Solvers
# ---------------------------------------------------------------------------


def integrate_irradiation_kwh_m2(
    irradiance_wm2: Sequence[Optional[float]],
    interval_hours: float = 0.25,
) -> Tuple[float, int]:
    """Integrate irradiance time-series (W/m²) to total irradiation (kWh/m²).

    Formula:
        G_poa = Σ (POA_w_m2 * Δt_h) / 1000.0

    Returns:
        (irradiation_kwh_m2, valid_readings_count)
    """
    valid = [g for g in irradiance_wm2 if g is not None and not math.isnan(g)]
    if not valid:
        return 0.0, 0
    total_wh_m2 = sum(max(0.0, g) * interval_hours for g in valid)
    irradiation_kwh_m2 = round(total_wh_m2 / 1000.0, 4)
    return irradiation_kwh_m2, len(valid)


def compute_inverter_solar_kpis(
    power_ac_w: Sequence[Optional[float]],
    power_dc_w: Optional[Sequence[Optional[float]]] = None,
    irradiance_poa_wm2: Optional[Sequence[Optional[float]]] = None,
    capacity_dc_kwp: float = 1250.0,
    capacity_ac_kw: float = 1250.0,
    expected_pr: float = 0.78,
    interval_hours: float = 0.25,
    is_ghi: bool = False,
    expected_count: int = 96,
    status_offline: Optional[Sequence[Optional[bool]]] = None,
    filter_daylight: bool = False,
    enforce_min_coverage: Optional[float] = None,
    daylight_threshold_wm2: float = DEFAULT_DAYLIGHT_THRESHOLD_WM2,
    include_daylight_cuf: bool = False,
) -> Dict[str, KPIResult]:
    """Compute all solar KPIs for a single inverter over a calendar day (§11, S3-AI-02).

    Supports:
    - Daylight filtering for PR and CUF (filtering out nighttime zero-values).
    - 24h standard CUF and daylight-only CUF (cuf_daylight).
    - Input coverage percentages across period and active daylight intervals.
    - Flag semantics ('insufficient_data', 'low_confidence', 'approx_ghi').

    Returns dictionary mapping KPI key to KPIResult.
    """
    results: Dict[str, KPIResult] = {}

    # 0. Active Daylight Profile (§11, S3-AI-02)
    daylight_hours: float = 0.0
    daylight_intervals: int = 0
    daylight_power_cov: float = 1.0

    if irradiance_poa_wm2:
        daylight_mask = get_daylight_mask(irradiance_poa_wm2, threshold_wm2=daylight_threshold_wm2)
        daylight_intervals = sum(1 for m in daylight_mask if m)
        daylight_hours = round(daylight_intervals * interval_hours, 4)
        if daylight_intervals > 0:
            valid_dl_p = sum(
                1 for i, p in enumerate(power_ac_w)
                if i < len(daylight_mask) and daylight_mask[i] and p is not None and not math.isnan(p)
            )
            daylight_power_cov = compute_daylight_coverage(valid_dl_p, daylight_intervals)

    # 1. AC Energy
    ac_input = power_ac_w
    if filter_daylight and irradiance_poa_wm2:
        filtered_ac, _ = filter_daylight_series(
            power_ac_w, irradiance_poa_wm2, threshold_wm2=daylight_threshold_wm2
        )
        ac_input = filtered_ac

    res_e_ac = calculate_energy_ac(
        power_ac=ac_input,
        interval_hours=interval_hours,
        unit="W",
        expected_count=daylight_intervals if (filter_daylight and daylight_intervals > 0) else expected_count,
        min_coverage_threshold=enforce_min_coverage,
    )
    results[KPIKey.ENERGY_AC.value] = res_e_ac

    # 2. Specific Yield
    res_yield = calculate_specific_yield(
        energy_ac_kwh=res_e_ac.value,
        capacity_dc_kwp=capacity_dc_kwp,
        coverage=res_e_ac.coverage,
        base_flags=res_e_ac.flags,
        min_coverage_threshold=enforce_min_coverage,
    )
    results[KPIKey.SPECIFIC_YIELD.value] = res_yield

    # POA Irradiation
    poa_val: Optional[float] = None
    poa_cov = 1.0
    if irradiance_poa_wm2:
        poa_kwh_m2, poa_count = integrate_irradiation_kwh_m2(irradiance_poa_wm2, interval_hours)
        poa_cov = compute_coverage(poa_count, expected_count)
        if poa_kwh_m2 > 0:
            poa_val = poa_kwh_m2

    combined_cov = min(res_e_ac.coverage, poa_cov)

    # 3. Performance Ratio (PR)
    res_pr = calculate_performance_ratio(
        energy_ac_kwh=res_e_ac.value,
        capacity_dc_kwp=capacity_dc_kwp,
        irradiation_poa_kwh_m2=poa_val,
        is_ghi=is_ghi,
        coverage=combined_cov,
        base_flags=res_e_ac.flags,
        min_coverage_threshold=enforce_min_coverage,
    )
    results[KPIKey.PERFORMANCE_RATIO.value] = res_pr

    # 4. Standard CUF (24h period)
    res_cuf = calculate_cuf(
        energy_ac_kwh=res_e_ac.value,
        capacity_ac_kw=capacity_ac_kw,
        period_hours=24.0,
        coverage=res_e_ac.coverage,
        base_flags=res_e_ac.flags,
        min_coverage_threshold=enforce_min_coverage,
    )

    # 4b. Daylight CUF (Normalized over active sunlight hours, S3-AI-02)
    res_cuf_daylight = calculate_daylight_cuf(
        energy_ac_kwh=res_e_ac.value,
        capacity_ac_kw=capacity_ac_kw,
        daylight_hours=daylight_hours,
        coverage=daylight_power_cov if daylight_intervals > 0 else res_e_ac.coverage,
        base_flags=res_e_ac.flags,
        min_coverage_threshold=enforce_min_coverage,
    )
    res_cuf.details["daylight_cuf"] = res_cuf_daylight.value
    res_cuf.details["daylight_hours"] = daylight_hours
    results[KPIKey.CUF.value] = res_cuf

    if include_daylight_cuf:
        results[KPIKey.CUF_DAYLIGHT.value] = res_cuf_daylight

    # 5. Availability (Daylight-filtered)
    if irradiance_poa_wm2:
        res_avail = calculate_availability(
            irradiance_poa_wm2=irradiance_poa_wm2,
            power_ac_w=power_ac_w,
            status_offline=status_offline,
            interval_hours=interval_hours,
            expected_count=expected_count,
            min_coverage_threshold=enforce_min_coverage,
        )
    else:
        res_avail = KPIResult(
            kpi_key=KPIKey.AVAILABILITY.value,
            value=None,
            coverage=0.0,
            flags=[FLAG_INSUFFICIENT_DATA],
            unit="ratio",
            details={"reason": "missing irradiance data"},
        )
    results[KPIKey.AVAILABILITY.value] = res_avail

    # 6. Inverter Efficiency
    if power_dc_w:
        dc_input = power_dc_w
        if filter_daylight and irradiance_poa_wm2:
            filtered_dc, _ = filter_daylight_series(
                power_dc_w, irradiance_poa_wm2, threshold_wm2=daylight_threshold_wm2
            )
            dc_input = filtered_dc

        res_e_dc = calculate_energy_ac(
            power_ac=dc_input,
            interval_hours=interval_hours,
            unit="W",
            expected_count=daylight_intervals if (filter_daylight and daylight_intervals > 0) else expected_count,
            min_coverage_threshold=enforce_min_coverage,
        )
        eff_cov = min(res_e_ac.coverage, res_e_dc.coverage)
        res_eff = calculate_inverter_efficiency(
            energy_ac_kwh=res_e_ac.value,
            energy_dc_kwh=res_e_dc.value,
            coverage=eff_cov,
            base_flags=res_e_ac.flags,
            min_coverage_threshold=enforce_min_coverage,
        )
    else:
        res_eff = KPIResult(
            kpi_key=KPIKey.INVERTER_EFFICIENCY.value,
            value=None,
            coverage=0.0,
            flags=[FLAG_INSUFFICIENT_DATA],
            unit="ratio",
            details={"reason": "no DC power channel exists"},
        )
    results[KPIKey.INVERTER_EFFICIENCY.value] = res_eff

    # 7. Estimated Energy Loss
    res_loss = calculate_energy_loss(
        pr_actual=res_pr.value,
        pr_expected=expected_pr,
        capacity_dc_kwp=capacity_dc_kwp,
        irradiation_poa_kwh_m2=poa_val,
        coverage=res_pr.coverage,
        base_flags=res_pr.flags,
        min_coverage_threshold=enforce_min_coverage,
    )
    results[KPIKey.ENERGY_LOSS.value] = res_loss

    # Attach daylight details across results
    for res in results.values():
        res.details.update(
            {
                "daylight_hours": daylight_hours,
                "daylight_intervals": daylight_intervals,
                "daylight_power_coverage": daylight_power_cov,
            }
        )

    return results


def compute_plant_solar_kpis(
    inverter_kpis: Dict[str, Dict[str, KPIResult]],
    plant_capacity_dc_kwp: float,
    plant_capacity_ac_kw: float,
    plant_expected_pr: float,
    irradiation_poa_kwh_m2: Optional[float],
    is_ghi: bool = False,
    daylight_hours: Optional[float] = None,
    enforce_min_coverage: Optional[float] = None,
    include_daylight_cuf: bool = False,
) -> Dict[str, KPIResult]:
    """Roll up inverter KPIs into plant-level KPIs (§11, S3-AI-02).

    Args:
        inverter_kpis: Mapping of inverter identifier to its dict of KPI results.
        plant_capacity_dc_kwp: Total plant DC rated capacity in kWp.
        plant_capacity_ac_kw: Total plant AC rated capacity in kW.
        plant_expected_pr: Target design PR (e.g. 0.78).
        irradiation_poa_kwh_m2: Total plant plane-of-array solar irradiation in kWh/m².
        is_ghi: Whether irradiance is GHI.
        daylight_hours: Optional plant active daylight hours for daylight CUF.
        enforce_min_coverage: Optional strict coverage threshold for 'insufficient_data'.
        include_daylight_cuf: If True, adds CUF_DAYLIGHT as a separate dictionary key.

    Returns:
        Dictionary mapping KPI key to plant-level KPIResult.
    """
    plant_results: Dict[str, KPIResult] = {}
    valid_e_ac: List[float] = []
    e_ac_coverages: List[float] = []
    e_ac_flags: List[str] = []

    # Extract daylight hours from inverter details if not passed
    if daylight_hours is None:
        for kpis in inverter_kpis.values():
            e_res = kpis.get(KPIKey.ENERGY_AC.value)
            if e_res and "daylight_hours" in e_res.details:
                daylight_hours = float(e_res.details["daylight_hours"])
                break

    for inv_name, kpis in inverter_kpis.items():
        e_res = kpis.get(KPIKey.ENERGY_AC.value)
        if e_res and e_res.value is not None:
            valid_e_ac.append(e_res.value)
            e_ac_coverages.append(e_res.coverage)
            e_ac_flags.extend(e_res.flags)

    # 1. Total Plant AC Energy
    if valid_e_ac:
        plant_e_ac = round(sum(valid_e_ac), 4)
        mean_cov = round(sum(e_ac_coverages) / len(e_ac_coverages), 4)
        p_flags = evaluate_coverage_flags(
            mean_cov, e_ac_flags, min_insufficient_threshold=enforce_min_coverage
        )
        res_e_ac = KPIResult(
            kpi_key=KPIKey.ENERGY_AC.value,
            value=None if (enforce_min_coverage is not None and mean_cov < enforce_min_coverage) else plant_e_ac,
            coverage=mean_cov,
            flags=p_flags,
            unit="kWh",
            details={"inverter_count": len(valid_e_ac)},
        )
    else:
        res_e_ac = KPIResult(
            kpi_key=KPIKey.ENERGY_AC.value,
            value=None,
            coverage=0.0,
            flags=[FLAG_INSUFFICIENT_DATA],
            unit="kWh",
            details={"inverter_count": 0},
        )
    plant_results[KPIKey.ENERGY_AC.value] = res_e_ac

    # 2. Plant Specific Yield
    res_yield = calculate_specific_yield(
        energy_ac_kwh=res_e_ac.value,
        capacity_dc_kwp=plant_capacity_dc_kwp,
        coverage=res_e_ac.coverage,
        base_flags=res_e_ac.flags,
        min_coverage_threshold=enforce_min_coverage,
    )
    plant_results[KPIKey.SPECIFIC_YIELD.value] = res_yield

    # 3. Plant Performance Ratio
    res_pr = calculate_performance_ratio(
        energy_ac_kwh=res_e_ac.value,
        capacity_dc_kwp=plant_capacity_dc_kwp,
        irradiation_poa_kwh_m2=irradiation_poa_kwh_m2,
        is_ghi=is_ghi,
        coverage=res_e_ac.coverage,
        base_flags=res_e_ac.flags,
        min_coverage_threshold=enforce_min_coverage,
    )
    plant_results[KPIKey.PERFORMANCE_RATIO.value] = res_pr

    # 4. Plant CUF (24h)
    res_cuf = calculate_cuf(
        energy_ac_kwh=res_e_ac.value,
        capacity_ac_kw=plant_capacity_ac_kw,
        period_hours=24.0,
        coverage=res_e_ac.coverage,
        base_flags=res_e_ac.flags,
        min_coverage_threshold=enforce_min_coverage,
    )

    # 4b. Plant Daylight CUF (S3-AI-02)
    dl_hrs = daylight_hours if daylight_hours is not None else 10.0
    res_cuf_daylight = calculate_daylight_cuf(
        energy_ac_kwh=res_e_ac.value,
        capacity_ac_kw=plant_capacity_ac_kw,
        daylight_hours=dl_hrs,
        coverage=res_e_ac.coverage,
        base_flags=res_e_ac.flags,
        min_coverage_threshold=enforce_min_coverage,
    )
    res_cuf.details["daylight_cuf"] = res_cuf_daylight.value
    res_cuf.details["daylight_hours"] = dl_hrs
    plant_results[KPIKey.CUF.value] = res_cuf

    if include_daylight_cuf:
        plant_results[KPIKey.CUF_DAYLIGHT.value] = res_cuf_daylight

    # 5. Plant Availability (Average of inverter availabilities)
    avail_vals: List[float] = []
    for kpis in inverter_kpis.values():
        a_res = kpis.get(KPIKey.AVAILABILITY.value)
        if a_res and a_res.value is not None:
            avail_vals.append(a_res.value)

    if avail_vals:
        mean_avail = round(sum(avail_vals) / len(avail_vals), 4)
        plant_results[KPIKey.AVAILABILITY.value] = KPIResult(
            kpi_key=KPIKey.AVAILABILITY.value,
            value=mean_avail,
            coverage=res_e_ac.coverage,
            flags=evaluate_coverage_flags(
                res_e_ac.coverage, min_insufficient_threshold=enforce_min_coverage
            ),
            unit="ratio",
            details={"reporting_inverters": len(avail_vals)},
        )
    else:
        plant_results[KPIKey.AVAILABILITY.value] = KPIResult(
            kpi_key=KPIKey.AVAILABILITY.value,
            value=None,
            coverage=0.0,
            flags=[FLAG_INSUFFICIENT_DATA],
            unit="ratio",
            details={"reporting_inverters": 0},
        )

    # 6. Plant Inverter Efficiency (Average of valid inverter efficiencies)
    eff_vals: List[float] = []
    for kpis in inverter_kpis.values():
        e_res = kpis.get(KPIKey.INVERTER_EFFICIENCY.value)
        if e_res and e_res.value is not None:
            eff_vals.append(e_res.value)

    if eff_vals:
        mean_eff = round(sum(eff_vals) / len(eff_vals), 4)
        plant_results[KPIKey.INVERTER_EFFICIENCY.value] = KPIResult(
            kpi_key=KPIKey.INVERTER_EFFICIENCY.value,
            value=mean_eff,
            coverage=res_e_ac.coverage,
            flags=evaluate_coverage_flags(
                res_e_ac.coverage, min_insufficient_threshold=enforce_min_coverage
            ),
            unit="ratio",
            details={"reporting_inverters": len(eff_vals)},
        )
    else:
        plant_results[KPIKey.INVERTER_EFFICIENCY.value] = KPIResult(
            kpi_key=KPIKey.INVERTER_EFFICIENCY.value,
            value=None,
            coverage=0.0,
            flags=[FLAG_INSUFFICIENT_DATA],
            unit="ratio",
            details={"reporting_inverters": 0},
        )

    # 7. Plant Estimated Energy Loss
    res_loss = calculate_energy_loss(
        pr_actual=res_pr.value,
        pr_expected=plant_expected_pr,
        capacity_dc_kwp=plant_capacity_dc_kwp,
        irradiation_poa_kwh_m2=irradiation_poa_kwh_m2,
        coverage=res_pr.coverage,
        base_flags=res_pr.flags,
        min_coverage_threshold=enforce_min_coverage,
    )
    plant_results[KPIKey.ENERGY_LOSS.value] = res_loss

    return plant_results
