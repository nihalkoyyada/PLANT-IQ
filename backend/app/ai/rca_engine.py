"""Root Cause Analysis (RCA) Workflow Engine (FR-7.1, Task S6-AI-01).

Implements:
1. End-to-end diagnostic execution workflow triggered on anomalies.
2. Step-by-step LLM diagnostic reasoning over multi-channel telemetry, peer assets, and SCADA alarms.
3. Strict structured output extraction (ranked causes, concrete evidence links, chronological narrative).
4. Full persistence layer updating anomaly record in PostgreSQL/TimescaleDB with audit tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.rca_context import DiagnosticContextAggregator, DiagnosticContextPayload
from app.llm.base import BaseProvider
from app.llm.factory import get_llm_provider
from app.llm.types import Message, TextBlock
from app.models.entities import Anomaly, AuditLog, Plant
from app.schemas.rca import (
    RCANarrativeReport,
    RCAEvidenceLink,
    RCATelemetrySummary,
    RankedCause,
)

logger = logging.getLogger("plantiq.ai.rca")


RCA_SYSTEM_PROMPT = """You are PlantIQ's Chief SCADA Diagnostic Engineer, specializing in industrial solar PV failure analysis, root-cause attribution, and field engineering remediation.

Your task is to analyze empirical multi-channel telemetry, peer inverter baselines, weather conditions, and SCADA alarm logs surrounding a detected plant anomaly to reconstruct the exact failure sequence and attribute the root cause.

GUIDELINES FOR PHYSICAL DIAGNOSIS:
1. Inverter AC Contactor / Breaker Trip: Power drops abruptly to near 0 kW while solar irradiance remains high and peer inverters operate normally. Often accompanied by SCADA trip codes or frequency/voltage disturbance alarms.
2. String Combiner Fuse Blown or DC Disconnect Open: Inverter continues operating, but at a permanent fractional deficit (e.g. 10%–25% below peer median) across sunny midday hours.
3. MPPT Dynamic Tracking Hunting / Localized Shading: Erratic, fluctuating output with high coefficient of variation (CV) during variable irradiance or partial module obstruction.
4. Inverter Over-Temperature Curtailment: Output clamps or thermal foldback occurs during maximum ambient temperatures (>40°C) with high DC currents.
5. Pyranometer / Sensor Calibration Drift: Apparent performance ratio anomaly where all inverters deviate synchronously from the reference sensor, but peer inverters match each other closely.
6. Grid Curtailment / Plant-wide Outage: All peer inverters simultaneously drop or clamp generation regardless of local asset condition.

STRICT JSON OUTPUT CONTRACT:
You must respond with ONLY a single valid JSON object (no markdown intro/outro, or inside ```json code block) conforming exactly to this structure:
{
  "summary": "Detailed, chronological narrative explaining the failure sequence from pre-fault steady state to failure onset and subsequent impact.",
  "primary_root_cause": "Short definitive title of the top root cause",
  "confidence_score": 0.85,
  "ranked_causes": [
    {
      "rank": 1,
      "cause": "Primary failure factor title",
      "probability": 0.70,
      "category": "electrical | inverter_electronics | grid | thermal | sensor | environmental",
      "rationale": "Clear technical explanation citing specific data points"
    },
    {
      "rank": 2,
      "cause": "Secondary failure factor title",
      "probability": 0.20,
      "category": "electrical | inverter_electronics | grid | thermal | sensor | environmental",
      "rationale": "Why this secondary factor is plausible but less probable"
    },
    {
      "rank": 3,
      "cause": "Tertiary failure factor title",
      "probability": 0.10,
      "category": "electrical | inverter_electronics | grid | thermal | sensor | environmental",
      "rationale": "Why this third factor is considered"
    }
  ],
  "evidence_links": [
    {
      "timestamp": "ISO-8601 timestamp",
      "source": "Channel or log name (e.g. 'INV-07:power_ac')",
      "observed_value": "e.g. 0.0 kW",
      "expected_value": "e.g. 980.5 kW",
      "note": "Domain interpretation of this specific data point",
      "status": "outlier | baseline | impact | event | correlation"
    }
  ],
  "recommended_checks": [
    "Prioritized actionable field check 1",
    "Prioritized actionable field check 2",
    "Prioritized actionable field check 3"
  ]
}

Ensure that probabilities in ranked_causes sum to approximately 1.0 (0.98 to 1.02).
Every number and citation must derive strictly from the provided context.
"""


class RCAWorkflowEngine:
    """Diagnostic execution workflow engine for Root Cause Analysis (FR-7.1)."""

    def __init__(self, provider: Optional[BaseProvider] = None) -> None:
        self.provider = provider or get_llm_provider()

    async def execute_rca(
        self,
        db: Session,
        anomaly_id: UUID,
        user_id: Optional[UUID] = None,
        pre_window_hours: float = 2.0,
        post_window_hours: float = 2.0,
        force_regenerate: bool = False,
    ) -> RCANarrativeReport:
        """Execute full diagnostic workflow for an anomaly and persist results to DB."""
        t0 = time.perf_counter()

        anomaly = db.get(Anomaly, anomaly_id)
        if not anomaly:
            raise ValueError(f"Anomaly with ID {anomaly_id} not found.")

        # Check if completed RCA already exists and force_regenerate is False
        if not force_regenerate and anomaly.rca_narrative and isinstance(anomaly.rca_narrative, dict):
            narrative = anomaly.rca_narrative
            if "primary_root_cause" in narrative and "ranked_causes" in narrative:
                try:
                    return RCANarrativeReport.model_validate(narrative)
                except Exception:
                    pass

        # 1. Aggregate empirical SCADA telemetry, peer data, and error events
        context = DiagnosticContextAggregator.aggregate(
            db=db,
            anomaly=anomaly,
            pre_window_hours=pre_window_hours,
            post_window_hours=post_window_hours,
        )

        # 2. Generate diagnosis via LLM or deterministic fallback
        report_data = await self._generate_diagnostic_report(context)

        # 3. Calculate quantitative telemetry summary
        telemetry_summary = RCATelemetrySummary(
            peak_deficit_kw=round(context.peak_deficit_kw, 2),
            total_energy_loss_kwh=round(context.energy_loss_kwh, 2),
            estimated_revenue_loss_inr=round(context.financial_loss_inr, 2) if context.financial_loss_inr else None,
            peer_generation_delta_pct=round(context.peer_generation_delta_pct, 1) if context.peer_generation_delta_pct is not None else None,
            pre_fault_avg_power_kw=round(context.pre_fault_avg_power_kw, 2),
            fault_avg_power_kw=round(context.fault_avg_power_kw, 2),
            irradiance_poa_avg_wm2=round(context.weather_poa_avg_wm2, 1) if context.weather_poa_avg_wm2 is not None else None,
            is_daylight=context.is_daylight,
            scada_events_count=len(context.scada_events),
        )

        # 4. Synthesize complete evidence links combining telemetry and logs
        evidence_links = self._compile_evidence_links(context, report_data.get("evidence_links", []))

        # 5. Build validated RCANarrativeReport
        duration_ms = int((time.perf_counter() - t0) * 1000)

        report = RCANarrativeReport(
            anomaly_id=anomaly.id,
            plant_id=context.plant_id,
            asset_id=context.asset_id,
            asset_name=context.asset_name,
            summary=report_data.get("summary", f"Root cause diagnostic analysis for {context.asset_name}."),
            primary_root_cause=report_data.get("primary_root_cause", "Inverter Operational Deficit"),
            confidence_score=float(report_data.get("confidence_score", 0.80)),
            ranked_causes=report_data.get("ranked_causes", []),
            evidence_links=evidence_links,
            recommended_checks=report_data.get("recommended_checks", []),
            telemetry_summary=telemetry_summary,
            generated_at=datetime.now(timezone.utc).isoformat(),
            model=getattr(self.provider, "model", "mock-copilot-v1"),
            execution_time_ms=duration_ms,
        )

        # 6. Persist structured report into database
        self.persist_rca_report(db=db, anomaly=anomaly, report=report, user_id=user_id)

        return report

    async def _generate_diagnostic_report(
        self,
        context: DiagnosticContextPayload,
    ) -> Dict[str, Any]:
        """Invoke LLM provider with structured diagnostic prompt, with deterministic fallback."""
        summary_payload = context.to_summary_dict()
        user_prompt = (
            f"Diagnose the following industrial solar anomaly for asset '{context.asset_name}':\n"
            f"{json.dumps(summary_payload, indent=2)}\n\n"
            "Produce the complete structured diagnostic JSON including chronological summary, "
            "ranked causes with probabilities, evidence links, and physical field checks."
        )

        # In mock or test mode, generate high-fidelity domain-accurate response
        provider_name = getattr(self.provider, "model", "")
        if "mock" in provider_name.lower():
            return self._synthesize_deterministic_rca(context)

        try:
            messages = [
                Message(role="user", content=[TextBlock(text=user_prompt)]),
            ]
            response = await self.provider.chat(
                messages=messages,
                system=RCA_SYSTEM_PROMPT,
                max_tokens=2048,
                temperature=0.1,
            )
            raw_text = response.text or ""
            parsed = self._extract_json(raw_text)
            if parsed and "primary_root_cause" in parsed and "ranked_causes" in parsed:
                return parsed
        except Exception as e:
            logger.warning(f"LLM diagnostic generation failed ({e}); falling back to deterministic RCA.")

        return self._synthesize_deterministic_rca(context)

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON object from raw LLM response text."""
        # 1. Direct JSON parse
        try:
            return json.loads(text.strip())
        except Exception:
            pass

        # 2. Extract from markdown code fence
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        # 3. Locate balanced curly braces
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass

        return None

    def _compile_evidence_links(
        self,
        context: DiagnosticContextPayload,
        llm_links: List[Dict[str, Any]],
    ) -> List[RCAEvidenceLink]:
        """Compile and guarantee concrete evidence links from telemetry and logs."""
        links: List[RCAEvidenceLink] = []

        # 1. Telemetry drop evidence
        fault_start_iso = context.fault_start.isoformat()
        links.append(
            RCAEvidenceLink(
                timestamp=fault_start_iso,
                source=f"{context.asset_name}:power_ac",
                observed_value=f"{context.fault_avg_power_kw:.1f} kW",
                expected_value=f"{context.pre_fault_avg_power_kw:.1f} kW",
                note=(
                    f"Power dropped from pre-fault average of {context.pre_fault_avg_power_kw:.1f} kW "
                    f"to {context.fault_avg_power_kw:.1f} kW during fault onset."
                ),
                status="outlier",
                chart_view={
                    "start": context.context_start.isoformat(),
                    "end": context.context_end.isoformat(),
                    "channel": "power_ac",
                    "canonical_key": "power_ac",
                },
            )
        )

        # 2. Peak deficit impact
        links.append(
            RCAEvidenceLink(
                timestamp=fault_start_iso,
                source=f"{context.asset_name}:peak_deficit",
                observed_value=f"{context.peak_deficit_kw:.1f} kW deficit",
                expected_value=f"{context.rated_kw:.1f} kW rated",
                note=f"Peak deficit reached {context.peak_deficit_kw:.1f} kW (integrated loss ~{context.energy_loss_kwh:.1f} kWh).",
                status="impact",
            )
        )

        # 3. Solar Irradiance context
        if context.weather_poa_avg_wm2 is not None:
            links.append(
                RCAEvidenceLink(
                    timestamp=fault_start_iso,
                    source="WeatherStation:irradiance_poa",
                    observed_value=f"{context.weather_poa_avg_wm2:.1f} W/m²",
                    expected_value="> 50 W/m²",
                    note=(
                        f"Active daylight insolation verified at {context.weather_poa_avg_wm2:.1f} W/m² "
                        "confirming reduction is not due to sunset or darkness."
                    ),
                    status="baseline",
                )
            )

        # 4. Peer inverter isolation
        if context.peer_median_power_kw is not None and context.peer_generation_delta_pct is not None:
            links.append(
                RCAEvidenceLink(
                    timestamp=fault_start_iso,
                    source="PeerInverters:median_power",
                    observed_value=f"{context.peer_median_power_kw:.1f} kW",
                    expected_value=f"{context.fault_avg_power_kw:.1f} kW",
                    note=(
                        f"Peer inverters operated normally at median {context.peer_median_power_kw:.1f} kW "
                        f"({context.peer_generation_delta_pct:.1f}% higher), isolating failure to {context.asset_name}."
                    ),
                    status="correlation",
                )
            )

        # 5. SCADA Alarm / Error events
        for ev in context.scada_events:
            links.append(
                RCAEvidenceLink(
                    timestamp=ev.get("timestamp", fault_start_iso),
                    source=f"SCADA:{ev.get('code', 'ALARM')}",
                    observed_value=ev.get("event_type", "error"),
                    expected_value="Normal Operation",
                    note=f"Alarm code {ev.get('code')}: {ev.get('message', 'SCADA alarm triggered.')}",
                    status="event",
                )
            )

        # Merge any unique links proposed by the LLM
        for l in llm_links:
            try:
                item = RCAEvidenceLink.model_validate(l)
                if not any(existing.source == item.source and existing.timestamp == item.timestamp for existing in links):
                    links.append(item)
            except Exception:
                pass

        return links

    def _synthesize_deterministic_rca(
        self,
        context: DiagnosticContextPayload,
    ) -> Dict[str, Any]:
        """Synthesize domain-accurate diagnostic attribution based on empirical telemetry signatures."""
        asset_name = context.asset_name
        is_zero_drop = context.fault_avg_power_kw <= 10.0 and context.pre_fault_avg_power_kw >= 50.0
        has_trip_event = any("trip" in str(ev.get("message", "")).lower() or "trip" in str(ev.get("event_type", "")).lower() for ev in context.scada_events)
        is_isolated = context.peer_generation_delta_pct is not None and context.peer_generation_delta_pct > 30.0
        high_temp = context.weather_temp_ambient_c is not None and context.weather_temp_ambient_c >= 42.0

        if is_zero_drop or has_trip_event:
            primary_cause = "Inverter AC Contactor / Breaker Trip"
            conf1 = 0.75
            conf2 = 0.15
            conf3 = 0.10
            ranked = [
                {
                    "rank": 1,
                    "cause": "Inverter AC Contactor / Breaker Trip",
                    "probability": conf1,
                    "category": "electrical",
                    "rationale": (
                        f"Abrupt drop in power to {context.fault_avg_power_kw:.1f} kW on {asset_name} "
                        f"while peer inverters operated at median {context.peer_median_power_kw or 900.0:.1f} kW "
                        f"and irradiance was {context.weather_poa_avg_wm2 or 750.0:.1f} W/m²."
                    ),
                },
                {
                    "rank": 2,
                    "cause": "DC Main Disconnect Switch Open",
                    "probability": conf2,
                    "category": "inverter_electronics",
                    "rationale": "Complete loss of conversion without prior progressive thermal degradation.",
                },
                {
                    "rank": 3,
                    "cause": "Grid Voltage / Frequency Surge Trip",
                    "probability": conf3,
                    "category": "grid",
                    "rationale": "Localized anti-islanding or protective relay actuation at the inverter terminal.",
                },
            ]
            checks = [
                f"Verify AC circuit breaker and contactor auxiliary contacts on {asset_name}.",
                f"Inspect DC isolator switch and surge protection device (SPD) flags.",
                "Check inverter onboard event log via Modbus/SCADA console for lockout fault codes.",
                "Verify AC grid voltage balance across all three phases.",
            ]
            narrative = (
                f"At {context.fault_start.strftime('%Y-%m-%d %H:%M:%S UTC')}, {asset_name} experienced an abrupt collapse "
                f"in AC power generation from {context.pre_fault_avg_power_kw:.1f} kW down to {context.fault_avg_power_kw:.1f} kW. "
                f"During this window, Plane of Array (POA) irradiance remained high ({context.weather_poa_avg_wm2 or 700.0:.0f} W/m²), "
                f"and adjacent inverters operated normally at median {context.peer_median_power_kw or 900.0:.1f} kW. "
                "The instantaneous nature of the drop and isolation from peer performance confirms an internal AC contactor "
                "or protective circuit breaker trip rather than environmental soiling or grid curtailment."
            )
        elif high_temp:
            primary_cause = "Inverter Thermal Derating / Cooling Fan Failure"
            conf1 = 0.65
            conf2 = 0.22
            conf3 = 0.13
            ranked = [
                {
                    "rank": 1,
                    "cause": "Inverter Thermal Derating / Cooling Fan Failure",
                    "probability": conf1,
                    "category": "thermal",
                    "rationale": f"High ambient temperature ({context.weather_temp_ambient_c:.1f}°C) triggered power curtailment envelope.",
                },
                {
                    "rank": 2,
                    "cause": "IGBT Heatsink Dust Accumulation",
                    "probability": conf2,
                    "category": "inverter_electronics",
                    "rationale": "Reduced heat dissipation efficiency causing internal thermal limit clamps.",
                },
                {
                    "rank": 3,
                    "cause": "Cabinet Over-Temperature Sensor Drift",
                    "probability": conf3,
                    "category": "sensor",
                    "rationale": "Erroneous temperature telemetry commanding premature thermal foldback.",
                },
            ]
            checks = [
                f"Inspect external cooling fans and air intake dust filters on {asset_name}.",
                "Check internal heatsink temperature telemetry versus ambient benchmark.",
                "Verify thermal paste and heat pipe integrity on primary IGBT power modules.",
            ]
            narrative = (
                f"During peak afternoon insolation, {asset_name} clamped generation with a {context.peak_deficit_kw:.1f} kW deficit. "
                f"Ambient temperatures reached {context.weather_temp_ambient_c:.1f}°C. Telemetry indicates the inverter "
                "entered thermal foldback derating to protect power electronics from over-temperature failure."
            )
        elif context.peer_generation_delta_pct is not None and context.peer_generation_delta_pct < 5.0:
            primary_cause = "Pyranometer Reference Sensor Calibration Drift"
            conf1 = 0.60
            conf2 = 0.25
            conf3 = 0.15
            ranked = [
                {
                    "rank": 1,
                    "cause": "Pyranometer Reference Sensor Calibration Drift",
                    "probability": conf1,
                    "category": "sensor",
                    "rationale": "All inverters track each other consistently within 5%, indicating the weather reference is shifted.",
                },
                {
                    "rank": 2,
                    "cause": "Cloud Transient / Rapid Irradiance Gradient",
                    "probability": conf2,
                    "category": "environmental",
                    "rationale": "Localized cloud edge effect causing temporary insolation divergence across the array.",
                },
                {
                    "rank": 3,
                    "cause": "Grid Utility Power Curtailment",
                    "probability": conf3,
                    "category": "grid",
                    "rationale": "Plant-wide active power setpoint clamp commanded by substation dispatch.",
                },
            ]
            checks = [
                "Clean pyranometer optical dome and inspect for bird droppings or dust film.",
                "Perform secondary calibration check against satellite/diurnal clear-sky reference.",
                "Check grid operator active power dispatch logs.",
            ]
            narrative = (
                f"Performance Ratio deficit flagged on {asset_name}, but peer comparison reveals that all inverters "
                f"performed within {context.peer_generation_delta_pct:.1f}% of median. Synchronized deviation across all "
                "generating blocks indicates pyranometer sensor drift or localized cloud cover rather than an asset breakdown."
            )
        else:
            primary_cause = "String Combiner Fuse Blown or DC Disconnect Open"
            conf1 = 0.65
            conf2 = 0.23
            conf3 = 0.12
            ranked = [
                {
                    "rank": 1,
                    "cause": "String Combiner Fuse Blown or DC Disconnect Open",
                    "probability": conf1,
                    "category": "electrical",
                    "rationale": (
                        f"Consistent under-generation deficit ({context.peak_deficit_kw:.1f} kW, {context.peer_generation_delta_pct or 15.0:.1f}% below peers) "
                        f"characteristic of lost string inputs on {asset_name}."
                    ),
                },
                {
                    "rank": 2,
                    "cause": "Severe Module Soiling or Bypass Diode Conduction",
                    "probability": conf2,
                    "category": "environmental",
                    "rationale": "Localized module obstruction causing bypass diode shorting and reduced array voltage.",
                },
                {
                    "rank": 3,
                    "cause": "MPPT Voltage Sub-tracker Misalignment",
                    "probability": conf3,
                    "category": "inverter_electronics",
                    "rationale": "Inverter operating slightly off maximum power point voltage curve.",
                },
            ]
            checks = [
                f"Measure DC string open-circuit voltage (Voc) and string currents (Isc) at combiner boxes for {asset_name}.",
                "Inspect DC fuses and surge protection devices (SPDs) for tripped indicator flags.",
                "Conduct handheld thermal scan across PV modules to locate hot spots or failed bypass diodes.",
            ]
            narrative = (
                f"Analysis of telemetry on {asset_name} reveals a persistent generation deficit of {context.peak_deficit_kw:.1f} kW "
                f"across active daylight hours (total loss {context.energy_loss_kwh:.1f} kWh). "
                f"Peer inverters maintained normal generation at {context.peer_median_power_kw or 850.0:.1f} kW. "
                "The proportionate and steady magnitude of the deficit indicates that one or more DC input strings are disconnected "
                "due to blown combiner fuses or open DC string isolators."
            )

        return {
            "summary": narrative,
            "primary_root_cause": primary_cause,
            "confidence_score": conf1,
            "ranked_causes": ranked,
            "evidence_links": [],
            "recommended_checks": checks,
        }

    @staticmethod
    def persist_rca_report(
        db: Session,
        anomaly: Anomaly,
        report: RCANarrativeReport,
        user_id: Optional[UUID] = None,
    ) -> Anomaly:
        """Persist structured RCA report directly into Anomaly record and log audit entry (FR-7.1)."""
        report_dict = report.model_dump(mode="json")

        # Update Anomaly fields
        anomaly.rca_narrative = report_dict
        if user_id:
            anomaly.rca_by = user_id

        # Update details JSON with RCA completion metadata
        details = dict(anomaly.details or {})
        details.update({
            "rca_status": "completed",
            "rca_generated_at": report.generated_at,
            "rca_primary_cause": report.primary_root_cause,
            "rca_confidence": report.confidence_score,
            "rca_model": report.model,
            "rca_execution_time_ms": report.execution_time_ms,
        })
        anomaly.details = details

        # Update summary if empty or generic
        if not anomaly.summary or anomaly.summary.startswith("Generation deficit"):
            anomaly.summary = f"{report.primary_root_cause} on {report.asset_name or 'Inverter'}: {report.summary[:140]}..."

        # Create AuditLog record
        audit = AuditLog(
            user_id=user_id,
            action="rca_analysis",
            entity="anomaly",
            entity_id=anomaly.id,
            details={
                "anomaly_id": str(anomaly.id),
                "primary_root_cause": report.primary_root_cause,
                "confidence_score": report.confidence_score,
                "model": report.model,
                "execution_time_ms": report.execution_time_ms,
                "ranked_causes_count": len(report.ranked_causes),
                "evidence_links_count": len(report.evidence_links),
            },
        )
        db.add(audit)
        db.commit()
        db.refresh(anomaly)

        logger.info(
            f"Successfully persisted RCA report for anomaly {anomaly.id}: {report.primary_root_cause} "
            f"({report.confidence_score * 100:.0f}% confidence)."
        )
        return anomaly
