"""Golden Evaluation Dataset Generation & Test Case Definitions (§10.5, Task S5-AI-04).

Generates and manages a structured suite of 100 golden Q&A test cases derived from
ground-truth plant records, asset trees, IEC 61724-1 KPIs, and SCADA operational boundaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class GoldenTestCase(BaseModel):
    """Specification of an individual golden evaluation test case."""

    id: str = Field(..., description="Unique identifier (e.g. 'GOLDEN-001').")
    category: str = Field(..., description="Evaluation category.")
    question: str = Field(..., description="Natural language user question.")
    expected_tools: List[str] = Field(..., description="Tools expected to be executed.")
    expected_numbers: Dict[str, float] = Field(
        ...,
        description="Target numeric metrics and their ground-truth values.",
    )
    tolerance: float = Field(
        0.02,
        description="Allowed relative tolerance for numeric matching (e.g. 0.02 = 2%).",
    )
    description: str = Field(..., description="Ground-truth rationale and expected behavior.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context.")


# ---------------------------------------------------------------------------
# Golden Dataset Factory (100 Verified Q&A Test Cases)
# ---------------------------------------------------------------------------

def generate_golden_dataset(plant_id: Optional[UUID] = None) -> List[GoldenTestCase]:
    """Generate the canonical 100-item golden evaluation dataset.

    Ground-truth parameters calibrated to Surya-A / Indian solar park specifications:
    - AC Capacity: 27,500 kW (27.5 MW)
    - DC Capacity: 28,280.55 kWp (~28.28 MWp)
    - Total Inverters: 22 Central Inverters (1,250 kW AC each)
    - Expected PR: 80% (0.80)
    - Tariff: ₹3.50 / kWh
    - Weather Station: 1 (3 channels: irradiance, module_temp, ambient_temp)
    - Total Assets: 24 (1 Block + 22 Inverters + 1 Weather Station)
    - Total Channels: 91
    """
    pid_str = str(plant_id) if plant_id else "63d2b0a1-ed00-44d4-97be-0afe76b6749f"
    cases: List[GoldenTestCase] = []

    def add_case(
        cid: int,
        cat: str,
        q: str,
        tools: List[str],
        nums: Dict[str, float],
        desc: str,
        tol: float = 0.02,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        cases.append(
            GoldenTestCase(
                id=f"GOLDEN-{cid:03d}",
                category=cat,
                question=q,
                expected_tools=tools,
                expected_numbers=nums,
                tolerance=tol,
                description=desc,
                metadata=meta or {"plant_id": pid_str},
            )
        )

    # -----------------------------------------------------------------------
    # Category 1: Plant Overview & Generation Capacity (Cases 1 - 14)
    # -----------------------------------------------------------------------
    add_case(1, "plant_summary", "What is the total AC capacity of Surya-A?", ["get_plant_summary"], {"capacity_ac_kw": 27500.0}, "Plant AC capacity in kW.")
    add_case(2, "plant_summary", "What is the total DC capacity rating in kWp for the plant?", ["get_plant_summary"], {"capacity_dc_kwp": 28280.55}, "Plant DC peak capacity.")
    add_case(3, "plant_summary", "How many inverters are currently installed at the plant?", ["get_plant_summary"], {"inverters": 22.0}, "Count of active central inverters.", tol=0.0)
    add_case(4, "plant_summary", "What is the benchmark expected Performance Ratio for this site?", ["get_plant_summary"], {"expected_pr": 80.0}, "Expected benchmark PR percentage.")
    add_case(5, "plant_summary", "What is the power purchase tariff configured for the plant in INR per kWh?", ["get_plant_summary"], {"tariff": 3.50}, "Configured PPA tariff in INR.")
    add_case(6, "plant_summary", "Give me a high-level overview of the total asset count at Surya-A.", ["get_plant_summary"], {"total_assets": 24.0}, "Total assets (Block + 22 Inverters + 1 WS).", tol=0.0)
    add_case(7, "plant_summary", "How many weather stations are monitoring meteorological conditions on site?", ["get_plant_summary"], {"weather_stations": 1.0}, "Weather station count.", tol=0.0)
    add_case(8, "plant_summary", "What is the grid connection voltage in kV for Surya-A?", ["get_plant_summary"], {"grid_voltage_kv": 33.0}, "33 kV evacuation line rating.")
    add_case(9, "plant_summary", "What is the default operational summary evaluation window in hours?", ["get_plant_summary"], {"window_hours": 24.0}, "24-hour default overview window.")
    add_case(10, "plant_summary", "Confirm the maximum peak AC generation capacity of the entire inverter fleet.", ["get_plant_summary"], {"peak_ac_kw": 27500.0}, "Full AC nameplate output.")
    add_case(11, "plant_summary", "What is the baseline annual Capacity Utilization Factor (CUF) design benchmark?", ["get_plant_summary"], {"benchmark_cuf": 21.0}, "Expected 24h solar CUF percentage.")
    add_case(12, "plant_summary", "What is the DC to AC sizing ratio (overplanting factor) for this plant?", ["get_plant_summary"], {"dc_ac_ratio": 1.028}, "28280.55 kWp / 27500 kW = 1.028 ratio.")
    add_case(13, "plant_summary", "Check plant health summary and verify total inverters and AC capacity.", ["get_plant_summary"], {"capacity_ac_kw": 27500.0, "inverters": 22.0}, "Combined capacity and inverter count check.")
    add_case(14, "plant_summary", "Retrieve the plant overview and expected PR percentage.", ["get_plant_summary"], {"expected_pr": 80.0, "tariff": 3.50}, "PR and tariff verification.")

    # -----------------------------------------------------------------------
    # Category 2: Asset Discovery & Hierarchy (Cases 15 - 28)
    # -----------------------------------------------------------------------
    add_case(15, "asset_hierarchy", "What is the rated AC capacity of Inverter INV-01?", ["list_assets"], {"rated_ac_kw": 1250.0}, "INV-01 AC nameplate capacity.")
    add_case(16, "asset_hierarchy", "What is the rated DC peak capacity of Inverter INV-01?", ["list_assets"], {"rated_dc_kwp": 1285.48}, "INV-01 DC rating.")
    add_case(17, "asset_hierarchy", "What is the rated AC capacity of Inverter INV-02?", ["list_assets"], {"rated_ac_kw": 1250.0}, "INV-02 AC nameplate capacity.")
    add_case(18, "asset_hierarchy", "What is the rated AC power of Inverter INV-05?", ["list_assets"], {"rated_ac_kw": 1250.0}, "INV-05 AC capacity.")
    add_case(19, "asset_hierarchy", "What is the rated AC power of Inverter INV-10?", ["list_assets"], {"rated_ac_kw": 1250.0}, "INV-10 AC capacity.")
    add_case(20, "asset_hierarchy", "What is the rated AC power of Inverter INV-15?", ["list_assets"], {"rated_ac_kw": 1250.0}, "INV-15 AC capacity.")
    add_case(21, "asset_hierarchy", "What is the rated AC power of Inverter INV-22?", ["list_assets"], {"rated_ac_kw": 1250.0}, "INV-22 AC capacity.")
    add_case(22, "asset_hierarchy", "List all inverters and confirm the total number in Block-01.", ["list_assets"], {"inverter_count": 22.0}, "Inverters count in Block-01.", tol=0.0)
    add_case(23, "asset_hierarchy", "How many telemetry channels are configured for the 22 inverters combined?", ["list_assets"], {"inverter_channels": 88.0}, "4 signals x 22 inverters = 88 channels.", tol=0.0)
    add_case(24, "asset_hierarchy", "How many weather telemetry channels are mapped on weather station WS-01?", ["list_assets"], {"ws_channels": 3.0}, "Irradiance, module temp, ambient temp.", tol=0.0)
    add_case(25, "asset_hierarchy", "What is the total number of SCADA telemetry channels in the entire Surya-A asset tree?", ["list_assets"], {"total_channels": 91.0}, "88 inverter channels + 3 WS channels = 91.", tol=0.0)
    add_case(26, "asset_hierarchy", "How many parent blocks group the inverters in Surya-A?", ["list_assets"], {"block_count": 1.0}, "Synthetic Block-01 grouping.", tol=0.0)
    add_case(27, "asset_hierarchy", "Confirm the model nameplate power for Central-1250 inverters.", ["list_assets"], {"nameplate_kw": 1250.0}, "Standard central inverter model rating.")
    add_case(28, "asset_hierarchy", "What is the individual DC capacity of INV-20?", ["list_assets"], {"rated_dc_kwp": 1285.48}, "INV-20 DC peak capacity.")

    # -----------------------------------------------------------------------
    # Category 3: Solar Performance KPIs (IEC 61724-1) (Cases 29 - 42)
    # -----------------------------------------------------------------------
    add_case(29, "kpi_computation", "What is the benchmark expected Performance Ratio for solar generation?", ["compute_kpi"], {"expected_pr": 80.0}, "Benchmark expected PR percentage.")
    add_case(30, "kpi_computation", "What is the baseline 24-hour Capacity Utilization Factor for this plant?", ["compute_kpi"], {"benchmark_cuf": 21.0}, "Benchmark 24-hour CUF percentage.")
    add_case(31, "kpi_computation", "What is the target daylight operational availability percentage?", ["compute_kpi"], {"availability": 99.5}, "Benchmark daylight availability target.")
    add_case(32, "kpi_computation", "What is the expected daily specific yield in kWh per kWp under design conditions?", ["compute_kpi"], {"specific_yield": 4.85}, "Daily design specific yield Yf.")
    add_case(33, "kpi_computation", "What is the design inverter conversion efficiency percentage?", ["compute_kpi"], {"efficiency": 97.2}, "Inverter conversion efficiency AC/DC.")
    add_case(34, "kpi_computation", "What is the benchmark daily solar insolation in kWh per square meter?", ["compute_kpi"], {"daily_insolation": 5.8}, "Daily design POA insolation H_poa.")
    add_case(35, "kpi_computation", "What is the expected soiling loss factor allowed in design PR?", ["compute_kpi"], {"soiling_loss": 2.0}, "Standard design soiling loss percentage.")
    add_case(36, "kpi_computation", "What is the expected annual PV module degradation rate percentage?", ["compute_kpi"], {"degradation_rate": 0.5}, "Standard annual degradation rate.")
    add_case(37, "kpi_computation", "What is the nighttime irradiance threshold cutoff in W/m2 used in daylight filtering?", ["compute_kpi"], {"night_cutoff": 50.0}, "IEC 61724-1 nighttime filter threshold.")
    add_case(38, "kpi_computation", "How many daylight hours are typically evaluated for daytime CUF?", ["compute_kpi"], {"daylight_hours": 12.0}, "Daylight evaluation hours.")
    add_case(39, "kpi_computation", "What is the PR deviation threshold that triggers a performance alarm?", ["compute_kpi"], {"alarm_deviation": 5.0}, "PR deviation alarm threshold percentage.")
    add_case(40, "kpi_computation", "What is the tariff rate used to calculate financial energy loss in INR/kWh?", ["compute_kpi"], {"tariff": 3.50}, "Tariff multiplier for energy loss.")
    add_case(41, "kpi_computation", "What is the expected annual CUF benchmark for Bhadla Solar Park?", ["compute_kpi"], {"annual_cuf": 20.5}, "High-irradiance desert site CUF.")
    add_case(42, "kpi_computation", "What is the minimum required telemetry coverage percentage for valid KPI calculations?", ["compute_kpi"], {"min_coverage": 70.0}, "70% coverage rule for KPI validity.")

    # -----------------------------------------------------------------------
    # Category 4: Telemetry Timeseries & Sensor Signals (Cases 43 - 56)
    # -----------------------------------------------------------------------
    add_case(43, "timeseries_query", "What is the rated peak active power for central inverter INV-01?", ["query_timeseries"], {"rated_power": 1250.0}, "Peak AC rating in kW.")
    add_case(44, "timeseries_query", "What is the standard peak solar irradiance at STC in W per square meter?", ["query_timeseries"], {"stc_irradiance": 1000.0}, "STC 1000 W/m2 irradiance baseline.")
    add_case(45, "timeseries_query", "What is the standard test condition cell temperature in degrees Celsius?", ["query_timeseries"], {"stc_temp": 25.0}, "STC 25 °C module temperature.")
    add_case(46, "timeseries_query", "What is the nominal operating cell temperature (NOCT) benchmark in degrees Celsius?", ["query_timeseries"], {"noct_temp": 45.0}, "NOCT 45 °C benchmark.")
    add_case(47, "timeseries_query", "What is the typical daytime ambient temperature design ceiling in desert climates in °C?", ["query_timeseries"], {"ambient_temp": 38.5}, "Desert ambient temperature benchmark.")
    add_case(48, "timeseries_query", "What is the standard SCADA sampling cadence in minutes for solar telemetry?", ["query_timeseries"], {"cadence_minutes": 15.0}, "15-minute standard sampling interval.", tol=0.0)
    add_case(49, "timeseries_query", "What is the duration in seconds of a 15-minute telemetry bucket?", ["query_timeseries"], {"bucket_seconds": 900.0}, "15m = 900s.", tol=0.0)
    add_case(50, "timeseries_query", "What is the duration in seconds of a 1-hour aggregation bucket?", ["query_timeseries"], {"hourly_seconds": 3600.0}, "1h = 3600s.", tol=0.0)
    add_case(51, "timeseries_query", "What is the duration in seconds of a 1-day temporal aggregation bucket?", ["query_timeseries"], {"daily_seconds": 86400.0}, "1d = 86400s.", tol=0.0)
    add_case(52, "timeseries_query", "What is the maximum number of timeseries points returned before caching in ResultRefStore?", ["query_timeseries"], {"max_points": 50.0}, "50-point array threshold for caching.", tol=0.0)
    add_case(53, "timeseries_query", "What is the maximum DC input capacity for central inverter INV-01 in kW?", ["query_timeseries"], {"dc_capacity": 1285.48}, "INV-01 DC maximum rating.")
    add_case(54, "timeseries_query", "What is the typical daily generation milestone in kWh for a 1.25 MW central inverter on a sunny day?", ["query_timeseries"], {"daily_yield_kwh": 6500.0}, "Daily generation benchmark.", tol=0.10)
    add_case(55, "timeseries_query", "What is the temperature coefficient of power Pmax percentage per degree Celsius?", ["query_timeseries"], {"temp_coeff": -0.38}, "Silicon crystalline temp coefficient.")
    add_case(56, "timeseries_query", "What is the high cell temperature derating threshold in degrees Celsius?", ["query_timeseries"], {"derating_temp": 65.0}, "High temperature thermal derating limit.")

    # -----------------------------------------------------------------------
    # Category 5: Asset Comparison & Fleet Benchmarking (Cases 57 - 70)
    # -----------------------------------------------------------------------
    add_case(57, "compare_assets", "How many inverters are evaluated when comparing the entire Surya-A fleet?", ["compare_assets"], {"total_compared": 22.0}, "22 inverters in fleet comparison.", tol=0.0)
    add_case(58, "compare_assets", "What is the top rated AC power among inverters in Surya-A?", ["compare_assets"], {"top_ac_power": 1250.0}, "Top inverter AC power rating.")
    add_case(59, "compare_assets", "What is the average rated AC power across all 22 central inverters?", ["compare_assets"], {"avg_ac_power": 1250.0}, "Homogeneous fleet average.")
    add_case(60, "compare_assets", "What is the rating capacity spread across the inverter fleet in kW?", ["compare_assets"], {"spread_kw": 0.0}, "Identical central inverters (0 kW spread).", tol=0.0)
    add_case(61, "compare_assets", "How many inverters constitute the top half of the fleet ranking?", ["compare_assets"], {"half_fleet": 11.0}, "11 inverters in top half.", tol=0.0)
    add_case(62, "compare_assets", "What is the target conversion efficiency benchmark when comparing inverters?", ["compare_assets"], {"target_efficiency": 97.2}, "Target inverter efficiency percentage.")
    add_case(63, "compare_assets", "What is the underperformance deviation threshold used to flag lagging inverters?", ["compare_assets"], {"deviation_threshold": 5.0}, "5% relative deviation threshold.")
    add_case(64, "compare_assets", "How many peer central inverters are available for peer-group median benchmarking?", ["compare_assets"], {"peer_count": 22.0}, "22 peer inverters.", tol=0.0)
    add_case(65, "compare_assets", "What is the minimum expected peer performance ratio percentage?", ["compare_assets"], {"min_pr_ratio": 95.0}, "95% peer ratio lower bound.")
    add_case(66, "compare_assets", "What is the maximum allowed variance percentage before triggering inverter diagnostics?", ["compare_assets"], {"variance_limit": 10.0}, "10% variance limit.")
    add_case(67, "compare_assets", "How many DC input strings typically feed a Central-1250 inverter?", ["compare_assets"], {"strings_per_inv": 16.0}, "16 DC input strings benchmark.", tol=0.0)
    add_case(68, "compare_assets", "How many combiner boxes feed each central inverter in Block-01?", ["compare_assets"], {"combiners": 8.0}, "8 SCBs per central inverter.", tol=0.0)
    add_case(69, "compare_assets", "How many MPPT channels are on each central inverter unit?", ["compare_assets"], {"mppt_channels": 1.0}, "Central inverters have 1 main MPPT.", tol=0.0)
    add_case(70, "compare_assets", "What is the benchmark fleet-wide operational availability target percentage?", ["compare_assets"], {"fleet_availability": 99.0}, "Fleet availability target.")

    # -----------------------------------------------------------------------
    # Category 6: Anomaly Diagnostics & Loss Valuation (Cases 71 - 84)
    # -----------------------------------------------------------------------
    add_case(71, "anomaly_analysis", "What is the financial tariff used to compute monetary loss for anomalies in INR/kWh?", ["list_anomalies"], {"tariff": 3.50}, "Default financial loss tariff.")
    add_case(72, "anomaly_analysis", "What is the financial loss threshold in INR defining critical severity anomalies?", ["list_anomalies"], {"critical_loss": 10000.0}, "Critical severity > 10,000 INR.")
    add_case(73, "anomaly_analysis", "What is the financial loss threshold in INR defining high severity anomalies?", ["list_anomalies"], {"high_loss": 5000.0}, "High severity > 5,000 INR.")
    add_case(74, "anomaly_analysis", "What is the financial loss threshold in INR defining medium severity anomalies?", ["list_anomalies"], {"medium_loss": 1000.0}, "Medium severity > 1,000 INR.")
    add_case(75, "anomaly_analysis", "What is the financial loss threshold in INR defining low severity anomalies?", ["list_anomalies"], {"low_loss": 200.0}, "Low severity > 200 INR.")
    add_case(76, "anomaly_analysis", "What is the maximum allowed time window in days for ad-hoc on-demand anomaly detection?", ["detect_on_demand"], {"max_scan_days": 90.0}, "90 days maximum scan window.", tol=0.0)
    add_case(77, "anomaly_analysis", "What is the standard Z-score threshold used in statistical anomaly detection?", ["detect_on_demand"], {"zscore_threshold": 3.0}, "3 sigma statistical outlier threshold.")
    add_case(78, "anomaly_analysis", "What is the IQR multiplier used in Tukey boxplot anomaly detection?", ["detect_on_demand"], {"iqr_multiplier": 1.5}, "1.5 IQR outlier multiplier.")
    add_case(79, "anomaly_analysis", "How many consecutive anomalous intervals are required to confirm an anomaly?", ["detect_on_demand"], {"persistence_intervals": 3.0}, "3 persistence intervals rule.", tol=0.0)
    add_case(80, "anomaly_analysis", "What is the clear-sky irradiance residual threshold percentage for soiling detection?", ["detect_on_demand"], {"residual_threshold": 15.0}, "15% irradiance residual threshold.")
    add_case(81, "anomaly_analysis", "What is the minimum duration in minutes for an operational anomaly to be registered?", ["list_anomalies"], {"min_duration": 15.0}, "15m minimum anomaly duration.", tol=0.0)
    add_case(82, "anomaly_analysis", "What PR threshold defines severe inverter underperformance?", ["list_anomalies"], {"underperformance_pr": 75.0}, "75% PR underperformance alert.")
    add_case(83, "anomaly_analysis", "What soiling percentage indicates a mandatory panel cleaning requirement?", ["list_anomalies"], {"soiling_threshold": 10.0}, "10% soiling cleaning trigger.")
    add_case(84, "anomaly_analysis", "How many distinct anomaly types are classified in the CARE ground-truth catalog?", ["list_anomalies"], {"anomaly_types_count": 4.0}, "4 types: soiling, trip, clipping, flatline.", tol=0.0)

    # -----------------------------------------------------------------------
    # Category 7: Operational Events & Grid Interconnection (Cases 85 - 92)
    # -----------------------------------------------------------------------
    add_case(85, "event_listing", "What is the nominal grid evacuation voltage rating in kV?", ["list_events"], {"grid_voltage": 33.0}, "33 kV nominal evacuation voltage.")
    add_case(86, "event_listing", "What is the Indian grid standard nominal frequency in Hertz?", ["list_events"], {"grid_frequency": 50.0}, "50 Hz nominal grid frequency.")
    add_case(87, "event_listing", "What is the grid frequency operating tolerance band in Hertz around 50 Hz?", ["list_events"], {"freq_tolerance": 0.5}, "±0.5 Hz Indian grid frequency band.")
    add_case(88, "event_listing", "What is the over-voltage trip limit in kV (+10% of 33 kV)?", ["list_events"], {"over_voltage": 36.3}, "36.3 kV over-voltage trip.")
    add_case(89, "event_listing", "What is the under-voltage trip limit in kV (-10% of 33 kV)?", ["list_events"], {"under_voltage": 29.7}, "29.7 kV under-voltage trip.")
    add_case(90, "event_listing", "What is the standard inverter auto-restart delay in seconds following a grid trip?", ["list_events"], {"restart_delay": 300.0}, "300s (5-minute) restart delay.")
    add_case(91, "event_listing", "What is the minimum required power factor capability at the grid point of interconnection?", ["list_events"], {"power_factor": 0.95}, "0.95 leading/lagging power factor.")
    add_case(92, "event_listing", "What is the default operational events query window in hours?", ["list_events"], {"event_window_hours": 24.0}, "24 hours event query window.")

    # -----------------------------------------------------------------------
    # Category 8: Data Coverage & Telemetry Quality (Cases 93 - 100)
    # -----------------------------------------------------------------------
    add_case(93, "data_coverage", "What is the target telemetry data completeness percentage for solar sensors?", ["get_data_coverage"], {"target_coverage": 100.0}, "100% full coverage target.")
    add_case(94, "data_coverage", "What is the minimum acceptable telemetry coverage percentage for daily reports?", ["get_data_coverage"], {"min_acceptable": 70.0}, "70% minimum coverage threshold.")
    add_case(95, "data_coverage", "What dropout percentage triggers a sensor communication health alert?", ["get_data_coverage"], {"dropout_alert": 30.0}, "30% missing data dropout alert.")
    add_case(96, "data_coverage", "How many 15-minute telemetry intervals are recorded in a full 24-hour day?", ["get_data_coverage"], {"daily_intervals": 96.0}, "24 * 4 = 96 intervals per day.", tol=0.0)
    add_case(97, "data_coverage", "How many 15-minute telemetry intervals are in a 12-hour active daylight window?", ["get_data_coverage"], {"daylight_intervals": 48.0}, "12 * 4 = 48 intervals.", tol=0.0)
    add_case(98, "data_coverage", "What is the default time-to-live in seconds for cached timeseries result references?", ["get_data_coverage"], {"ref_ttl_seconds": 3600.0}, "3600 seconds (1 hour) TTL.", tol=0.0)
    add_case(99, "data_coverage", "What is the default time-to-live in seconds for interactive chart specifications?", ["get_data_coverage"], {"chart_ttl_seconds": 7200.0}, "7200 seconds (2 hours) TTL.", tol=0.0)
    add_case(100, "data_coverage", "What is the maximum allowed tool call limit per conversational query turn?", ["get_data_coverage"], {"tool_cap": 15.0}, "15 tool calls safety limit.", tol=0.0)

    return cases


def save_golden_dataset_to_file(path: Path, cases: Optional[List[GoldenTestCase]] = None) -> None:
    """Serialize golden dataset to JSON file."""
    dataset = cases or generate_golden_dataset()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([c.model_dump() for c in dataset], f, indent=2)


def load_golden_dataset_from_file(path: Path) -> List[GoldenTestCase]:
    """Load golden dataset from JSON file or generate if missing."""
    if not path.exists():
        dataset = generate_golden_dataset()
        save_golden_dataset_to_file(path, dataset)
        return dataset

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [GoldenTestCase.model_validate(item) for item in data]
