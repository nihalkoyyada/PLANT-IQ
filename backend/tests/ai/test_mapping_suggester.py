"""Comprehensive unit and integration tests for MappingSuggester.

Task: S2-AI-02
Validates:
- Tier 1: Exact, normalized, camelCase, and rapidfuzz string matching.
- Tier 1: Domain-specific solar telemetry synonyms (Kaggle, SMA, Campbell, Meteocontrol).
- Tier 2: Low-confidence routing to LLM provider interface with structured prompts.
- Tier 2: Graceful error handling when LLM returns invalid JSON or encounters an error.
- Edge Cases: Empty strings, whitespace, numbers, punctuation, unrelated business fields.
- Alternative candidate ranking and score propagation.
- Batch processing: Synchronous and Asynchronous APIs.
- Dataclass models, serialization, and typing completeness.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional
import pytest

from app.ai.mapping_suggester import (
    CANONICAL_SIGNALS,
    BatchMappingResult,
    MappingSuggester,
    MappingSuggestion,
    normalize_header_text,
    suggest_mappings,
    suggest_mappings_async,
)
from app.llm.base import BaseProvider
from app.llm.types import (
    Message,
    ProviderResponse,
    StreamDelta,
    TextBlock,
    ToolDefinition,
    Usage,
)


# ---------------------------------------------------------------------------
# Mock LLM Provider for Deterministic Offline Testing
# ---------------------------------------------------------------------------


class MockSuggesterLLMProvider(BaseProvider):
    """Mock LLM provider returning deterministic JSON for mapping fallback tests."""

    def __init__(
        self,
        canned_mappings: Optional[Dict[str, Dict[str, Any]]] = None,
        raise_error: bool = False,
        return_invalid_json: bool = False,
    ) -> None:
        super().__init__(model="mock-suggester-model")
        self.canned_mappings = canned_mappings or {
            "spannung_ac": {
                "suggested_canonical_key": "voltage_ac",
                "confidence_score": 0.93,
                "reasoning": "German engineering term 'Spannung' translates directly to voltage, with AC specifier.",
            },
            "datum_uhrzeit": {
                "suggested_canonical_key": "timestamp",
                "confidence_score": 0.98,
                "reasoning": "German 'Datum' (date) and 'Uhrzeit' (time) represent temporal observation logging.",
            },
        }
        self.raise_error = raise_error
        self.return_invalid_json = return_invalid_json
        self.calls_count = 0

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> ProviderResponse:
        """Simulate LLM inference returning structured JSON mapping response."""
        self.calls_count += 1

        if self.raise_error:
            raise RuntimeError("Simulated upstream LLM network failure")

        if self.return_invalid_json:
            return ProviderResponse(
                text_blocks=[
                    TextBlock(text="I think this column might be power, but here is no valid JSON")
                ],
                model=self.model,
                usage=Usage(input_tokens=10, output_tokens=10),
            )

        # Inspect prompt to find raw header
        user_msg = ""
        if messages:
            content = messages[-1].content
            user_msg = content.lower() if isinstance(content, str) else ""

        for raw_key, payload in self.canned_mappings.items():
            if raw_key in user_msg:
                return ProviderResponse(
                    text_blocks=[TextBlock(text=json.dumps(payload))],
                    model=self.model,
                    usage=Usage(input_tokens=50, output_tokens=20),
                )

        # Default fallback for unmapped foreign term
        default_payload = {
            "suggested_canonical_key": None,
            "confidence_score": 0.0,
            "reasoning": "No relevant solar telemetry canonical key identified.",
        }
        return ProviderResponse(
            text_blocks=[TextBlock(text=json.dumps(default_payload))],
            model=self.model,
            usage=Usage(input_tokens=50, output_tokens=20),
        )

    async def stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[StreamDelta]:
        """Unused streaming interface for provider protocol completeness."""
        yield StreamDelta(delta_text="mock")


# ---------------------------------------------------------------------------
# Tier 1: Normalization & String Similarity Unit Tests
# ---------------------------------------------------------------------------


def test_normalize_header_text() -> None:
    """Verify camelCase splitting and delimiter normalization."""
    assert normalize_header_text("activePower") == "active power"
    assert normalize_header_text("AC_POWER_KW") == "ac power kw"
    assert normalize_header_text("SlrW_Avg(1)") == "slr w avg 1"
    assert normalize_header_text("Date-Time.UTC") == "date time utc"
    assert normalize_header_text("   daily_yield   ") == "daily yield"


def test_exact_canonical_keys() -> None:
    """Verify headers matching canonical keys resolve with 100% confidence."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    keys_to_test = [
        "power_ac",
        "power_dc",
        "energy_ac_daily",
        "energy_ac_total",
        "irradiance_poa",
        "temperature_ambient",
        "temperature_module",
        "voltage_dc",
        "current_dc",
        "frequency_grid",
        "power_factor",
        "timestamp",
        "device_id",
        "plant_id",
    ]

    for key in keys_to_test:
        suggestion = suggester.suggest(key)
        assert suggestion.suggested_canonical_key == key
        assert suggestion.confidence_score == 1.0
        assert suggestion.source in ("exact", "fuzzy")
        assert suggestion.is_mapped is True


def test_case_insensitive_and_symbols() -> None:
    """Verify casing and delimiter differences resolve to canonical keys."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    test_cases = [
        ("AC_POWER", "power_ac"),
        ("dc-power", "power_dc"),
        ("DAILY-YIELD", "energy_ac_daily"),
        ("Ambient_Temperature", "temperature_ambient"),
        ("Module_Temperature", "temperature_module"),
        ("GRID.FREQUENCY", "frequency_grid"),
        ("DATE_TIME", "timestamp"),
        ("source-key", "device_id"),
        ("PLANT_ID", "plant_id"),
    ]

    for raw, expected in test_cases:
        suggestion = suggester.suggest(raw)
        assert suggestion.suggested_canonical_key == expected
        assert suggestion.confidence_score >= 0.90
        assert suggestion.is_mapped is True


def test_camel_case_headers() -> None:
    """Verify camelCase telemetry headers resolve correctly."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    test_cases = [
        ("activePower", "power_ac"),
        ("gridFrequency", "frequency_grid"),
        ("ambientTemperature", "temperature_ambient"),
        ("moduleTemperature", "temperature_module"),
        ("windSpeed", "wind_speed"),
        ("windDirection", "wind_direction"),
    ]

    for raw, expected in test_cases:
        suggestion = suggester.suggest(raw)
        assert suggestion.suggested_canonical_key == expected
        assert suggestion.confidence_score >= 0.85
        assert suggestion.is_mapped is True


# ---------------------------------------------------------------------------
# Tier 1: Real-World Dataset Synonyms Tests
# ---------------------------------------------------------------------------


def test_kaggle_solar_pv_headers() -> None:
    """Verify all 10 Kaggle Gandikota solar benchmark headers resolve."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    kaggle_headers = [
        ("DATE_TIME", "timestamp"),
        ("PLANT_ID", "plant_id"),
        ("SOURCE_KEY", "device_id"),
        ("DC_POWER", "power_dc"),
        ("AC_POWER", "power_ac"),
        ("DAILY_YIELD", "energy_ac_daily"),
        ("TOTAL_YIELD", "energy_ac_total"),
        ("AMBIENT_TEMPERATURE", "temperature_ambient"),
        ("MODULE_TEMPERATURE", "temperature_module"),
        ("IRRADIATION", "irradiance_poa"),
    ]

    for header, expected in kaggle_headers:
        suggestion = suggester.suggest(header)
        assert suggestion.suggested_canonical_key == expected
        assert suggestion.confidence_score >= 0.95
        assert suggestion.source in ("exact", "fuzzy")


def test_sma_inverter_headers() -> None:
    """Verify standard SMA commercial & utility inverter telemetry headers."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    sma_headers = [
        ("P_AC", "power_ac"),
        ("P_DC", "power_dc"),
        ("E_Daily", "energy_ac_daily"),
        ("E_Total", "energy_ac_total"),
        ("V_DC", "voltage_dc"),
        ("I_DC", "current_dc"),
        ("Grid_Freq", "frequency_grid"),
        ("CosPhi", "power_factor"),
        ("Serial_Number", "device_id"),
        ("Timestamp", "timestamp"),
    ]

    for header, expected in sma_headers:
        suggestion = suggester.suggest(header)
        assert suggestion.suggested_canonical_key == expected
        assert suggestion.confidence_score >= 0.90


def test_campbell_weather_station_headers() -> None:
    """Verify Campbell Scientific weather datalogger telemetry headers."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    campbell_headers = [
        ("AirTC_Avg", "temperature_ambient"),
        ("ModuleTC_Avg", "temperature_module"),
        ("SlrW_Avg", "irradiance_poa"),
        ("WS_ms_Avg", "wind_speed"),
        ("WindDir", "wind_direction"),
        ("RECORD_TIME", "timestamp"),
        ("Station_ID", "device_id"),
    ]

    for header, expected in campbell_headers:
        suggestion = suggester.suggest(header)
        assert suggestion.suggested_canonical_key == expected
        assert suggestion.confidence_score >= 0.85


def test_meteocontrol_engineering_units() -> None:
    """Verify SCADA headers with embedded engineering suffixes."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    meteocontrol_headers = [
        ("Pac_kW", "power_ac"),
        ("Pdc_kW", "power_dc"),
        ("E_Today_kWh", "energy_ac_daily"),
        ("G_POA_Wm2", "irradiance_poa"),
        ("T_Amb_C", "temperature_ambient"),
        ("T_Mod_C", "temperature_module"),
    ]

    for header, expected in meteocontrol_headers:
        suggestion = suggester.suggest(header)
        assert suggestion.suggested_canonical_key == expected
        assert suggestion.confidence_score >= 0.85


def test_direct_foreign_synonyms() -> None:
    """Verify German direct synonyms matching Tier 1 dictionary."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    foreign_headers = [
        ("E_heute", "energy_ac_daily"),
        ("W_strahlung", "irradiance_poa"),
        ("Strom_DC", "current_dc"),
    ]

    for header, expected in foreign_headers:
        suggestion = suggester.suggest(header)
        assert suggestion.suggested_canonical_key == expected
        assert suggestion.confidence_score >= 0.90


# ---------------------------------------------------------------------------
# Tier 2: LLM Fallback Routing Tests
# ---------------------------------------------------------------------------


def test_llm_fallback_invoked_for_low_confidence() -> None:
    """Verify that headers below threshold trigger the LLM provider."""
    mock_llm = MockSuggesterLLMProvider()
    suggester = MappingSuggester(
        llm_provider=mock_llm,
        fuzzy_threshold=0.80,
        enable_llm_fallback=True,
    )

    # "Spannung_AC" is German for AC Voltage, not in rapidfuzz synonyms
    suggestion = suggester.suggest("Spannung_AC")
    assert suggestion.suggested_canonical_key == "voltage_ac"
    assert suggestion.confidence_score == 0.93
    assert suggestion.source == "llm"
    assert suggestion.reasoning is not None and "Spannung" in suggestion.reasoning
    assert mock_llm.calls_count == 1

    # "Datum_Uhrzeit" is German for Date Time
    suggestion_time = suggester.suggest("Datum_Uhrzeit")
    assert suggestion_time.suggested_canonical_key == "timestamp"
    assert suggestion_time.confidence_score == 0.98
    assert suggestion_time.source == "llm"
    assert mock_llm.calls_count == 2


def test_llm_fallback_disabled() -> None:
    """Verify behavior when enable_llm_fallback is False."""
    mock_llm = MockSuggesterLLMProvider()
    suggester = MappingSuggester(
        llm_provider=mock_llm,
        fuzzy_threshold=0.80,
        enable_llm_fallback=False,
    )

    # Obscure header should remain fuzzy/unmapped without invoking LLM
    suggestion = suggester.suggest("Spannung_AC")
    assert mock_llm.calls_count == 0
    assert suggestion.source in ("fuzzy", "unmapped")
    assert suggestion.confidence_score < 0.80


def test_llm_provider_network_error_graceful_fallback() -> None:
    """Verify that an LLM network failure does not crash the suggester."""
    failing_llm = MockSuggesterLLMProvider(raise_error=True)
    suggester = MappingSuggester(
        llm_provider=failing_llm,
        fuzzy_threshold=0.80,
        enable_llm_fallback=True,
    )

    # Suggester catches error and falls back to Tier 1 candidate
    suggestion = suggester.suggest("Spannung_AC")
    assert failing_llm.calls_count == 1
    assert suggestion.source in ("fuzzy", "unmapped")
    assert suggestion.confidence_score < 0.80


def test_llm_provider_invalid_json_fallback() -> None:
    """Verify that invalid JSON returned by LLM is handled cleanly."""
    invalid_llm = MockSuggesterLLMProvider(return_invalid_json=True)
    suggester = MappingSuggester(
        llm_provider=invalid_llm,
        fuzzy_threshold=0.80,
        enable_llm_fallback=True,
    )

    suggestion = suggester.suggest("Spannung_AC")
    assert invalid_llm.calls_count == 1
    assert suggestion.source in ("fuzzy", "unmapped")


# ---------------------------------------------------------------------------
# Edge Cases: Malformed, Whitespace, & Unrelated Headers
# ---------------------------------------------------------------------------


def test_empty_and_whitespace_headers() -> None:
    """Verify empty and whitespace strings return unmapped result."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    for empty_header in ("", "   ", "\t\n"):
        suggestion = suggester.suggest(empty_header)
        assert suggestion.suggested_canonical_key is None
        assert suggestion.confidence_score == 0.0
        assert suggestion.source == "unmapped"
        assert suggestion.is_mapped is False


def test_punctuation_and_numbers_headers() -> None:
    """Verify purely symbolic or numeric headers return unmapped."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    for weird_header in ("!@#$%^&*()", "123456789", "---___..."):
        suggestion = suggester.suggest(weird_header)
        assert suggestion.suggested_canonical_key is None
        assert suggestion.confidence_score <= 0.20
        assert suggestion.source == "unmapped"
        assert suggestion.is_mapped is False


def test_unrelated_business_headers() -> None:
    """Verify non-solar domain columns are designated as unmapped."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    unrelated = [
        "customer_credit_card_number",
        "employee_annual_salary_usd",
        "home_shipping_address_line1",
        "random_gibberish_xyz_987",
    ]

    for header in unrelated:
        suggestion = suggester.suggest(header)
        assert suggestion.suggested_canonical_key is None
        assert suggestion.confidence_score < 0.80
        assert suggestion.source == "unmapped"
        assert suggestion.is_mapped is False


# ---------------------------------------------------------------------------
# Alternative Candidates & Sample Values Context
# ---------------------------------------------------------------------------


def test_alternative_candidates_ranking() -> None:
    """Verify alternative candidates are populated and sorted descending."""
    suggester = MappingSuggester(enable_llm_fallback=False)

    suggestion = suggester.suggest("power")
    assert suggestion.suggested_canonical_key in ("power_ac", "power_dc")
    assert len(suggestion.alternative_candidates) > 0

    # Ensure alternatives are sorted by score descending
    scores = [c[1] for c in suggestion.alternative_candidates]
    assert scores == sorted(scores, reverse=True)


def test_sample_values_context() -> None:
    """Verify sample values can be passed without errors."""
    mock_llm = MockSuggesterLLMProvider()
    suggester = MappingSuggester(
        llm_provider=mock_llm,
        fuzzy_threshold=0.80,
        enable_llm_fallback=True,
    )

    suggestion = suggester.suggest(
        "Spannung_AC",
        sample_values=["230.1", "229.8", "230.4"],
    )
    assert suggestion.suggested_canonical_key == "voltage_ac"
    assert suggestion.source == "llm"


# ---------------------------------------------------------------------------
# Batch APIs: Synchronous & Asynchronous Tests
# ---------------------------------------------------------------------------


def test_suggest_batch_sync() -> None:
    """Verify synchronous suggest_batch returns complete BatchMappingResult."""
    suggester = MappingSuggester(enable_llm_fallback=False)
    headers = ["AC_POWER", "DC_POWER", "DATE_TIME", "UNKNOWN_STATUS_CODE"]

    batch_result = suggester.suggest_batch(headers)

    assert isinstance(batch_result, BatchMappingResult)
    assert batch_result.total_columns == 4
    assert batch_result.fuzzy_matches_count >= 3
    assert batch_result.unmapped_count == 1
    assert batch_result.duration_ms > 0
    assert len(batch_result.suggestions) == 4

    # Dict serialization check
    d = batch_result.to_dict()
    assert d["total_columns"] == 4
    assert len(d["suggestions"]) == 4


@pytest.mark.asyncio
async def test_suggest_batch_async() -> None:
    """Verify asynchronous suggest_batch_async executes cleanly."""
    mock_llm = MockSuggesterLLMProvider()
    suggester = MappingSuggester(
        llm_provider=mock_llm,
        fuzzy_threshold=0.80,
        enable_llm_fallback=True,
    )
    headers = ["AC_POWER", "Spannung_AC", "UNKNOWN_FLAG"]

    batch_result = await suggester.suggest_batch_async(headers)

    assert batch_result.total_columns == 3
    assert batch_result.fuzzy_matches_count >= 1
    assert batch_result.llm_fallbacks_count == 1
    assert batch_result.unmapped_count == 1


def test_module_level_helpers() -> None:
    """Verify module-level suggest_mappings synchronous helper."""
    res = suggest_mappings(["P_AC", "P_DC", "TIMESTAMP"])
    assert res.total_columns == 3
    assert res.fuzzy_matches_count == 3
    assert res.unmapped_count == 0


@pytest.mark.asyncio
async def test_module_level_async_helper() -> None:
    """Verify module-level suggest_mappings_async helper."""
    res = await suggest_mappings_async(["E_Daily", "E_Total"])
    assert res.total_columns == 2
    assert res.fuzzy_matches_count == 2
    assert res.unmapped_count == 0


def test_canonical_signals_integrity() -> None:
    """Verify all canonical signals have metadata, descriptions, and valid units."""
    assert len(CANONICAL_SIGNALS) >= 15
    for key, meta in CANONICAL_SIGNALS.items():
        assert meta.key == key
        assert len(meta.display_name) > 0
        assert len(meta.unit) > 0
        assert len(meta.description) > 0
        assert len(meta.synonyms) > 0
