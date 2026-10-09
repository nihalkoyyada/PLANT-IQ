"""Tests for CARE Benchmark Harness & Evaluation Engine (Task S4-AI-05).

Validates:
1. ClassificationMetrics calculation (Precision, Recall, F1, Specificity, FAR, Accuracy).
2. LeadTimeMetrics calculation (lead times, latencies, promptness notes).
3. Ground truth parsing and catalog ingestion.
4. Timestamp parsing across Day-First and ISO formats.
5. End-to-end benchmark evaluation of anomaly detectors against test datasets.
6. Markdown artifact compilation and JSON serialization.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import List, Tuple
from uuid import uuid4

import pytest

from app.ai.care_benchmark import (
    CAREBenchmarkEngine,
    CAREBenchmarkSuite,
    ClassificationMetrics,
    DetectorBenchmarkResult,
    GroundTruthEvent,
    LeadTimeMetrics,
)
from app.ai.detector_registry import (
    BaseDetector,
    DetectedAnomaly,
    DetectorContext,
    DetectorRegistry,
    register_detector,
)

_repo_root = Path(__file__).resolve().parents[3]
DATASETS_DIR = _repo_root / "Datasets"
DEMO_CSV = DATASETS_DIR / "Surya-A-demo.csv"
GROUND_TRUTH_JSON = DATASETS_DIR / "ground_truth_anomalies.json"


# ---------------------------------------------------------------------------
# Unit Tests: Metrics Calculations
# ---------------------------------------------------------------------------

def test_classification_metrics_standard_confusion_matrix() -> None:
    """Verify precision, recall, F1, specificity, FAR, and accuracy calculations."""
    metrics = ClassificationMetrics.compute(tp=80, fp=20, fn=10, tn=890)

    # Precision: 80 / (80 + 20) = 0.80
    assert metrics.precision == 0.80
    # Recall: 80 / (80 + 10) = 0.8889
    assert metrics.recall == 0.8889
    # F1 Score: 2 * (0.8 * 0.888889) / (0.8 + 0.888889) = 0.8421
    assert metrics.f1_score == 0.8421
    # Specificity: 890 / (890 + 20) = 0.9780
    assert metrics.specificity == 0.9780
    # False Alarm Rate: 20 / (20 + 890) = 0.0220
    assert metrics.false_alarm_rate == 0.0220
    # Accuracy: (80 + 890) / 1000 = 0.9700
    assert metrics.accuracy == 0.9700


def test_classification_metrics_edge_cases() -> None:
    """Verify zero-division handling for perfect and empty metric cases."""
    # Zero positives (perfect negative discrimination with zero false alarms)
    zero_m = ClassificationMetrics.compute(tp=0, fp=0, fn=0, tn=100)
    assert zero_m.precision == 1.0
    assert zero_m.recall == 1.0
    assert zero_m.f1_score == 1.0
    assert zero_m.false_alarm_rate == 0.0

    # Total miss
    miss_m = ClassificationMetrics.compute(tp=0, fp=5, fn=5, tn=90)
    assert miss_m.precision == 0.0
    assert miss_m.recall == 0.0
    assert miss_m.f1_score == 0.0


def test_lead_time_metrics_aggregates() -> None:
    """Verify calculation of mean, median, max, min lead times and latencies."""
    lead_times = {
        "event-01": 15.0,
        "event-02": 45.0,
        "event-03": 90.0,
    }
    latencies = {
        "event-01": -15.0,  # 15 min early warning
        "event-02": 0.0,    # Immediate onset trigger
        "event-03": 30.0,   # 30 min latency into event
    }
    notes = {
        "event-01": "Early predictive warning (15 min before onset)",
        "event-02": "Immediate onset trigger",
        "event-03": "Standard detection (+30 min latency)",
    }

    lt = LeadTimeMetrics.compute(lead_times=lead_times, latencies=latencies, notes=notes)

    assert lt.mean_lead_time_minutes == 50.0  # (15 + 45 + 90) / 3
    assert lt.median_lead_time_minutes == 45.0
    assert lt.min_lead_time_minutes == 15.0
    assert lt.max_lead_time_minutes == 90.0
    assert "event-01" in lt.event_lead_times
    assert lt.promptness_notes["event-01"] == notes["event-01"]


def test_lead_time_metrics_empty() -> None:
    """Verify empty lead time handling returns zeroed statistics."""
    empty_lt = LeadTimeMetrics.compute(lead_times={})
    assert empty_lt.mean_lead_time_minutes == 0.0
    assert empty_lt.median_lead_time_minutes == 0.0
    assert empty_lt.event_lead_times == {}


# ---------------------------------------------------------------------------
# Unit Tests: Synthetic Engine & Parsing
# ---------------------------------------------------------------------------

def test_ground_truth_event_properties() -> None:
    """Verify GroundTruthEvent duration and property calculations."""
    start = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)
    ev = GroundTruthEvent(
        event_id="test-001",
        anomaly_type="trip",
        device_id="INV-01",
        start_time=start,
        end_time=end,
        affected_row_count=18,
    )
    assert ev.duration_hours == 4.5
    assert ev.duration_minutes == 270.0


def test_timestamp_parser_formats(tmp_path: Path) -> None:
    """Verify timestamp parsing across Day-First, ISO, and standard solar formats."""
    dummy_csv = tmp_path / "dummy.csv"
    dummy_csv.write_text("SOURCE_KEY,DATE_TIME,AC_POWER\nINV-01,15-05-2020 12:00,500.0\n")
    dummy_gt = tmp_path / "dummy_gt.json"
    dummy_gt.write_text(json.dumps({"events": []}))

    engine = CAREBenchmarkEngine(dataset_path=dummy_csv, ground_truth_path=dummy_gt)

    # Day-First
    dt1 = engine._parse_timestamp("15-05-2020 14:30")
    assert dt1.day == 15 and dt1.month == 5 and dt1.hour == 14

    # ISO
    dt2 = engine._parse_timestamp("2020-05-15T14:30:00Z")
    assert dt2.day == 15 and dt2.month == 5 and dt2.hour == 14

    # Year-Month-Day with space
    dt3 = engine._parse_timestamp("2020-05-15 14:30:00")
    assert dt3.day == 15 and dt3.month == 5 and dt3.hour == 14


# ---------------------------------------------------------------------------
# Integration Tests: End-to-End Benchmark Execution on Real Datasets
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not DEMO_CSV.exists() or not GROUND_TRUTH_JSON.exists(), reason="Reference datasets not found")
def test_care_benchmark_full_suite_execution(tmp_path: Path) -> None:
    """Run full CARE benchmark on Surya-A-demo dataset and verify all deliverables."""
    engine = CAREBenchmarkEngine(
        dataset_path=DEMO_CSV,
        ground_truth_path=GROUND_TRUTH_JSON,
        tariff_inr=4.20,
        tolerance_minutes=60.0,
    )
    engine.load_data()

    assert len(engine.ground_truth_events) == 4
    assert len(engine.devices) == 22

    # Target the 4 faulted inverters + 2 clean control inverters for fast test execution
    faulted = [ev.device_id for ev in engine.ground_truth_events]
    clean = [d for d in engine.devices if d not in faulted][:2]
    target_inverters = faulted + clean

    # Evaluate suite across D1-D4 and specialized rules
    suite = engine.run_full_benchmark(
        detector_keys=["d1_statistical", "d2_pr_deviation", "trip", "flatline", "clipping"],
        target_devices=target_inverters,
        include_ensemble=True,
    )

    assert isinstance(suite, CAREBenchmarkSuite)
    assert suite.run_id.startswith("CARE-")
    assert len(suite.results_by_detector) >= 5
    assert suite.ensemble_result is not None

    # Check that Trip detector flagged trip-001
    trip_res = suite.results_by_detector.get("trip")
    assert trip_res is not None
    assert "trip-001" in trip_res.events_detected
    assert trip_res.lead_time_metrics.mean_lead_time_minutes > 0.0

    # Check that Flatline detector flagged flat-001
    flat_res = suite.results_by_detector.get("flatline")
    assert flat_res is not None
    assert "flat-001" in flat_res.events_detected

    # Check that Multi-Model Ensemble catches all ground truth events
    ens_res = suite.ensemble_result
    assert ens_res.event_metrics.recall >= 0.75  # Caught at least 3 of 4 events
    assert ens_res.total_energy_loss_kwh > 0.0
    assert ens_res.total_financial_loss_inr > 0.0


@pytest.mark.skipif(not DEMO_CSV.exists() or not GROUND_TRUTH_JSON.exists(), reason="Reference datasets not found")
def test_care_benchmark_markdown_and_json_report_generation(tmp_path: Path) -> None:
    """Verify that Markdown artifact and JSON summaries are programmatically compiled."""
    engine = CAREBenchmarkEngine(
        dataset_path=DEMO_CSV,
        ground_truth_path=GROUND_TRUTH_JSON,
        tariff_inr=4.20,
    )
    engine.load_data()

    # Fast evaluation on the 4 faulted inverters
    faulted_inverters = [ev.device_id for ev in engine.ground_truth_events]
    suite = engine.run_full_benchmark(
        detector_keys=["d1_statistical", "trip", "flatline"],
        target_devices=faulted_inverters,
        include_ensemble=True,
    )

    # 1. Generate Markdown Report
    md_content = suite.generate_markdown_report()
    assert "# PlantIQ: CARE Benchmark & Detector Validation Report" in md_content
    assert "## 1. Executive Summary" in md_content
    assert "## 2. Benchmark Dataset & Ground Truth Fault Catalog" in md_content
    assert "## 3. Algorithm Performance Comparison Matrix" in md_content
    assert "## 4. Lead-Time & Early Warning Analysis" in md_content
    assert "## 5. Fault-by-Fault Detection Breakdown" in md_content
    assert "## 6. Financial Loss & Quantified Operational Impact" in md_content
    assert "## 7. Strategic Recommendations for Solar Asset Operators" in md_content

    # Check that report contains fault identifiers
    assert "soil-001" in md_content
    assert "trip-001" in md_content
    assert "clip-001" in md_content
    assert "flat-001" in md_content

    # Save to disk
    report_file = tmp_path / "test_care_report.md"
    saved_path = suite.save_markdown_report(report_file)
    assert saved_path.exists()
    assert saved_path.read_text(encoding="utf-8") == md_content

    # 2. Generate JSON Summary
    json_file = tmp_path / "test_care_report.json"
    suite.save_json(json_file)
    assert json_file.exists()

    with open(json_file, "r", encoding="utf-8") as f:
        json_data = json.load(f)
    assert json_data["run_id"] == suite.run_id
    assert "results_by_detector" in json_data
    assert "ensemble_result" in json_data
