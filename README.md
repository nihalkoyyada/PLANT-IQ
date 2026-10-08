# PlantIQ — Backend Architecture & Implemented Features

This document outlines the backend architecture, core engines, and features implemented across Sprints 1, 2, and 3.

---

## 📌 Executive Summary of Implemented Backend Systems

The backend provides a complete solar telemetry ingestion and analytics pipeline:
1. **Asset & Telemetry Foundation** (SQLAlchemy 2.0 + TimescaleDB)
2. **Telemetry Ingestion & Quality Control** (Polars + DuckDB + 14.8k rows/s ingest)
3. **AI Schema Mapping Layer** (Fuzzy matching + Domain synonyms + LLM fallback)
4. **Solar KPI Analytics Engine** (IEC 61724-1 compliant math + Daylight filtering)
5. **Celery Task Pipeline & CLI Tools** (Daily rollups, historical backfill, benchmark validator)

---

## 🛠️ Sprint-by-Sprint Implementation Breakdown

### 1. Sprint 1: Foundation, Asset Hierarchy & LLM Abstraction
* **Empirical EDA & Dataset Profiling (`Datasets/notebooks/01_kaggle_eda.py`)**:
  * Profiled Kaggle solar datasets using Polars and DuckDB.
  * Designated **Surya-A** (Plant 1: 28.28 MWp DC / 27.50 MW AC, 22 central inverters) and **Surya-B** (Plant 2: 26.44 MWp DC / 27.50 MW AC, 22 string inverters).
  * Accounted for Plant 1's 10x DC power scaling artifact and day-first timestamp formats (`DD-MM-YYYY HH:MM`).
* **Canonical Dictionary & Unit Converter (`backend/app/core/units.py`)**:
  * Standardized signals: `active_power_ac`, `active_power_dc`, `poa_irradiance`, `ambient_temp`, `module_temp`.
  * Vectorized unit conversion engine (W $\leftrightarrow$ kW, Wh $\leftrightarrow$ kWh, °F $\leftrightarrow$ °C, etc.).
* **Asset Tree Seeder (`backend/scripts/seed_surya.py`)**:
  * Full asset hierarchy seeding for Surya-A: Organization, Admin/Engineer/Viewer users, Plant, Block, 22 Inverters, Weather Station, and 91 Telemetry Channels.
  * Configured PPA tariff of **₹3.50/kWh** and Indian solar coordinates (Bhadla Solar Park, Rajasthan).
* **LLM Provider Layer (`backend/app/llm/`)**:
  * Normalized provider abstraction supporting **Anthropic** (Claude 3.5 Sonnet) and **OpenAI / local vLLM**.
  * Typed error handling, exponential backoff, structured JSON parsing, and smoke CLI (`backend/scripts/smoke_tooluse.py`).

---

### 2. Sprint 2: High-Performance Ingestion & AI Schema Mapper
* **File Profiler (`backend/app/ai/file_profiler.py`)**:
  * Vectorized engine analyzing uploaded CSV/Parquet files.
  * Automatically detects delimiters, timestamp formats (ISO vs. Day-First), sampling cadence (e.g., 15-min), nulls, min/max, and generates 50-point sparklines.
* **Intelligent Schema Suggester (`backend/app/ai/mapping_suggester.py`)**:
  * Two-tier auto-mapping from unknown CSV headers to canonical signals:
    * **Tier 1:** Rapidfuzz + domain synonym dictionaries (SMA, Huawei, Campbell Scientific, Meteocontrol).
    * **Tier 2:** LLM fallback when confidence is low.
  * Evaluated on standard solar datasets with 100% mapping accuracy (`backend/scripts/eval_mapping.py`).
* **Ingestion Worker & Quality Control (`backend/app/ai/ingest_worker.py`)**:
  * Direct DBAPI batch streaming into TimescaleDB (`ON CONFLICT DO UPDATE`).
  * Benchmarked at **14,851 rows/sec** (exceeding the 10,000 rows/s NFR-1 target).
  * Real-time QC flag bitmask: range checks, frozen sensor flatlines, spike detection, nighttime cutoff.
* **Fault-Injection Engine (`backend/scripts/inject_faults.py`)**:
  * Deterministic injection of realistic operational faults (soiling degradation, inverter trips, power clipping, sensor flatlines) creating `Datasets/Surya-A-demo.csv` with ground-truth catalog (`Datasets/ground_truth_anomalies.json`).

---

### 3. Sprint 3: Solar KPI Analytics Engine & NREL Validation
* **Core KPI Math Engine (`backend/app/ai/kpi_engine.py`)**:
  * Pure solar mathematical functions adhering to international standard **IEC 61724-1**:
    * **Performance Ratio (PR):** $PR = Y_f / Y_r$
    * **Capacity Utilization Factor (CUF):** Standard 24-hour CUF and active Daylight CUF.
    * **Specific Yield ($Y_f$):** $kWh / kWp$
    * **Inverter Conversion Efficiency ($\eta$):** $E_{ac} / E_{dc}$
    * **Operational Availability ($A$):** $1 - (\text{daylight downtime} / \text{daylight hours})$
    * **Energy Loss ($E_{loss}$):** Quantifies lost generation against target design PR.
    * **POA Solar Insolation Integration ($H_{poa}$):** Trapezoidal and Riemann integration.
* **Daylight Filtering & Data Quality Rules**:
  * Filters out nighttime zero-readings ($POA \le 50\text{ W/m}^2$) so nighttime values do not dilute daytime KPIs.
  * Computes telemetry coverage percentages for each evaluation window.
  * Enforces the project rule: **missing or sparse data (< 70% coverage) must never output zero**; it explicitly tags metrics with `insufficient_data`, `low_confidence`, or `approx_ghi` flags.
* **Celery Rollup Tasks (`backend/app/tasks/kpi_tasks.py`)**:
  * Automated background job aligning readings to a 15-minute grid, computing plant and inverter rollups, and upserting into the `kpis` database table.
* **CLI Operational Tools**:
  * **Historical Backfill Tool (`backend/scripts/backfill_kpis.py`):** Recomputes KPIs across historical date ranges with dry-run and async options.
  * **NREL PVDAQ Benchmark Tool (`backend/scripts/validate_pvdaq_benchmark.py`):** Runs the KPI engine against the NREL PVDAQ benchmark dataset (`PVDAQ_Reference_Sample.csv`), validating outputs against NREL baselines within a **< 0.1% delta** (well inside the $\pm 2.0\%$ tolerance band).
  * **Validation Documentation:** See [`docs/pvdaq-benchmark-validation-note.md`](docs/pvdaq-benchmark-validation-note.md).

---

### 4. Sprint 4: Anomaly Detection Engine & CARE Benchmark Suite
* **Detector Framework Registry (`backend/app/ai/detector_registry.py`)**:
  * Extensible decorator-based plugin architecture (`@register_detector`) for discovering and invoking anomaly detection algorithms.
  * Includes automated deduplication engine (`backend/app/ai/anomaly_dedup.py`), severity tiers (`SeverityPolicy`), and financial loss estimation (`FinancialLossPolicy`).
* **Physics & Machine Learning Algorithms (D1 through D4)**:
  * **D1 Statistical Outlier (`d1_statistical`):** Vectorized moving Z-score and Interquartile Range (IQR) checks to catch telemetry spikes, drops, and physically impossible readings.
  * **D2 PR Deviation (`d2_pr_deviation`):** Real-time Performance Ratio deviation detector referencing on-site pyranometers or diurnal reference curves with root-cause classification.
  * **D3 Irradiance-Residual (`d3_irradiance_residual`):** Clear-sky solar radiation model and robust regression analysis to isolate soiling, degradation, and module obstruction from natural cloud cover.
  * **D4 Isolation Forest (`d4_isolation_forest`):** Unsupervised Scikit-Learn `IsolationForest` fitting per-asset models across 7 multi-variable rolling window features with 3-interval persistence verification.
* **CARE Benchmark Harness & Reporting (`backend/scripts/run_care_benchmark.py`, `backend/app/ai/care_benchmark.py`)**:
  * Automated benchmarking evaluating D1–D4, rule baselines, and multi-model ensembles against verified ground-truth fault catalogs (`Datasets/ground_truth_anomalies.json`).
  * Computes classification metrics (Precision, Recall, F1, False Alarm Rate) and early warning Lead-Time metrics.
  * Programmatically generates executive Markdown artifacts (`docs/care-benchmark-report.md`) for stakeholder reviews and project pitches.

---

## 🧪 How to Run & Verify the Backend

All backend dependencies are managed inside the project virtual environment (`.venv`).

### 1. Run Backend Automated Test Suite (218+ Tests)
```bash
cd backend
./venv/bin/pytest tests/ai tests/scripts -v
```

### 2. Run CARE Benchmark Harness (S4-AI-05)
```bash
cd backend
./venv/bin/python scripts/run_care_benchmark.py
```

### 3. Run NREL PVDAQ Benchmark Validation
```bash
cd backend
./venv/bin/python scripts/validate_pvdaq_benchmark.py
```

### 4. Run Ingestion Throughput Benchmark
```bash
cd backend
./venv/bin/python scripts/test_ingest_throughput.py
```

### 5. Run Historical KPI Backfill CLI
```bash
cd backend
./venv/bin/python scripts/backfill_kpis.py --start-date 2023-06-01 --end-date 2023-06-06 --dry-run
```

### 6. Start FastAPI Dev Server
```bash
cd backend
./venv/bin/uvicorn app.main:app --reload --port 8000
```

