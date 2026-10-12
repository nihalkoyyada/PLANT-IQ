"""Severity Classification & Financial Loss Policy Engine (§12, Task S4-AI-01).

Implements:
- Standardized severity classification ('low', 'medium', 'high', 'critical')
  enforcing database CheckConstraint `ck_anomalies_severity`.
- Accurate solar energy loss calculation (kWh) based on time-integrated deficits.
- Financial loss quantification (INR) using plant tariffs or industry defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple
from datetime import datetime


DEFAULT_SOLAR_TARIFF_INR_PER_KWH = 3.50  # Typical Indian utility/rooftop PPA rate (₹3.50 / kWh)


@dataclass
class FinancialAssessment:
    """Financial and energy impact metrics for an anomaly event."""

    energy_loss_kwh: float
    financial_loss_inr: float
    effective_tariff_inr: float
    power_deficit_kw: float
    duration_minutes: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "energy_loss_kwh": round(self.energy_loss_kwh, 2),
            "financial_loss_inr": round(self.financial_loss_inr, 2),
            "effective_tariff_inr": round(self.effective_tariff_inr, 2),
            "power_deficit_kw": round(self.power_deficit_kw, 2),
            "duration_minutes": self.duration_minutes,
            "formatted_loss": f"₹{self.financial_loss_inr:,.2f}",
            "formatted_energy": f"{self.energy_loss_kwh:,.1f} kWh",
        }


class SeverityPolicy:
    """Classifies detected anomalies into standardized severity tiers."""

    SEVERITY_LEVELS = ("low", "medium", "high", "critical")

    @classmethod
    def evaluate(
        cls,
        loss_kw: Optional[float] = None,
        loss_kwh: Optional[float] = None,
        score: float = 0.5,
        duration_minutes: int = 15,
        deficit_pct: Optional[float] = None,
        anomaly_type: str = "outlier",
        rated_kw: Optional[float] = None,
    ) -> str:
        """Classify anomaly severity into 'low', 'medium', 'high', or 'critical'.

        Decision rules prioritize real physical impact (kW / kWh lost) over raw statistical noise.
        """
        kw = loss_kw or 0.0
        kwh = loss_kwh or 0.0
        pct = deficit_pct or 0.0

        # Relative power deficit relative to rated capacity if available
        if rated_kw and float(rated_kw) > 0:
            rel_drop = kw / float(rated_kw)
            pct = max(pct, rel_drop)

        # 1. CRITICAL Tier
        # Total inverter shutdown / trip during daylight, massive loss, or extended outage
        if anomaly_type == "trip":
            return "critical"
        if kw >= 100.0 or kwh >= 200.0:
            return "critical"
        if pct >= 0.75 and duration_minutes >= 30:
            return "critical"
        if score >= 0.90 and kw >= 25.0:
            return "critical"

        # 2. HIGH Tier
        # Substantial generation loss (> 25 kW or > 50 kWh) or prolonged high deficit
        if kw >= 25.0 or kwh >= 50.0:
            return "high"
        if pct >= 0.35 and duration_minutes >= 30:
            return "high"
        if score >= 0.75 and kw >= 10.0:
            return "high"
        if duration_minutes >= 120 and kw >= 15.0:
            return "high"

        # 3. MEDIUM Tier
        # Moderate deviation, sensor flatlines, minor inverter derating
        if kw >= 5.0 or kwh >= 10.0:
            return "medium"
        if pct >= 0.15:
            return "medium"
        if score >= 0.55:
            return "medium"
        if anomaly_type in ("flatline", "soiling"):
            return "medium"

        # 4. LOW Tier
        # Negligible power delta, minor statistical spike, slight clipping
        return "low"


class FinancialLossPolicy:
    """Estimates energy loss in kWh and monetary value in INR."""

    @classmethod
    def calculate(
        cls,
        loss_kwh: float,
        power_deficit_kw: float = 0.0,
        duration_minutes: int = 15,
        tariff_inr_per_kwh: Optional[float] = None,
        default_tariff: float = DEFAULT_SOLAR_TARIFF_INR_PER_KWH,
    ) -> FinancialAssessment:
        """Calculate financial loss based on energy loss and tariff."""
        if tariff_inr_per_kwh is not None and float(tariff_inr_per_kwh) > 0:
            effective_tariff = float(tariff_inr_per_kwh)
        else:
            effective_tariff = float(default_tariff)

        effective_kwh = max(0.0, float(loss_kwh))
        financial_loss_inr = effective_kwh * effective_tariff

        return FinancialAssessment(
            energy_loss_kwh=effective_kwh,
            financial_loss_inr=financial_loss_inr,
            effective_tariff_inr=effective_tariff,
            power_deficit_kw=max(0.0, float(power_deficit_kw)),
            duration_minutes=max(1, int(duration_minutes)),
        )

    @classmethod
    def integrate_discrete_loss(
        cls,
        actual_series: Sequence[Tuple[datetime, float]],
        expected_series: Sequence[Tuple[datetime, float]],
        cadence_seconds: int = 900,
        tariff_inr_per_kwh: Optional[float] = None,
    ) -> FinancialAssessment:
        """Integrate power delta across timestamp-aligned discrete observations."""
        exp_map = {ts: val for ts, val in expected_series}
        total_kwh = 0.0
        peak_deficit_kw = 0.0
        point_count = 0

        interval_hours = cadence_seconds / 3600.0

        for ts, act_val in actual_series:
            if ts in exp_map:
                exp_val = exp_map[ts]
                deficit = max(0.0, exp_val - act_val)
                total_kwh += deficit * interval_hours
                if deficit > peak_deficit_kw:
                    peak_deficit_kw = deficit
                point_count += 1

        duration_minutes = int((point_count * cadence_seconds) / 60)
        return cls.calculate(
            loss_kwh=total_kwh,
            power_deficit_kw=peak_deficit_kw,
            duration_minutes=duration_minutes,
            tariff_inr_per_kwh=tariff_inr_per_kwh,
        )
