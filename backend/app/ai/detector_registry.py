"""PlantIQ Anomaly Detector Framework & Plugin Registry (§12, Task S4-AI-01).

Provides:
- Central plugin registry pattern for anomaly detection algorithms.
- Unified DetectorContext and DetectedAnomaly data contracts.
- BaseDetector abstract base class with type-safe interfaces.
- Built-in implementations for 'zscore', 'iqr', 'deviation', and 'isolation_forest'
  (matching database CheckConstraint `ck_detectors_method`).
- Extensible solar field fault detectors: 'trip', 'flatline', 'clipping', 'soiling'.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Type, Union
from uuid import UUID
import numpy as np

try:
    from sklearn.ensemble import IsolationForest as SklearnIsolationForest
    HAS_SKLEARN = True
except ImportError:
    SklearnIsolationForest = None  # type: ignore
    HAS_SKLEARN = False


@dataclass
class DetectorContext:
    """Execution context provided to anomaly detectors."""

    plant_id: UUID
    asset_id: Optional[UUID] = None
    channel_id: Optional[UUID] = None
    canonical_key: str = "active_power"
    plant_name: Optional[str] = None
    asset_name: Optional[str] = None
    asset_type: Optional[str] = "inverter"
    rated_kw: Optional[float] = None
    capacity_dc_kwp: Optional[float] = None
    expected_pr: float = 0.80
    tariff_inr_per_kwh: Optional[float] = None
    cadence_seconds: int = 900  # Default 15-minute interval (900 seconds)
    irradiance_reference: Optional[Dict[datetime, float]] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectedAnomaly:
    """Standardized anomaly event emitted by any registered detector."""

    start_time: datetime
    end_time: datetime
    score: float  # Normalized anomaly severity score [0.0, 1.0]
    anomaly_type: str  # e.g. "zscore", "iqr", "deviation", "trip", "flatline", etc.
    summary: str
    metric_name: str = "active_power"
    severity: Optional[str] = None  # Populated or refined by SeverityPolicy
    actual_value: Optional[float] = None
    expected_value: Optional[float] = None
    delta: Optional[float] = None
    loss_kw: Optional[float] = None
    loss_kwh: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert detected anomaly to dictionary."""
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "score": round(self.score, 4),
            "anomaly_type": self.anomaly_type,
            "metric_name": self.metric_name,
            "severity": self.severity,
            "actual_value": round(self.actual_value, 2) if self.actual_value is not None else None,
            "expected_value": round(self.expected_value, 2) if self.expected_value is not None else None,
            "delta": round(self.delta, 2) if self.delta is not None else None,
            "loss_kw": round(self.loss_kw, 2) if self.loss_kw is not None else None,
            "loss_kwh": round(self.loss_kwh, 2) if self.loss_kwh is not None else None,
            "summary": self.summary,
            "details": self.details,
        }


class BaseDetector(ABC):
    """Abstract base class for all PlantIQ anomaly detection plugins."""

    name: str = "base"
    description: str = "Base Anomaly Detector"
    supported_signals: List[str] = []  # Empty means all signals supported

    @abstractmethod
    def detect(
        self,
        observations: Sequence[Tuple[datetime, float]],
        parameters: Dict[str, Any],
        context: DetectorContext,
    ) -> List[DetectedAnomaly]:
        """Execute anomaly detection on time-series observations.

        Args:
            observations: List of (timestamp, value) tuples sorted by timestamp.
            parameters: Configuration dictionary for algorithm hyperparameters.
            context: Plant and asset domain context.

        Returns:
            List of DetectedAnomaly objects.
        """
        pass


class DetectorRegistry:
    """Central plugin registry for discovering and executing anomaly detectors."""

    _registry: Dict[str, Type[BaseDetector]] = {}
    _metadata: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(
        cls,
        name: str,
        description: Optional[str] = None,
        supported_signals: Optional[List[str]] = None,
    ) -> Callable[[Type[BaseDetector]], Type[BaseDetector]]:
        """Decorator to register a detector plugin."""

        def decorator(subclass: Type[BaseDetector]) -> Type[BaseDetector]:
            cls._registry[name.lower()] = subclass
            cls._metadata[name.lower()] = {
                "name": name.lower(),
                "class_name": subclass.__name__,
                "description": description or subclass.description or subclass.__doc__ or "",
                "supported_signals": supported_signals or getattr(subclass, "supported_signals", []),
            }
            return subclass

        return decorator

    @classmethod
    def get(cls, name: str) -> BaseDetector:
        """Instantiate a registered detector by name."""
        key = name.lower()
        if key not in cls._registry:
            valid = ", ".join(sorted(cls._registry.keys()))
            raise KeyError(f"Detector '{name}' not found in registry. Registered detectors: [{valid}]")
        return cls._registry[key]()

    @classmethod
    def list_detectors(cls) -> List[str]:
        """List all registered detector names."""
        return sorted(cls._registry.keys())

    @classmethod
    def get_metadata(cls, name: str) -> Dict[str, Any]:
        """Get metadata for a specific detector."""
        key = name.lower()
        if key not in cls._metadata:
            raise KeyError(f"Detector '{name}' not found in registry.")
        return cls._metadata[key].copy()

    @classmethod
    def all_metadata(cls) -> List[Dict[str, Any]]:
        """Return metadata for all registered detectors."""
        return [cls._metadata[k].copy() for k in sorted(cls._metadata.keys())]

    @classmethod
    def has_detector(cls, name: str) -> bool:
        """Check if detector exists in registry."""
        return name.lower() in cls._registry

    @classmethod
    def clear(cls) -> None:
        """Clear registry (used for test isolation)."""
        cls._registry.clear()
        cls._metadata.clear()


# Convenience decorator alias
register_detector = DetectorRegistry.register


# =====================================================================
# Built-in Algorithm: 1. D1: Statistical Outlier Detector ('d1_statistical', 'zscore', 'iqr')
# =====================================================================
@register_detector(
    "d1_statistical",
    description="D1: Statistical Outlier Detector (Z-score / IQR / Spikes / Impossible Values)",
)
@register_detector("statistical", description="Statistical Outlier Detector")
class D1StatisticalDetector(BaseDetector):
    """Flags sudden spikes, drops, impossible sensor values, and statistical outliers via Z-score or IQR."""

    name = "d1_statistical"
    description = "Statistical Outlier Detector (Z-score / IQR / Spikes / Impossible Values)"
    default_mode = "zscore"

    def detect(
        self,
        observations: Sequence[Tuple[datetime, float]],
        parameters: Dict[str, Any],
        context: DetectorContext,
    ) -> List[DetectedAnomaly]:
        if not observations or len(observations) < 4:
            return []

        mode = str(parameters.get("mode", self.default_mode)).lower()
        # window_size for moving/rolling statistics (default 16 intervals ~ 4 hours; 0 or None means global batch)
        raw_win = parameters.get("window_size", 16 if self.name == "d1_statistical" else None)
        window_size = int(raw_win) if raw_win is not None and int(raw_win) > 0 else None

        filter_zeros = bool(parameters.get("filter_zeros", True))
        check_impossible = bool(parameters.get("check_impossible", self.name == "d1_statistical"))
        check_spikes_drops = bool(parameters.get("check_spikes_drops", self.name == "d1_statistical"))

        threshold = float(parameters.get("threshold", parameters.get("z_threshold", 3.0)))
        k_iqr = float(parameters.get("k", parameters.get("multiplier", 1.5)))

        rated_kw = float(context.rated_kw) if context.rated_kw is not None else (
            float(context.capacity_dc_kwp) * 0.90 if context.capacity_dc_kwp is not None else 1000.0
        )
        cadence_seconds = context.cadence_seconds

        ts_list = [obs[0] for obs in observations]
        val_arr = np.array([float(obs[1]) for obs in observations], dtype=float)
        n = len(val_arr)

        is_power_signal = context.canonical_key in (
            "active_power", "ac_power", "power_ac", "ac_power_kw",
            "dc_power", "power_dc", "dc_power_kw", "inverter_efficiency"
        )
        valid_mask = ~np.isnan(val_arr)
        if filter_zeros and is_power_signal:
            valid_mask = valid_mask & (val_arr > 0.0)

        # 1. Physical Impossibility Checking
        impossible_mask = np.zeros(n, dtype=bool)
        impossible_reasons: Dict[int, str] = {}
        if check_impossible:
            min_val = parameters.get("min_val")
            max_val = parameters.get("max_val")

            if min_val is not None:
                min_phys = float(min_val)
            elif is_power_signal:
                min_phys = -5.0  # slight negative tare loss allowed
            elif "irradiance" in context.canonical_key or "irradiation" in context.canonical_key:
                min_phys = -1.0
            elif "efficiency" in context.canonical_key or "pr" in context.canonical_key:
                min_phys = 0.0
            else:
                min_phys = None

            if max_val is not None:
                max_phys = float(max_val)
            elif is_power_signal:
                max_phys = rated_kw * 1.30  # 130% of rated capacity
            elif "irradiance" in context.canonical_key or "irradiation" in context.canonical_key:
                max_phys = 1500.0
            elif "efficiency" in context.canonical_key:
                max_phys = 1.05
            elif "pr" in context.canonical_key:
                max_phys = 1.25
            else:
                max_phys = None

            for i in range(n):
                v = val_arr[i]
                if np.isnan(v):
                    continue
                if min_phys is not None and v < min_phys:
                    impossible_mask[i] = True
                    impossible_reasons[i] = f"Observed {v:.2f} below physical minimum {min_phys:.2f}"
                elif max_phys is not None and v > max_phys:
                    impossible_mask[i] = True
                    impossible_reasons[i] = f"Observed {v:.2f} above physical maximum {max_phys:.2f}"

        # 2. Rate-of-Change (Spikes & Drops) Checking
        spike_drop_mask = np.zeros(n, dtype=bool)
        spike_drop_reasons: Dict[int, str] = {}
        if check_spikes_drops:
            max_ramp = parameters.get("max_ramp_rate")
            if max_ramp is not None:
                ramp_limit = float(max_ramp)
            elif is_power_signal:
                ramp_limit = rated_kw * 0.70  # >70% capacity jump in a single step
            else:
                ramp_limit = None

            if ramp_limit is not None:
                for i in range(1, n):
                    if valid_mask[i] and valid_mask[i - 1]:
                        diff = val_arr[i] - val_arr[i - 1]
                        dt = (ts_list[i] - ts_list[i - 1]).total_seconds()
                        if dt <= cadence_seconds * 2:
                            if diff >= ramp_limit:
                                spike_drop_mask[i] = True
                                spike_drop_reasons[i] = f"Sudden positive spike (+{diff:.1f} in {int(dt/60)}m)"
                            elif diff <= -ramp_limit:
                                spike_drop_mask[i] = True
                                spike_drop_reasons[i] = f"Sudden negative drop ({diff:.1f} in {int(dt/60)}m)"

        # 3. Statistical Deviation (Z-score or IQR)
        stat_outlier_mask = np.zeros(n, dtype=bool)
        stat_scores = np.zeros(n, dtype=float)
        expected_baselines = np.zeros(n, dtype=float)

        if mode == "iqr":
            if window_size and window_size >= 4:
                # Rolling / Moving IQR
                for i in range(n):
                    if not valid_mask[i]:
                        continue
                    w_start = max(0, i - window_size + 1)
                    w_vals = val_arr[w_start : i + 1]
                    w_valid = w_vals[valid_mask[w_start : i + 1]]
                    if len(w_valid) < 4:
                        continue
                    q1 = float(np.percentile(w_valid, 25))
                    q3 = float(np.percentile(w_valid, 75))
                    iqr = q3 - q1
                    med = float(np.median(w_valid))
                    expected_baselines[i] = med
                    if iqr >= 1e-4:
                        lb = q1 - (k_iqr * iqr)
                        ub = q3 + (k_iqr * iqr)
                        v = val_arr[i]
                        if v < lb:
                            stat_outlier_mask[i] = True
                            dist = lb - v
                            stat_scores[i] = min(1.0, max(0.1, 0.5 + (dist / (2.0 * iqr))))
                        elif v > ub:
                            stat_outlier_mask[i] = True
                            dist = v - ub
                            stat_scores[i] = min(1.0, max(0.1, 0.5 + (dist / (2.0 * iqr))))
            else:
                # Global batch IQR
                valid_vals = val_arr[valid_mask]
                if len(valid_vals) >= 4:
                    q1 = float(np.percentile(valid_vals, 25))
                    q3 = float(np.percentile(valid_vals, 75))
                    iqr = q3 - q1
                    med = float(np.median(valid_vals))
                    expected_baselines[:] = med
                    if iqr >= 1e-4:
                        lb = q1 - (k_iqr * iqr)
                        ub = q3 + (k_iqr * iqr)
                        for i in range(n):
                            if valid_mask[i]:
                                v = val_arr[i]
                                if v < lb:
                                    stat_outlier_mask[i] = True
                                    dist = lb - v
                                    stat_scores[i] = min(1.0, max(0.1, 0.5 + (dist / (2.0 * iqr))))
                                elif v > ub:
                                    stat_outlier_mask[i] = True
                                    dist = v - ub
                                    stat_scores[i] = min(1.0, max(0.1, 0.5 + (dist / (2.0 * iqr))))
        else:
            # Z-Score (Moving or Global)
            if window_size and window_size >= 4:
                for i in range(n):
                    if not valid_mask[i]:
                        continue
                    w_start = max(0, i - window_size + 1)
                    w_vals = val_arr[w_start : i + 1]
                    w_valid = w_vals[valid_mask[w_start : i + 1]]
                    if len(w_valid) < 4:
                        continue
                    w_mean = float(np.mean(w_valid))
                    w_std = float(np.std(w_valid))
                    expected_baselines[i] = w_mean
                    if w_std >= 1e-4:
                        z = abs(val_arr[i] - w_mean) / w_std
                        if z >= threshold:
                            stat_outlier_mask[i] = True
                            stat_scores[i] = min(1.0, max(0.1, z / (threshold * 2.0)))
            else:
                valid_vals = val_arr[valid_mask]
                if len(valid_vals) >= 4:
                    mean = float(np.mean(valid_vals))
                    std = float(np.std(valid_vals))
                    expected_baselines[:] = mean
                    if std >= 1e-4:
                        for i in range(n):
                            if valid_mask[i]:
                                z = abs(val_arr[i] - mean) / std
                                if z >= threshold:
                                    stat_outlier_mask[i] = True
                                    stat_scores[i] = min(1.0, max(0.1, z / (threshold * 2.0)))

        # Combine flagged points
        flagged_indices = [
            i for i in range(n)
            if impossible_mask[i] or spike_drop_mask[i] or stat_outlier_mask[i]
        ]
        if not flagged_indices:
            return []

        # Group contiguous spans
        grouped_spans: List[List[int]] = []
        current_span = [flagged_indices[0]]

        for idx in flagged_indices[1:]:
            prev_idx = current_span[-1]
            dt = (ts_list[idx] - ts_list[prev_idx]).total_seconds()
            if dt <= cadence_seconds * 2:
                current_span.append(idx)
            else:
                grouped_spans.append(current_span)
                current_span = [idx]
        grouped_spans.append(current_span)

        anomalies: List[DetectedAnomaly] = []
        for span in grouped_spans:
            start_ts = ts_list[span[0]]
            end_ts = ts_list[span[-1]]
            span_vals = val_arr[span]
            dur_mins = max(1, int((len(span) * cadence_seconds) / 60))

            subtypes = set()
            reasons = []
            max_score = 0.5
            for i in span:
                if impossible_mask[i]:
                    subtypes.add("impossible_value")
                    reasons.append(impossible_reasons.get(i, "Impossible sensor value"))
                    max_score = 1.0
                if spike_drop_mask[i]:
                    subtypes.add("spike_or_drop")
                    reasons.append(spike_drop_reasons.get(i, "Ramp rate surge/drop"))
                    max_score = max(max_score, 0.85)
                if stat_outlier_mask[i]:
                    subtypes.add(mode)
                    max_score = max(max_score, stat_scores[i])

            avg_actual = float(np.mean(span_vals))
            avg_expected = float(np.mean([expected_baselines[i] for i in span]))
            if avg_expected <= 0:
                avg_expected = rated_kw * 0.80

            delta = avg_actual - avg_expected
            loss_kw = max(0.0, avg_expected - avg_actual) if avg_actual < avg_expected else 0.0
            hours = dur_mins / 60.0
            loss_kwh = loss_kw * hours

            asset_label = context.asset_name or (str(context.asset_id)[:8] if context.asset_id else "Asset")
            subtype_str = "/".join(sorted(subtypes)) or mode
            summary = (
                f"Statistical outlier ({subtype_str}) on {asset_label} ({context.canonical_key}): "
                f"observed avg {avg_actual:.1f} vs expected {avg_expected:.1f} over {dur_mins} mins."
            )

            anomalies.append(
                DetectedAnomaly(
                    start_time=start_ts,
                    end_time=end_ts,
                    score=round(max_score, 4),
                    anomaly_type=self.name,
                    metric_name=context.canonical_key,
                    summary=summary,
                    actual_value=avg_actual,
                    expected_value=avg_expected,
                    delta=delta,
                    loss_kw=loss_kw,
                    loss_kwh=loss_kwh,
                    details={
                        "mode": mode,
                        "window_size": window_size,
                        "subtypes": sorted(list(subtypes)),
                        "reasons": reasons[:3],
                        "point_count": len(span),
                        "duration_minutes": dur_mins,
                    },
                )
            )

        return anomalies


@register_detector("zscore", description="Statistical Z-Score Outlier Detector (μ ± kσ)")
class ZScoreDetector(D1StatisticalDetector):
    """Flags values whose standard deviation distance |(x - μ) / σ| exceeds threshold."""

    name = "zscore"
    description = "Statistical Z-Score Outlier Detector"
    default_mode = "zscore"


@register_detector("iqr", description="Interquartile Range Outlier Detector (Q1 - k*IQR, Q3 + k*IQR)")
class IQRDetector(D1StatisticalDetector):
    """Flags points falling outside robust quartile boundaries [Q1 - k*IQR, Q3 + k*IQR]."""

    name = "iqr"
    description = "Interquartile Range Outlier Detector"
    default_mode = "iqr"


# =====================================================================
# Built-in Algorithm: 2. D2: Performance Ratio Deviation Detector ('d2_pr_deviation', 'deviation')
# =====================================================================
@register_detector(
    "d2_pr_deviation",
    description="D2: Performance Ratio Deviation Detector (Actual PR vs Expected Baseline)",
)
@register_detector("pr_deviation", description="Performance Ratio Deviation Detector")
class D2PRDeviationDetector(BaseDetector):
    """Evaluates actual Performance Ratio (PR) against expected baseline to flag shading, soiling, or degradation."""

    name = "d2_pr_deviation"
    description = "Performance Ratio Deviation Detector (Actual PR vs Expected Baseline)"

    def detect(
        self,
        observations: Sequence[Tuple[datetime, float]],
        parameters: Dict[str, Any],
        context: DetectorContext,
    ) -> List[DetectedAnomaly]:
        if not observations or len(observations) < 3:
            return []

        threshold_pct = float(parameters.get("threshold_pct", parameters.get("pr_tolerance", 0.15)))
        min_expected_kw = float(parameters.get("min_expected_kw", 5.0))
        min_poa = float(parameters.get("min_poa_irradiance", 100.0))
        cadence_seconds = context.cadence_seconds

        ts_list = [obs[0] for obs in observations]
        val_arr = np.array([float(obs[1]) for obs in observations], dtype=float)

        rated_kw = float(context.rated_kw) if context.rated_kw is not None else (
            float(context.capacity_dc_kwp) * 0.90 if context.capacity_dc_kwp is not None else 1000.0
        )
        expected_pr = float(context.expected_pr) if context.expected_pr is not None else 0.80

        anom_indices: List[int] = []
        expected_series: List[float] = []
        actual_pr_series: List[Optional[float]] = []
        irradiance_used: bool = False

        for i, (ts, actual_val) in enumerate(observations):
            expected_kw = 0.0
            actual_pr = None

            if context.irradiance_reference and ts in context.irradiance_reference:
                poa = float(context.irradiance_reference[ts])
                if poa >= min_poa:
                    irradiance_used = True
                    # PR = (P / P_rated) / (G_poa / 1000)
                    expected_kw = (poa / 1000.0) * rated_kw * expected_pr
                    if not np.isnan(actual_val) and actual_val >= 0:
                        actual_pr = (actual_val / rated_kw) / (poa / 1000.0)
            else:
                # Fallback: estimate from diurnal clear-sky envelope (06:00 to 18:00)
                hour = ts.hour + (ts.minute / 60.0)
                if 6.0 <= hour <= 18.0:
                    solar_factor = math.sin((hour - 6.0) / 12.0 * math.pi)
                    if solar_factor > 0.05:
                        expected_kw = rated_kw * 0.85 * solar_factor * expected_pr
                        if not np.isnan(actual_val) and actual_val >= 0 and expected_kw > 0:
                            actual_pr = (actual_val / expected_kw) * expected_pr

            expected_series.append(expected_kw)
            actual_pr_series.append(actual_pr)

            if expected_kw >= min_expected_kw and not np.isnan(actual_val):
                deficit = expected_kw - actual_val
                deficit_pct = deficit / expected_kw
                if deficit_pct >= threshold_pct:
                    anom_indices.append(i)

        if not anom_indices:
            return []

        # Group contiguous intervals
        grouped_spans: List[List[int]] = []
        current_span = [anom_indices[0]]

        for idx in anom_indices[1:]:
            prev_idx = current_span[-1]
            dt = (ts_list[idx] - ts_list[prev_idx]).total_seconds()
            if dt <= cadence_seconds * 2:
                current_span.append(idx)
            else:
                grouped_spans.append(current_span)
                current_span = [idx]
        grouped_spans.append(current_span)

        distinct_days_with_deficit = len(set(ts_list[i].date() for i in anom_indices))
        is_multi_day = distinct_days_with_deficit >= 2

        anomalies: List[DetectedAnomaly] = []
        for span in grouped_spans:
            start_ts = ts_list[span[0]]
            end_ts = ts_list[span[-1]]
            actual_vals = val_arr[span]
            exp_vals = [expected_series[i] for i in span]
            span_prs = [actual_pr_series[i] for i in span if actual_pr_series[i] is not None]

            avg_actual = float(np.mean(actual_vals))
            avg_expected = float(np.mean(exp_vals))
            avg_deficit = max(0.0, avg_expected - avg_actual)
            deficit_pct = (avg_deficit / avg_expected) if avg_expected > 0 else 0.0

            dur_mins = max(1, int((len(span) * cadence_seconds) / 60))
            hours = dur_mins / 60.0
            loss_kw = avg_deficit
            loss_kwh = loss_kw * hours

            avg_pr = float(np.mean(span_prs)) if span_prs else (
                (avg_actual / avg_expected) * expected_pr if avg_expected > 0 else 0.0
            )
            pr_drop = max(0.0, expected_pr - avg_pr)

            # Root cause heuristic
            if is_multi_day:
                root_cause = "dust_accumulation_or_equipment_degradation"
            elif any(9 <= ts_list[i].hour <= 14 and val_arr[i] < avg_expected * 0.4 for i in span):
                root_cause = "inverter_curtailment_or_thermal_throttling"
            else:
                root_cause = "shading_or_soiling"

            norm_score = min(1.0, max(0.1, deficit_pct))
            asset_label = context.asset_name or (str(context.asset_id)[:8] if context.asset_id else "Asset")
            summary = (
                f"PR deviation anomaly on {asset_label} ({context.canonical_key}): "
                f"actual PR {avg_pr:.2f} vs expected {expected_pr:.2f} ({deficit_pct*100:.1f}% deficit) "
                f"over {dur_mins} mins [indicates {root_cause.replace('_', ' ')}]."
            )

            anomalies.append(
                DetectedAnomaly(
                    start_time=start_ts,
                    end_time=end_ts,
                    score=norm_score,
                    anomaly_type=self.name,
                    metric_name=context.canonical_key,
                    summary=summary,
                    actual_value=avg_actual,
                    expected_value=avg_expected,
                    delta=-avg_deficit,
                    loss_kw=loss_kw,
                    loss_kwh=loss_kwh,
                    details={
                        "actual_pr": round(avg_pr, 3),
                        "expected_pr": round(expected_pr, 3),
                        "pr_deficit": round(pr_drop, 3),
                        "deficit_pct": round(deficit_pct * 100.0, 1),
                        "threshold_pct": round(threshold_pct * 100.0, 1),
                        "root_cause_indicator": root_cause,
                        "irradiance_reference_used": irradiance_used,
                        "duration_minutes": dur_mins,
                        "point_count": len(span),
                    },
                )
            )

        return anomalies


@register_detector("deviation", description="Expected Generation Deviation & Peer Underperformance")
class DeviationDetector(D2PRDeviationDetector):
    """Flags severe underperformance by comparing observed power against expected power."""

    name = "deviation"
    description = "Expected Generation Deviation Detector"


# =====================================================================
# Built-in Algorithm: 3. D3: Irradiance-Residual Detector ('d3_irradiance_residual')
# =====================================================================
def calculate_solar_position(
    dt: datetime,
    latitude: float,
    longitude: float,
) -> Tuple[float, float, float]:
    """Calculate solar position angles (cos_zenith, zenith_degrees, elevation_degrees).

    Uses astronomical solar equations accounting for declination, equation of time,
    local solar time, and hour angle.

    Args:
        dt: Datetime object. If naive, assumed UTC.
        latitude: Geographic latitude in decimal degrees (-90 to +90).
        longitude: Geographic longitude in decimal degrees (-180 to +180).

    Returns:
        (cos_zenith, zenith_deg, elevation_deg)
    """
    if dt.tzinfo is None:
        dt_utc = dt.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt.astimezone(timezone.utc)

    # Day of year N (1 to 366)
    n = dt_utc.timetuple().tm_yday

    # Solar declination angle delta (degrees) via Cooper formula
    delta_deg = 23.45 * math.sin(math.radians((360.0 / 365.0) * (284 + n)))
    delta_rad = math.radians(delta_deg)

    # Equation of Time EoT (minutes)
    b_rad = math.radians((360.0 / 365.0) * (n - 81))
    eot_min = 9.87 * math.sin(2 * b_rad) - 7.53 * math.cos(b_rad) - 1.5 * math.sin(b_rad)

    # Decimal hours in UTC
    utc_hours = dt_utc.hour + (dt_utc.minute / 60.0) + (dt_utc.second / 3600.0)

    # Local Solar Time (LST) in hours
    lst_hours = (utc_hours + (longitude / 15.0) + (eot_min / 60.0)) % 24.0

    # Solar hour angle omega (degrees): 15 deg per hour from solar noon (12:00)
    omega_deg = 15.0 * (lst_hours - 12.0)
    omega_rad = math.radians(omega_deg)

    lat_rad = math.radians(latitude)

    # cos(zenith) = sin(lat)*sin(delta) + cos(lat)*cos(delta)*cos(omega)
    cos_zenith = math.sin(lat_rad) * math.sin(delta_rad) + math.cos(lat_rad) * math.cos(delta_rad) * math.cos(omega_rad)

    if cos_zenith <= 0.0:
        return 0.0, 90.0, 0.0

    cos_zenith = min(1.0, max(0.0, cos_zenith))
    zenith_deg = math.degrees(math.acos(cos_zenith))
    elevation_deg = max(0.0, 90.0 - zenith_deg)

    return cos_zenith, zenith_deg, elevation_deg


def calculate_clear_sky_irradiance(
    dt: datetime,
    latitude: float,
    longitude: float,
    solar_constant: float = 1098.0,
) -> float:
    """Calculate theoretical clear-sky Global Horizontal Irradiance (GHI in W/m²).

    Implements the Haurwitz clear-sky solar radiation model:
        GHI_clear = 1098 * cos(theta_z) * exp(-0.057 / cos(theta_z))  [for cos(theta_z) > 0.01]
    Yields realistic diurnal irradiance curves with peak ~1000 W/m² under clear skies.
    """
    cos_zenith, _, _ = calculate_solar_position(dt, latitude, longitude)
    if cos_zenith <= 0.01:
        return 0.0

    ghi_clear = solar_constant * cos_zenith * math.exp(-0.057 / cos_zenith)
    return max(0.0, float(ghi_clear))


def calculate_clear_sky_expected_power(
    dt: datetime,
    latitude: float,
    longitude: float,
    rated_kw: float = 1000.0,
    expected_pr: float = 0.80,
) -> float:
    """Calculate theoretical expected clear-sky AC active power generation in kW."""
    ghi_clear = calculate_clear_sky_irradiance(dt, latitude, longitude)
    if ghi_clear <= 0.0:
        return 0.0
    p_clear = (ghi_clear / 1000.0) * rated_kw * expected_pr
    return float(p_clear)


@register_detector(
    "d3_irradiance_residual",
    description="D3: Irradiance-Residual Detector (Clear-Sky Model & Robust Residual Analysis)",
)
@register_detector("irradiance_residual", description="Clear-Sky Irradiance-Residual Detector")
@register_detector("d3", description="D3 Irradiance-Residual Outlier Detector")
class D3IrradianceResidualDetector(BaseDetector):
    """Detects site-specific performance degradation and sensor obstructions using clear-sky residual analysis.

    Distinguishes natural weather-induced cloud attenuation from genuine site defects:
    - Calculates clear-sky theoretical irradiance and expected AC power using site coordinates.
    - Filters transient cloud-cover by identifying high-frequency irradiance fluctuations and
      measured weather pyranometer drops.
    - Uses robust regression (Theil-Sen / median slope) over unclouded points to isolate
      persistent residual gaps caused by soiling, module degradation, or sensor obstruction.
    """

    name = "d3_irradiance_residual"
    description = "D3: Clear-Sky Irradiance-Residual Anomaly Detector"

    def detect(
        self,
        observations: Sequence[Tuple[datetime, float]],
        parameters: Dict[str, Any],
        context: DetectorContext,
    ) -> List[DetectedAnomaly]:
        if not observations or len(observations) < 4:
            return []

        # Geographic coordinates (defaults: Pavagada / Karnataka solar belt)
        latitude = float(context.latitude if context.latitude is not None else parameters.get("latitude", 14.1))
        longitude = float(context.longitude if context.longitude is not None else parameters.get("longitude", 77.3))

        rated_kw = float(context.rated_kw if context.rated_kw is not None else (
            float(context.capacity_dc_kwp) * 0.90 if context.capacity_dc_kwp is not None else 1000.0
        ))
        expected_pr = float(context.expected_pr if context.expected_pr is not None else 0.80)
        cadence_seconds = context.cadence_seconds

        threshold_pct = float(parameters.get("threshold_pct", 0.18))
        min_clearsky_kw = float(parameters.get("min_clearsky_kw", max(5.0, rated_kw * 0.05)))
        cloud_variance_threshold = float(parameters.get("cloud_variance_threshold", 0.22))
        min_consecutive = int(parameters.get("min_consecutive", 2))

        is_irradiance_channel = context.canonical_key in (
            "poa_irradiance", "ghi_irradiance", "irradiation", "irradiance", "weather_irradiance"
        )

        ts_list = [obs[0] for obs in observations]
        val_arr = np.array([float(obs[1]) for obs in observations], dtype=float)
        n = len(observations)

        # 1. Compute theoretical clear-sky baseline series
        clearsky_baseline = np.zeros(n, dtype=float)
        clearsky_ghi = np.zeros(n, dtype=float)

        for i, ts in enumerate(ts_list):
            ghi = calculate_clear_sky_irradiance(ts, latitude, longitude)
            clearsky_ghi[i] = ghi
            if is_irradiance_channel:
                clearsky_baseline[i] = ghi
            else:
                clearsky_baseline[i] = (ghi / 1000.0) * rated_kw * expected_pr

        # Daylight mask (baseline exceeds minimal daylight generation)
        daylight_mask = clearsky_baseline >= min_clearsky_kw

        # 2. Identify natural cloud attenuation vs clear-sky intervals
        # Clouds cause either:
        # a) Measured pyranometer irradiance to drop significantly while power also drops proportionally, OR
        # b) Rapid high-frequency variance in power ratio (Delta(y/x)) that recovers quickly
        cloud_attenuation_mask = np.zeros(n, dtype=bool)
        sensor_obstruction_mask = np.zeros(n, dtype=bool)

        has_pyranometer_ref = bool(context.irradiance_reference)

        for i in range(n):
            if not daylight_mask[i] or np.isnan(val_arr[i]):
                continue

            ts = ts_list[i]
            x_clear = clearsky_baseline[i]
            y_act = val_arr[i]

            if has_pyranometer_ref and ts in context.irradiance_reference:
                meas_ghi = float(context.irradiance_reference[ts])
                c_ghi = clearsky_ghi[i]
                if c_ghi > 50.0:
                    clearness_ratio = meas_ghi / c_ghi
                    # Weather pyranometer indicates heavy cloud cover
                    if clearness_ratio < 0.65:
                        expected_cloud_power = (meas_ghi / 1000.0) * rated_kw * expected_pr
                        # If actual power tracks the lower pyranometer irradiance, it's natural cloud cover
                        if not is_irradiance_channel:
                            if abs(y_act - expected_cloud_power) <= max(15.0, expected_cloud_power * 0.35):
                                cloud_attenuation_mask[i] = True
                            elif y_act >= expected_cloud_power * 1.4 and meas_ghi < c_ghi * 0.4:
                                # Inverter generating well but pyranometer reads very low -> pyranometer obstruction!
                                sensor_obstruction_mask[i] = True
                        else:
                            # It's an irradiance channel itself
                            cloud_attenuation_mask[i] = True

        # Secondary cloud-variance filter (temporal chopiness filter without or alongside pyranometer)
        # Compute normalized ratio r_i = y_i / x_i for daylight points
        norm_ratios = np.zeros(n, dtype=float)
        for i in range(n):
            if daylight_mask[i] and clearsky_baseline[i] > 0 and not np.isnan(val_arr[i]):
                norm_ratios[i] = max(0.0, val_arr[i] / clearsky_baseline[i])

        for i in range(1, n - 1):
            if daylight_mask[i] and not cloud_attenuation_mask[i] and not sensor_obstruction_mask[i]:
                r_prev = norm_ratios[i - 1]
                r_curr = norm_ratios[i]
                r_next = norm_ratios[i + 1]
                # If there is a sharp dip that recovers in adjacent 1-2 intervals, it's a passing cloud
                if r_curr < 0.75 and (r_prev - r_curr > cloud_variance_threshold or r_next - r_curr > cloud_variance_threshold):
                    cloud_attenuation_mask[i] = True

        # 3. Robust regression / median slope estimation on unclouded daylight points
        unclouded_mask = daylight_mask & (~cloud_attenuation_mask) & (~np.isnan(val_arr)) & (val_arr >= 0.0)
        unclouded_count = int(np.sum(unclouded_mask))

        if unclouded_count >= 3:
            ratios_clean = norm_ratios[unclouded_mask]
            beta_robust = float(np.median(ratios_clean))
        else:
            beta_robust = 1.0

        # 4. Residual analysis and flagging
        # Residual gap: e_i = clearsky_baseline[i] - val_arr[i]
        # Deficit percentage: e_i / clearsky_baseline[i]
        flagged_mask = np.zeros(n, dtype=bool)
        residual_series = np.zeros(n, dtype=float)
        rel_residual_series = np.zeros(n, dtype=float)

        for i in range(n):
            if not daylight_mask[i] or np.isnan(val_arr[i]):
                continue

            # Skip cloud-attenuated intervals (not actionable site defects)
            if cloud_attenuation_mask[i] and not sensor_obstruction_mask[i]:
                continue

            x_exp = clearsky_baseline[i]
            y_act = val_arr[i]
            residual = x_exp - y_act
            rel_res = (residual / x_exp) if x_exp > 0 else 0.0

            residual_series[i] = residual
            rel_residual_series[i] = rel_res

            if rel_res >= threshold_pct or sensor_obstruction_mask[i]:
                flagged_mask[i] = True

        flagged_indices = [i for i in range(n) if flagged_mask[i]]
        if not flagged_indices:
            return []

        # 5. Group contiguous intervals into anomaly spans
        grouped_spans: List[List[int]] = []
        current_span = [flagged_indices[0]]

        for idx in flagged_indices[1:]:
            prev_idx = current_span[-1]
            dt = (ts_list[idx] - ts_list[prev_idx]).total_seconds()
            if dt <= cadence_seconds * 2:
                current_span.append(idx)
            else:
                grouped_spans.append(current_span)
                current_span = [idx]
        grouped_spans.append(current_span)

        anomalies: List[DetectedAnomaly] = []
        distinct_days = len(set(ts_list[i].date() for i in flagged_indices))
        is_multi_day = distinct_days >= 2

        for span in grouped_spans:
            if len(span) < min_consecutive:
                continue

            start_ts = ts_list[span[0]]
            end_ts = ts_list[span[-1]]
            span_actual = val_arr[span]
            span_expected = clearsky_baseline[span]
            span_residuals = residual_series[span]
            span_rel_residuals = rel_residual_series[span]

            dur_mins = max(1, int((len(span) * cadence_seconds) / 60))
            hours = dur_mins / 60.0

            avg_actual = float(np.mean(span_actual))
            avg_expected = float(np.mean(span_expected))
            avg_deficit = float(np.mean(span_residuals))
            avg_rel_deficit = float(np.mean(span_rel_residuals))

            loss_kw = max(0.0, avg_deficit)
            loss_kwh = loss_kw * hours

            # Determine root-cause indicator
            has_sensor_obs = any(sensor_obstruction_mask[i] for i in span)
            if has_sensor_obs:
                root_cause = "sensor_obstruction_or_soiled_pyranometer"
            elif is_irradiance_channel:
                root_cause = "sensor_obstruction_or_pyranometer_soiling"
            elif any(clearsky_baseline[i] >= rated_kw * 0.30 and span_actual[k] <= max(5.0, rated_kw * 0.05) for k, i in enumerate(span)):
                root_cause = "inverter_trip_under_clearsky"
            elif is_multi_day or (np.std(span_rel_residuals) < 0.10 and avg_rel_deficit >= 0.20):
                root_cause = "severe_dust_accumulation_or_module_degradation"
            else:
                root_cause = "irradiance_residual_underperformance"

            norm_score = min(1.0, max(0.2, avg_rel_deficit))
            asset_label = context.asset_name or (str(context.asset_id)[:8] if context.asset_id else "SolarAsset")

            unit_label = "W/m²" if is_irradiance_channel else "kW"
            summary = (
                f"Clear-sky irradiance-residual anomaly on {asset_label} ({context.canonical_key}): "
                f"actual {avg_actual:.1f} {unit_label} vs clear-sky {avg_expected:.1f} {unit_label} "
                f"({avg_rel_deficit * 100.0:.1f}% deficit) over {dur_mins} mins [{root_cause.replace('_', ' ')}]."
            )

            anomalies.append(
                DetectedAnomaly(
                    start_time=start_ts,
                    end_time=end_ts,
                    score=round(norm_score, 4),
                    anomaly_type="d3_irradiance_residual",
                    metric_name=context.canonical_key,
                    summary=summary,
                    actual_value=avg_actual,
                    expected_value=avg_expected,
                    delta=-avg_deficit,
                    loss_kw=loss_kw,
                    loss_kwh=loss_kwh,
                    details={
                        "clear_sky_model": "haurwitz_astronomical",
                        "latitude": latitude,
                        "longitude": longitude,
                        "robust_slope_beta": round(beta_robust, 3),
                        "deficit_pct": round(avg_rel_deficit * 100.0, 1),
                        "threshold_pct": round(threshold_pct * 100.0, 1),
                        "root_cause_indicator": root_cause,
                        "cloud_attenuated_points_filtered": int(np.sum(cloud_attenuation_mask)),
                        "unclouded_points_evaluated": unclouded_count,
                        "duration_minutes": dur_mins,
                        "point_count": len(span),
                    },
                )
            )

        return anomalies


# =====================================================================
# Built-in Algorithm: 4. D4: Isolation Forest Detector ('d4_isolation_forest', 'isolation_forest')
# =====================================================================
class _PureIsolationTree:
    """Fallback single isolation tree recursively partitioning sub-sampled data."""

    def __init__(self, x: np.ndarray, current_depth: int = 0, max_depth: int = 10):
        self.depth = current_depth
        self.size = len(x)
        self.is_leaf = True
        self.split_val: Optional[float] = None
        self.split_feat: int = 0
        self.left: Optional["_PureIsolationTree"] = None
        self.right: Optional["_PureIsolationTree"] = None

        if current_depth < max_depth and self.size > 1:
            if x.ndim == 1:
                feat_idx = 0
                vals = x
            else:
                feat_idx = int(np.random.randint(0, x.shape[1]))
                vals = x[:, feat_idx]

            val_min, val_max = float(np.min(vals)), float(np.max(vals))
            if val_max > val_min:
                self.split_feat = feat_idx
                self.split_val = float(np.random.uniform(val_min, val_max))
                left_mask = vals < self.split_val
                if np.any(left_mask) and not np.all(left_mask):
                    self.is_leaf = False
                    self.left = _PureIsolationTree(x[left_mask], current_depth + 1, max_depth)
                    self.right = _PureIsolationTree(x[~left_mask], current_depth + 1, max_depth)

    def path_length(self, val: np.ndarray) -> float:
        """Compute path length required to isolate a sample."""
        if self.is_leaf or self.split_val is None:
            if self.size <= 1:
                return float(self.depth)
            c_factor = 2.0 * (math.log(self.size - 1) + 0.5772156649) - (2.0 * (self.size - 1) / self.size)
            return float(self.depth) + max(0.0, c_factor)

        sample_val = val if (np.isscalar(val) or val.ndim == 0) else val[self.split_feat]
        if sample_val < self.split_val:
            return self.left.path_length(val) if self.left else float(self.depth)
        else:
            return self.right.path_length(val) if self.right else float(self.depth)


def extract_per_asset_telemetry_features(
    observations: Sequence[Tuple[datetime, float]],
    context: DetectorContext,
    window_size: int = 4,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[str]]:
    """Extract multi-variable telemetry feature matrix per asset across rolling time windows.

    Features engineered:
    1. raw_value: Raw telemetry signal reading y_t
    2. rolling_mean: Moving central tendency across rolling window W
    3. rolling_std: Rolling signal volatility / jitter across window W
    4. ramp_delta: Rate-of-change gradient Delta y_t = y_t - y_{t-1}
    5. loading_ratio: Capacity-normalized loading ratio y_t / P_rated
    6. diurnal_factor: Diurnal solar cycle curve factor sin(pi * (h - 6) / 12)
    7. expected_ratio: Ratio of actual power to expected clear-sky power

    Returns:
        (feature_matrix X, valid_mask, expected_baselines, feature_names)
    """
    n = len(observations)
    ts_list = [obs[0] for obs in observations]
    val_arr = np.array([float(obs[1]) for obs in observations], dtype=float)

    rated_kw = float(context.rated_kw if context.rated_kw is not None else 1000.0)
    expected_pr = float(context.expected_pr if context.expected_pr is not None else 0.80)
    latitude = float(context.latitude if context.latitude is not None else 14.1)
    longitude = float(context.longitude if context.longitude is not None else 77.3)

    is_power_channel = context.canonical_key in (
        "active_power", "ac_power", "ac_power_kw", "power_ac", "dc_power", "inverter_efficiency"
    )

    feature_names = [
        "raw_value",
        "rolling_mean",
        "rolling_std",
        "ramp_delta",
        "loading_ratio",
        "diurnal_factor",
        "expected_ratio",
    ]

    X = np.zeros((n, len(feature_names)), dtype=float)
    expected_baselines = np.zeros(n, dtype=float)

    w = max(2, window_size)

    for i in range(n):
        ts = ts_list[i]
        val = val_arr[i]
        h = ts.hour + (ts.minute / 60.0) + (ts.second / 3600.0)

        # Expected clear-sky power
        if is_power_channel:
            exp_p = calculate_clear_sky_expected_power(ts, latitude, longitude, rated_kw=rated_kw, expected_pr=expected_pr)
        else:
            exp_p = calculate_clear_sky_irradiance(ts, latitude, longitude)

        # Fallback to moving daylight envelope if astronomical model is not aligned with timestamps
        if exp_p <= 5.0 and val > 10.0:
            exp_p = rated_kw * 0.80

        expected_baselines[i] = exp_p

        # Rolling window
        w_start = max(0, i - w + 1)
        w_vals = val_arr[w_start : i + 1]
        valid_w = w_vals[~np.isnan(w_vals)]

        r_mean = float(np.mean(valid_w)) if len(valid_w) > 0 else val
        r_std = float(np.std(valid_w)) if len(valid_w) > 1 else 0.0
        delta = float(val - val_arr[i - 1]) if i > 0 and not np.isnan(val_arr[i - 1]) else 0.0
        deficit = max(0.0, exp_p - val) / max(10.0, exp_p) if not np.isnan(val) else 0.0
        loading = float(val / max(1.0, rated_kw)) if not np.isnan(val) else 0.0

        if 6.0 <= h <= 18.0:
            diurnal = math.sin(math.pi * (h - 6.0) / 12.0)
        else:
            diurnal = 0.0

        X[i, 0] = val if not np.isnan(val) else 0.0
        X[i, 1] = r_mean
        X[i, 2] = r_std
        X[i, 3] = delta
        X[i, 4] = deficit
        X[i, 5] = loading
        X[i, 6] = diurnal

    # Valid mask for training per asset
    valid_mask = ~np.isnan(val_arr)
    if is_power_channel:
        # For solar power, filter out nighttime zero periods so model focuses on operational behavior
        valid_mask = valid_mask & ((val_arr > 10.0) | (expected_baselines > rated_kw * 0.10))

    return X, valid_mask, expected_baselines, feature_names


@register_detector(
    "d4_isolation_forest",
    description="D4: Isolation Forest Machine Learning Anomaly Detector (Per-Asset Multi-Feature)",
)
@register_detector("d4", description="D4 Machine Learning Isolation Forest Detector")
class D4IsolationForestDetector(BaseDetector):
    """Unsupervised Isolation Forest anomaly detector trained per individual asset.

    Features:
    - Custom model trained per asset using rolling window feature engineering
      (value, moving mean, moving volatility, ramp delta, deficit ratio, loading, diurnal cycle).
    - Unsupervised outlier isolation via scikit-learn IsolationForest (with fallback).
    - Persistence verification: suppresses brief 1-2 interval telemetry glitches,
      confirming anomalies only when deviations persist across consecutive evaluation windows.
    - Automated severity and energy loss quantification.
    """

    name = "d4_isolation_forest"
    description = "D4: Isolation Forest Machine Learning Anomaly Detector"

    def detect(
        self,
        observations: Sequence[Tuple[datetime, float]],
        parameters: Dict[str, Any],
        context: DetectorContext,
    ) -> List[DetectedAnomaly]:
        if not observations or len(observations) < 6:
            return []

        contamination = float(parameters.get("contamination", 0.05))
        n_estimators = int(parameters.get("n_estimators", 50))
        window_size = int(parameters.get("window_size", 4))
        default_min_p = 2 if self.name == "isolation_forest" else 3
        min_persistence = int(parameters.get("min_persistence", parameters.get("min_consecutive", default_min_p)))
        random_state = int(parameters.get("random_state", 42))
        cadence_seconds = context.cadence_seconds
        rated_kw = float(context.rated_kw if context.rated_kw is not None else 1000.0)

        ts_list = [obs[0] for obs in observations]
        val_arr = np.array([float(obs[1]) for obs in observations], dtype=float)
        n = len(observations)

        # 1. Per-Asset Feature Extraction across rolling windows
        X, valid_mask, expected_baselines, feature_names = extract_per_asset_telemetry_features(
            observations=observations,
            context=context,
            window_size=window_size,
        )

        valid_indices = np.where(valid_mask)[0]
        if len(valid_indices) < 6:
            return []

        X_valid = X[valid_indices]

        # Standardize features per asset
        feat_mean = np.mean(X_valid, axis=0)
        feat_std = np.std(X_valid, axis=0)
        feat_std[feat_std < 1e-6] = 1.0
        Z_valid = (X_valid - feat_mean) / feat_std

        # 2. Fit Isolation Forest per individual asset
        scores_valid = np.zeros(len(valid_indices), dtype=float)
        dec_func_valid = np.zeros(len(valid_indices), dtype=float)
        preds_valid = np.ones(len(valid_indices), dtype=int)

        if HAS_SKLEARN and SklearnIsolationForest is not None:
            model = SklearnIsolationForest(
                n_estimators=n_estimators,
                contamination=contamination,
                max_samples=min(len(valid_indices), 128),
                random_state=random_state,
            )
            model.fit(Z_valid)
            dec_func_valid = model.decision_function(Z_valid)
            preds_valid = model.predict(Z_valid)  # -1 for anomaly, 1 for inlier

            # Normalization of anomaly score to [0.0, 1.0]
            scores_valid = np.clip(0.5 - (dec_func_valid * 2.0), 0.05, 1.0)
        else:
            # Fallback pure Python isolation trees
            rng = np.random.RandomState(random_state)
            trees: List[_PureIsolationTree] = []
            n_sub = min(len(valid_indices), 64)
            for _ in range(n_estimators):
                sub_idx = rng.choice(len(valid_indices), size=n_sub, replace=False)
                trees.append(_PureIsolationTree(Z_valid[sub_idx], current_depth=0, max_depth=8))

            c_n = 2.0 * (math.log(max(2, n_sub - 1)) + 0.5772156649) - (2.0 * (n_sub - 1) / n_sub)
            for j in range(len(valid_indices)):
                avg_path = sum(t.path_length(Z_valid[j]) for t in trees) / n_estimators
                scores_valid[j] = 2.0 ** (-avg_path / max(0.1, c_n))

        threshold_pct = float(parameters.get("threshold_pct", 0.18))
        ramp_threshold = float(parameters.get("ramp_threshold", max(50.0, rated_kw * 0.15)))

        candidate_global_indices = []
        for j in range(len(valid_indices)):
            g_idx = valid_indices[j]
            exp_v = expected_baselines[g_idx]
            act_v = val_arr[g_idx]
            deficit_pct = max(0.0, exp_v - act_v) / max(10.0, exp_v)
            is_oscillating = abs(X[g_idx, 3]) >= ramp_threshold
            is_deviation = (deficit_pct >= threshold_pct) or is_oscillating
            if is_deviation and (scores_valid[j] >= 0.45 or dec_func_valid[j] <= 0.08 or preds_valid[j] == -1):
                candidate_global_indices.append(g_idx)
        if not candidate_global_indices:
            return []

        # 3. Group contiguous candidate points
        grouped_spans: List[List[int]] = []
        current_span = [candidate_global_indices[0]]

        for idx in candidate_global_indices[1:]:
            prev_idx = current_span[-1]
            dt = (ts_list[idx] - ts_list[prev_idx]).total_seconds()
            if dt <= cadence_seconds * 2:
                current_span.append(idx)
            else:
                grouped_spans.append(current_span)
                current_span = [idx]
        grouped_spans.append(current_span)

        # 4. Persistence Verification: Filter out brief transient telemetry glitches!
        confirmed_spans: List[List[int]] = []
        transient_glitches_count = 0

        for span in grouped_spans:
            if len(span) < min_persistence:
                # Transient telemetry glitch / sensor bounce filtered
                transient_glitches_count += len(span)
            else:
                confirmed_spans.append(span)

        if not confirmed_spans:
            return []

        # Map scores to full array
        full_scores = np.zeros(n, dtype=float)
        for j, g_idx in enumerate(valid_indices):
            full_scores[g_idx] = scores_valid[j]

        anomalies: List[DetectedAnomaly] = []
        asset_label = context.asset_name or (str(context.asset_id)[:8] if context.asset_id else "Inverter")

        for span in confirmed_spans:
            start_ts = ts_list[span[0]]
            end_ts = ts_list[span[-1]]
            span_vals = val_arr[span]
            span_exp = expected_baselines[span]
            span_scores = full_scores[span]

            dur_mins = max(1, int((len(span) * cadence_seconds) / 60))
            hours = dur_mins / 60.0

            avg_actual = float(np.mean(span_vals))
            avg_expected = float(np.mean(span_exp))
            if avg_expected <= 0:
                avg_expected = float(np.median(val_arr[valid_mask]))

            loss_kw = max(0.0, avg_expected - avg_actual)
            loss_kwh = loss_kw * hours
            max_score = float(np.max(span_scores))

            # Root-cause diagnostic heuristic
            span_X = X[span]
            avg_std_in_span = float(np.mean(span_X[:, 2]))  # feature 2 is rolling std
            overall_std = float(np.mean(X[valid_indices, 2]))

            if avg_expected > 0 and (avg_expected - avg_actual) / avg_expected >= 0.20:
                root_cause = "multivariable_behavioral_derating"
            elif avg_std_in_span > 2.0 * overall_std and avg_std_in_span > 20.0:
                root_cause = "erratic_sensor_noise_or_inverter_hunting"
            elif any(abs(span_X[k, 3]) > rated_kw * 0.35 for k in range(len(span))):
                root_cause = "abrupt_telemetry_step_shift"
            else:
                root_cause = "unsupervised_isolation_outlier"

            summary = (
                f"Isolation Forest multi-variable anomaly on {asset_label} ({context.canonical_key}): "
                f"anomaly score {max_score:.2f} across {dur_mins} mins "
                f"[verified persistence: {len(span)} intervals, cause: {root_cause.replace('_', ' ')}]."
            )

            anomalies.append(
                DetectedAnomaly(
                    start_time=start_ts,
                    end_time=end_ts,
                    score=round(max_score, 4),
                    anomaly_type=self.name,
                    metric_name=context.canonical_key,
                    summary=summary,
                    actual_value=avg_actual,
                    expected_value=avg_expected,
                    delta=avg_actual - avg_expected,
                    loss_kw=loss_kw,
                    loss_kwh=loss_kwh,
                    details={
                        "model": "sklearn_isolation_forest" if HAS_SKLEARN else "pure_isolation_tree",
                        "per_asset_custom_fit": True,
                        "asset_name": asset_label,
                        "features_used": feature_names,
                        "window_size": window_size,
                        "contamination": contamination,
                        "min_persistence_intervals": min_persistence,
                        "persistence_verified": True,
                        "transient_glitches_filtered": transient_glitches_count,
                        "root_cause_indicator": root_cause,
                        "duration_minutes": dur_mins,
                        "point_count": len(span),
                    },
                )
            )

        return anomalies


@register_detector("isolation_forest", description="Tree-Based Isolation Forest Detector")
class IsolationForestDetector(D4IsolationForestDetector):
    """Backwards-compatible alias for D4IsolationForestDetector."""

    name = "isolation_forest"
    description = "Tree-Based Isolation Forest Detector"

    name = "isolation_forest"


# =====================================================================
# Extensible Solar Domain Detectors: Trip & Flatline
# =====================================================================
@register_detector("trip", description="Midday Solar Inverter Ramp/Trip Outage Detector")
class TripDetector(BaseDetector):
    """Detects abrupt midday drops to 0.0 kW while sunshine/irradiance is present."""

    name = "trip"
    description = "Midday Solar Inverter Trip Detector"

    def detect(
        self,
        observations: Sequence[Tuple[datetime, float]],
        parameters: Dict[str, Any],
        context: DetectorContext,
    ) -> List[DetectedAnomaly]:
        if not observations or len(observations) < 2:
            return []

        min_midday_hour = int(parameters.get("start_hour", 8))
        max_midday_hour = int(parameters.get("end_hour", 17))
        cadence_seconds = context.cadence_seconds
        rated_kw = float(context.rated_kw) if context.rated_kw is not None else 1000.0

        ts_list = [obs[0] for obs in observations]
        val_arr = np.array([float(obs[1]) for obs in observations], dtype=float)

        trip_indices: List[int] = []
        for i, (ts, val) in enumerate(observations):
            if min_midday_hour <= ts.hour <= max_midday_hour:
                is_sunlight = True
                if context.irradiance_reference and ts in context.irradiance_reference:
                    is_sunlight = context.irradiance_reference[ts] > 100.0

                if is_sunlight and val <= 0.1:
                    trip_indices.append(i)

        if not trip_indices:
            return []

        # Group contiguous trip intervals
        grouped_spans: List[List[int]] = []
        current_span = [trip_indices[0]]

        for idx in trip_indices[1:]:
            prev_idx = current_span[-1]
            dt = (ts_list[idx] - ts_list[prev_idx]).total_seconds()
            if dt <= cadence_seconds * 2:
                current_span.append(idx)
            else:
                grouped_spans.append(current_span)
                current_span = [idx]
        grouped_spans.append(current_span)

        anomalies: List[DetectedAnomaly] = []
        for span in grouped_spans:
            start_ts = ts_list[span[0]]
            end_ts = ts_list[span[-1]]
            duration_minutes = int((len(span) * cadence_seconds) / 60)
            loss_kw = rated_kw * 0.80  # Estimated generation expected during trip
            hours = duration_minutes / 60.0
            loss_kwh = loss_kw * hours

            asset_label = context.asset_name or (str(context.asset_id)[:8] if context.asset_id else "Asset")
            summary = (
                f"CRITICAL Inverter Trip on {asset_label}: output collapsed to 0 kW "
                f"for {duration_minutes} mins during daylight (loss ~{loss_kwh:.1f} kWh)."
            )

            anomalies.append(
                DetectedAnomaly(
                    start_time=start_ts,
                    end_time=end_ts,
                    score=0.98,
                    severity="critical",
                    anomaly_type="trip",
                    metric_name=context.canonical_key,
                    summary=summary,
                    actual_value=0.0,
                    expected_value=loss_kw,
                    delta=-loss_kw,
                    loss_kw=loss_kw,
                    loss_kwh=loss_kwh,
                    details={
                        "duration_minutes": duration_minutes,
                        "point_count": len(span),
                        "rated_capacity_kw": rated_kw,
                    },
                )
            )

        return anomalies


@register_detector("flatline", description="Stuck Frozen Sensor Flatline Detector")
class FlatlineDetector(BaseDetector):
    """Detects repeated identical non-zero values across consecutive intervals."""

    name = "flatline"
    description = "Stuck Sensor Flatline Detector"

    def detect(
        self,
        observations: Sequence[Tuple[datetime, float]],
        parameters: Dict[str, Any],
        context: DetectorContext,
    ) -> List[DetectedAnomaly]:
        if not observations or len(observations) < 4:
            return []

        min_consecutive = int(parameters.get("min_consecutive", 4))
        tolerance = float(parameters.get("tolerance", 1e-4))
        cadence_seconds = context.cadence_seconds

        ts_list = [obs[0] for obs in observations]
        val_arr = np.array([float(obs[1]) for obs in observations], dtype=float)

        anomalies: List[DetectedAnomaly] = []
        run_indices: List[int] = [0]

        for i in range(1, len(val_arr)):
            prev_val = val_arr[run_indices[-1]]
            curr_val = val_arr[i]

            # Check if identical non-zero value
            if curr_val > 0.0 and abs(curr_val - prev_val) <= tolerance:
                run_indices.append(i)
            else:
                if len(run_indices) >= min_consecutive:
                    start_ts = ts_list[run_indices[0]]
                    end_ts = ts_list[run_indices[-1]]
                    frozen_val = float(val_arr[run_indices[0]])
                    dur_mins = int((len(run_indices) * cadence_seconds) / 60)

                    asset_label = context.asset_name or (str(context.asset_id)[:8] if context.asset_id else "Asset")
                    summary = (
                        f"Sensor flatline detected on {asset_label} ({context.canonical_key}): "
                        f"repeating identical non-zero value {frozen_val:.2f} across {dur_mins} minutes."
                    )

                    anomalies.append(
                        DetectedAnomaly(
                            start_time=start_ts,
                            end_time=end_ts,
                            score=0.75,
                            severity="medium",
                            anomaly_type="flatline",
                            metric_name=context.canonical_key,
                            summary=summary,
                            actual_value=frozen_val,
                            expected_value=None,
                            delta=0.0,
                            loss_kw=0.0,
                            loss_kwh=0.0,
                            details={
                                "frozen_value": frozen_val,
                                "duration_minutes": dur_mins,
                                "consecutive_intervals": len(run_indices),
                            },
                        )
                    )
                run_indices = [i]

        # Check trailing run
        if len(run_indices) >= min_consecutive:
            start_ts = ts_list[run_indices[0]]
            end_ts = ts_list[run_indices[-1]]
            frozen_val = float(val_arr[run_indices[0]])
            dur_mins = int((len(run_indices) * cadence_seconds) / 60)

            asset_label = context.asset_name or (str(context.asset_id)[:8] if context.asset_id else "Asset")
            anomalies.append(
                DetectedAnomaly(
                    start_time=start_ts,
                    end_time=end_ts,
                    score=0.75,
                    severity="medium",
                    anomaly_type="flatline",
                    metric_name=context.canonical_key,
                    summary=f"Sensor flatline on {asset_label}: {frozen_val:.2f} frozen for {dur_mins} mins.",
                    actual_value=frozen_val,
                    expected_value=None,
                    delta=0.0,
                    loss_kw=0.0,
                    loss_kwh=0.0,
                    details={
                        "frozen_value": frozen_val,
                        "duration_minutes": dur_mins,
                        "consecutive_intervals": len(run_indices),
                    },
                )
            )

        return anomalies


@register_detector("clipping", description="Inverter Power Ceiling / Inverter Saturation Clipping Detector")
class ClippingDetector(BaseDetector):
    """Detects inverter output clipping where generation is capped at a ceiling during peak daylight hours."""

    name = "clipping"
    description = "Inverter Power Ceiling Clipping Detector"

    def detect(
        self,
        observations: Sequence[Tuple[datetime, float]],
        parameters: Dict[str, Any],
        context: DetectorContext,
    ) -> List[DetectedAnomaly]:
        if not observations or len(observations) < 4:
            return []

        min_consecutive = int(parameters.get("min_consecutive", 3))
        tolerance = float(parameters.get("tolerance", 0.5))
        rated_kw = float(context.rated_kw) if context.rated_kw is not None else 1000.0
        min_clip_power = float(parameters.get("min_clip_power", rated_kw * 0.60))
        cadence_seconds = context.cadence_seconds

        ts_list = [obs[0] for obs in observations]
        val_arr = np.array([float(obs[1]) for obs in observations], dtype=float)

        anomalies: List[DetectedAnomaly] = []
        run_indices: List[int] = [0]

        def process_run(indices: List[int]) -> Optional[DetectedAnomaly]:
            if len(indices) < min_consecutive:
                return None
            val = float(val_arr[indices[0]])
            if val < min_clip_power:
                return None
            start_ts = ts_list[indices[0]]
            end_ts = ts_list[indices[-1]]
            if not (9 <= start_ts.hour <= 16):
                return None
            dur_mins = int((len(indices) * cadence_seconds) / 60)
            hours = dur_mins / 60.0
            est_unclipped = min(rated_kw, val * 1.15)
            loss_kw = max(0.0, est_unclipped - val)
            loss_kwh = loss_kw * hours

            asset_label = context.asset_name or (str(context.asset_id)[:8] if context.asset_id else "Inverter")
            summary = (
                f"Power clipping ceiling detected on {asset_label} ({context.canonical_key}): "
                f"output clamped at {val:.1f} kW for {dur_mins} mins during peak sunlight."
            )
            return DetectedAnomaly(
                start_time=start_ts,
                end_time=end_ts,
                score=0.82,
                severity="medium" if loss_kwh < 200 else "high",
                anomaly_type="clipping",
                metric_name=context.canonical_key,
                summary=summary,
                actual_value=val,
                expected_value=est_unclipped,
                delta=val - est_unclipped,
                loss_kw=loss_kw,
                loss_kwh=loss_kwh,
                details={
                    "clip_ceiling_kw": val,
                    "duration_minutes": dur_mins,
                    "consecutive_intervals": len(indices),
                },
            )

        for i in range(1, len(val_arr)):
            prev_val = val_arr[run_indices[-1]]
            curr_val = val_arr[i]
            dt = (ts_list[i] - ts_list[run_indices[-1]]).total_seconds()

            if abs(curr_val - prev_val) <= tolerance and curr_val >= min_clip_power and dt <= cadence_seconds * 2:
                run_indices.append(i)
            else:
                anom = process_run(run_indices)
                if anom:
                    anomalies.append(anom)
                run_indices = [i]

        anom = process_run(run_indices)
        if anom:
            anomalies.append(anom)

        return anomalies


@register_detector("soiling", description="Solar Array Soiling & Progressive Surface Degradation Detector")
class SoilingDetector(BaseDetector):
    """Detects multi-day progressive generation loss / soiling degradation."""

    name = "soiling"
    description = "Solar Array Soiling Degradation Detector"

    def detect(
        self,
        observations: Sequence[Tuple[datetime, float]],
        parameters: Dict[str, Any],
        context: DetectorContext,
    ) -> List[DetectedAnomaly]:
        if not observations or len(observations) < 16:
            return []

        cadence_seconds = context.cadence_seconds
        rated_kw = float(context.rated_kw) if context.rated_kw is not None else 1000.0
        degradation_threshold = float(parameters.get("degradation_threshold", 0.15))

        daily_daytime: Dict[str, List[Tuple[datetime, float]]] = {}
        for ts, val in observations:
            if 10 <= ts.hour <= 15:
                date_key = ts.strftime("%Y-%m-%d")
                daily_daytime.setdefault(date_key, []).append((ts, val))

        if len(daily_daytime) < 3:
            return []

        daily_avgs = {d: float(np.mean([v for _, v in pts])) for d, pts in daily_daytime.items() if len(pts) >= 4}
        if len(daily_avgs) < 3:
            return []

        baseline_kw = float(np.percentile(list(daily_avgs.values()), 80))
        if baseline_kw < 100.0:
            return []

        soiled_days = []
        for d, avg_p in sorted(daily_avgs.items()):
            deficit = (baseline_kw - avg_p) / baseline_kw
            if deficit >= degradation_threshold:
                soiled_days.append((d, avg_p, deficit))

        if len(soiled_days) < 3:
            return []

        start_date = soiled_days[0][0]
        end_date = soiled_days[-1][0]
        first_ts = daily_daytime[start_date][0][0]
        last_ts = daily_daytime[end_date][-1][0]

        avg_deficit_pct = float(np.mean([d[2] for d in soiled_days])) * 100.0
        avg_loss_kw = baseline_kw * (avg_deficit_pct / 100.0)
        est_loss_kwh = avg_loss_kw * 5.0 * len(soiled_days)

        asset_label = context.asset_name or (str(context.asset_id)[:8] if context.asset_id else "Array")
        summary = (
            f"Progressive soiling/degradation detected on {asset_label} ({context.canonical_key}): "
            f"average peak generation depressed by {avg_deficit_pct:.1f}% across {len(soiled_days)} days."
        )

        return [
            DetectedAnomaly(
                start_time=first_ts,
                end_time=last_ts,
                score=min(0.95, 0.65 + (avg_deficit_pct / 100.0) * 0.5),
                severity="high" if avg_deficit_pct >= 25.0 else "medium",
                anomaly_type="soiling",
                metric_name=context.canonical_key,
                summary=summary,
                actual_value=baseline_kw - avg_loss_kw,
                expected_value=baseline_kw,
                delta=-avg_loss_kw,
                loss_kw=avg_loss_kw,
                loss_kwh=est_loss_kwh,
                details={
                    "soiled_days_count": len(soiled_days),
                    "baseline_peak_kw": round(baseline_kw, 2),
                    "average_degradation_pct": round(avg_deficit_pct, 1),
                },
            )
        ]

