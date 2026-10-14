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
    financial_loss_inr: Optional[float]
    effective_tariff_inr: Optional[float]
    power_deficit_kw: float
    duration_minutes: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "energy_loss_kwh": round(self.energy_loss_kwh, 2),
            "financial_loss_inr": round(self.financial_loss_inr, 2) if self.financial_loss_inr is not None else None,
            "effective_tariff_inr": round(self.effective_tariff_inr, 2) if self.effective_tariff_inr is not None else None,
            "power_deficit_kw": round(self.power_deficit_kw, 2),
            "duration_minutes": self.duration_minutes,
            "formatted_loss": f"₹{self.financial_loss_inr:,.2f}" if self.financial_loss_inr is not None else "N/A",
            "formatted_energy": f"{self.energy_loss_kwh:,.1f} kWh",
        }


class SeverityPolicy:
    """Classifies detected anomalies into standardized severity tiers."""

    SEVERITY_LEVELS = ("low", "medium", "high", "critical")
    EVALUATION_TIERS = ("nominal", "low", "medium", "high", "critical")

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
        is_daylight: bool = True,
        allow_nominal: bool = False,
    ) -> str:
        """Classify anomaly severity into 'low', 'medium', 'high', or 'critical' (and optionally 'nominal').

        Decision rules prioritize physical impact (capacity-normalized power delta and energy loss)
        over raw statistical scores. A high statistical confidence score alone does not elevate
        a physically insignificant deviation to High or Critical.
        """
        kw = max(0.0, float(loss_kw or 0.0))
        kwh = max(0.0, float(loss_kwh or 0.0))
        dur = max(1, int(duration_minutes or 15))

        # Resolve effective inverter rated AC capacity safely.
        # Defaults to 1000.0 kW if missing/invalid, and guards against whole-plant DC capacity substitution.
        eff_rated_kw = 1000.0
        if rated_kw is not None:
            try:
                val = float(rated_kw)
                if 0.0 < val <= 3000.0:
                    eff_rated_kw = val
                elif val > 3000.0:
                    # Guard against plant-level capacity mistakenly passed for an inverter
                    eff_rated_kw = 1250.0
            except (ValueError, TypeError):
                pass

        # Normalize relative deficit fraction
        pct = 0.0
        if deficit_pct is not None:
            try:
                val = float(deficit_pct)
                pct = (val / 100.0) if val > 1.0 else max(0.0, val)
            except (ValueError, TypeError):
                pass

        kw_rel = (kw / eff_rated_kw) if eff_rated_kw > 0 else 0.0
        rel_deficit = max(pct, kw_rel)

        # 0. Nighttime zero-power suppression (never flag normal night as trip/critical)
        if not is_daylight:
            return "nominal" if allow_nominal else "low"

        # 1. CRITICAL Tier
        # - Daylight trip with complete dropout or shutdown failure mode
        if anomaly_type in ("trip", "shutdown", "offline"):
            return "critical"

        if kw == 0.0 and kwh == 0.0 and rel_deficit == 0.0:
            return "nominal" if allow_nominal else "low"

        # - Relative deficit >= 50% sustained for >= 30 minutes
        # - Massive energy loss >= 300 kWh
        if rel_deficit >= 0.50 and dur >= 30:
            return "critical"
        if kwh >= 300.0:
            return "critical"
        if kw >= (eff_rated_kw * 0.75) and dur >= 30:
            return "critical"

        # 2. HIGH Tier
        # - Relative deficit >= 20% for >= 30 minutes
        # - Substantial energy loss >= 30 kWh with relative deficit >= 5%
        # - Significant energy loss >= 150 kWh with peak deficit >= 100 kW
        if rel_deficit >= 0.20 and dur >= 30:
            return "high"
        if kwh >= 30.0 and rel_deficit >= 0.05:
            return "high"
        if kwh >= 150.0 and kw >= 100.0:
            return "high"

        # 3. MEDIUM Tier
        # - Relative deficit >= 8% for >= 15 minutes
        # - Energy loss >= 10 kWh with relative deficit >= 2%
        # - Energy loss >= 20 kWh with relative deficit >= 1%
        # - Flatline/soiling failure modes with noticeable physical deficit
        if rel_deficit >= 0.08 and dur >= 15:
            return "medium"
        if kwh >= 10.0 and rel_deficit >= 0.02:
            return "medium"
        if kwh >= 20.0 and rel_deficit >= 0.01:
            return "medium"
        if anomaly_type in ("flatline", "soiling") and (kw >= 15.0 or kwh >= 5.0 or rel_deficit >= 0.05):
            return "medium"

        # 4. LOW Tier
        # - Relative deficit >= 3% or energy loss >= 1 kWh or power deficit >= 10 kW
        if rel_deficit >= 0.03 or kwh >= 1.0 or kw >= 10.0:
            return "low"

        # 5. NOMINAL Tier
        # Below justified alert thresholds (measurement noise)
        return "nominal" if allow_nominal else "low"


class FinancialLossPolicy:
    """Estimates energy loss in kWh and monetary value in INR."""

    @classmethod
    def calculate(
        cls,
        loss_kwh: float,
        power_deficit_kw: float = 0.0,
        duration_minutes: int = 15,
        tariff_inr_per_kwh: Optional[float] = None,
        default_tariff: Optional[float] = None,
    ) -> FinancialAssessment:
        """Calculate financial loss based on energy loss and configured tariff."""
        effective_tariff: Optional[float] = None
        if tariff_inr_per_kwh is not None and float(tariff_inr_per_kwh) > 0:
            effective_tariff = float(tariff_inr_per_kwh)
        elif default_tariff is not None and float(default_tariff) > 0:
            effective_tariff = float(default_tariff)

        effective_kwh = max(0.0, float(loss_kwh))
        financial_loss_inr = (effective_kwh * effective_tariff) if effective_tariff is not None else None

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
