"""Tests for unit conversion module backend/app/core/units.py.

Task: S1-AI-03 Part B
Validates:
- All minimum required conversion callables (kW->W, MW->W, MWh->kWh, Wh->kWh, kW/m²->W/m², W/m²->W/m², °F->°C, K->°C)
- Inverses and cross-conversions
- Alias normalization (unicode, exponents, case)
- Vectorized Polars Series conversions (null handling, name preservation)
- Typed UnknownConversionError exception paths
"""

import math
import pytest
import polars as pl
from app.core.units import (
    UnknownConversionError,
    convert,
    get_converter,
    normalize_unit,
)


class TestUnitNormalization:
    """Test unit alias normalization."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("W/m2", "W/m²"),
            ("W/m^2", "W/m²"),
            ("w/m²", "W/m²"),
            ("w/m2", "W/m²"),
            ("W / m2", "W/m²"),
            ("W / m^2", "W/m²"),
            ("watt/m2", "W/m²"),
            ("watts/m2", "W/m²"),
            ("kW/m2", "kW/m²"),
            ("kW/m^2", "kW/m²"),
            ("kw/m²", "kW/m²"),
            ("kw/m2", "kW/m²"),
            ("W", "W"),
            ("w", "W"),
            ("watt", "W"),
            ("watts", "W"),
            ("kW", "kW"),
            ("kw", "kW"),
            ("KW", "kW"),
            ("kilowatt", "kW"),
            ("kilowatts", "kW"),
            ("MW", "MW"),
            ("mw", "MW"),
            ("megawatt", "MW"),
            ("Wh", "Wh"),
            ("wh", "Wh"),
            ("watt-hour", "Wh"),
            ("watthour", "Wh"),
            ("kWh", "kWh"),
            ("kwh", "kWh"),
            ("kilowatt-hour", "kWh"),
            ("kilowatthour", "kWh"),
            ("MWh", "MWh"),
            ("mwh", "MWh"),
            ("megawatt-hour", "MWh"),
            ("degC", "degC"),
            ("deg_c", "degC"),
            ("°C", "degC"),
            ("°c", "degC"),
            ("C", "degC"),
            ("c", "degC"),
            ("celsius", "degC"),
            ("centigrade", "degC"),
            ("degF", "degF"),
            ("deg_f", "degF"),
            ("°F", "degF"),
            ("°f", "degF"),
            ("F", "degF"),
            ("f", "degF"),
            ("fahrenheit", "degF"),
            ("K", "K"),
            ("k", "K"),
            ("kelvin", "K"),
        ],
    )
    def test_normalize_aliases(self, raw: str, expected: str) -> None:
        assert normalize_unit(raw) == expected

    def test_unknown_unit_raises_error(self) -> None:
        with pytest.raises(UnknownConversionError) as exc_info:
            normalize_unit("unobtainium")
        assert "Unrecognized unit 'unobtainium'" in str(exc_info.value)
        assert exc_info.value.from_unit == "unobtainium"

    def test_empty_unit_raises_error(self) -> None:
        with pytest.raises(UnknownConversionError):
            normalize_unit("   ")


class TestRequiredConversions:
    """Test minimum required conversion callables specified in task requirements."""

    def test_kW_to_W(self) -> None:
        # kW -> W (1.5 kW = 1500 W)
        assert convert(1.5, "kW", "W") == pytest.approx(1500.0)
        assert convert(0.0, "kW", "W") == pytest.approx(0.0)
        assert convert(1250, "kW", "W") == pytest.approx(1_250_000.0)

    def test_MW_to_W(self) -> None:
        # MW -> W (2.5 MW = 2,500,000 W)
        assert convert(2.5, "MW", "W") == pytest.approx(2_500_000.0)
        assert convert(0.05, "MW", "W") == pytest.approx(50_000.0)

    def test_MWh_to_kWh(self) -> None:
        # MWh -> kWh (1.25 MWh = 1250 kWh)
        assert convert(1.25, "MWh", "kWh") == pytest.approx(1250.0)

    def test_Wh_to_kWh(self) -> None:
        # Wh -> kWh (5000 Wh = 5 kWh)
        assert convert(5000.0, "Wh", "kWh") == pytest.approx(5.0)

    def test_kWm2_to_Wm2(self) -> None:
        # kW/m² -> W/m² (1.2217 kW/m² = 1221.7 W/m²)
        assert convert(1.2217, "kW/m²", "W/m²") == pytest.approx(1221.7)
        # Using alias
        assert convert(1.0, "kw/m2", "w/m2") == pytest.approx(1000.0)

    def test_Wm2_to_Wm2_identity(self) -> None:
        # W/m² -> W/m² (identity)
        assert convert(850.5, "W/m²", "W/m²") == pytest.approx(850.5)
        assert convert(850.5, "w/m2", "W/m^2") == pytest.approx(850.5)

    def test_degF_to_degC(self) -> None:
        # °F -> °C (32°F = 0°C, 212°F = 100°C, -40°F = -40°C)
        assert convert(32.0, "°F", "°C") == pytest.approx(0.0)
        assert convert(212.0, "degF", "degC") == pytest.approx(100.0)
        assert convert(-40.0, "F", "C") == pytest.approx(-40.0)
        assert convert(77.0, "fahrenheit", "celsius") == pytest.approx(25.0)

    def test_K_to_degC(self) -> None:
        # K -> °C (273.15 K = 0°C, 373.15 K = 100°C)
        assert convert(273.15, "K", "°C") == pytest.approx(0.0)
        assert convert(373.15, "kelvin", "celsius") == pytest.approx(100.0)
        assert convert(298.15, "k", "degC") == pytest.approx(25.0)


class TestInversesAndCrossConversions:
    """Test inverse and transitive conversions within physical dimensions."""

    def test_power_roundtrip(self) -> None:
        val = 1420.5
        w_val = convert(val, "kW", "W")
        assert convert(w_val, "W", "kW") == pytest.approx(val)

        mw_val = convert(val, "kW", "MW")
        assert convert(mw_val, "MW", "kW") == pytest.approx(val)

    def test_energy_roundtrip(self) -> None:
        val = 5754.0  # kWh
        wh_val = convert(val, "kWh", "Wh")
        assert convert(wh_val, "Wh", "kWh") == pytest.approx(val)

        mwh_val = convert(val, "kWh", "MWh")
        assert convert(mwh_val, "MWh", "kWh") == pytest.approx(val)

    def test_irradiance_roundtrip(self) -> None:
        val = 950.0  # W/m²
        kwm2 = convert(val, "W/m²", "kW/m²")
        assert convert(kwm2, "kW/m²", "W/m²") == pytest.approx(val)

    def test_temperature_roundtrip(self) -> None:
        c_val = 35.5
        f_val = convert(c_val, "degC", "degF")
        assert convert(f_val, "degF", "degC") == pytest.approx(c_val)

        k_val = convert(c_val, "degC", "K")
        assert convert(k_val, "K", "degC") == pytest.approx(c_val)

        # F to K direct
        f_to_k = convert(77.0, "degF", "K")
        assert f_to_k == pytest.approx(298.15)


class TestVectorizedPolarsOperations:
    """Test vectorized convert function on Polars Series."""

    def test_polars_series_numeric_conversion(self) -> None:
        s = pl.Series("raw_kw", [100.0, 250.0, 1250.0])
        res = convert(s, "kW", "W")

        assert isinstance(res, pl.Series)
        assert res.name == "raw_kw"
        assert res.to_list() == [100_000.0, 250_000.0, 1_250_000.0]

    def test_polars_series_preserves_nulls(self) -> None:
        s = pl.Series("irradiance_kw", [0.0, 0.5, None, 1.2])
        res = convert(s, "kW/m²", "W/m²")

        assert isinstance(res, pl.Series)
        assert res.name == "irradiance_kw"
        assert res.null_count() == 1
        expected = [0.0, 500.0, None, 1200.0]
        for actual_val, exp_val in zip(res.to_list(), expected):
            if exp_val is None:
                assert actual_val is None
            else:
                assert actual_val == pytest.approx(exp_val)

    def test_polars_series_temperature_conversion(self) -> None:
        s = pl.Series("ambient_f", [32.0, 68.0, 212.0, None])
        res = convert(s, "degF", "degC")

        assert isinstance(res, pl.Series)
        assert res.name == "ambient_f"
        assert res[0] == pytest.approx(0.0)
        assert res[1] == pytest.approx(20.0)
        assert res[2] == pytest.approx(100.0)
        assert res[3] is None

    def test_polars_series_empty(self) -> None:
        s = pl.Series("empty", [], dtype=pl.Float64)
        res = convert(s, "kW", "W")
        assert isinstance(res, pl.Series)
        assert len(res) == 0
        assert res.name == "empty"


class TestExceptionHandling:
    """Test UnknownConversionError and TypeError paths."""

    def test_incompatible_dimensions_raises_error(self) -> None:
        # Converting Power to Temperature
        with pytest.raises(UnknownConversionError) as exc_info:
            convert(100.0, "kW", "degC")
        assert "Incompatible physical dimensions" in str(exc_info.value)
        assert exc_info.value.from_unit == "kW"
        assert exc_info.value.to_unit == "degC"

        # Converting Energy to Irradiance
        with pytest.raises(UnknownConversionError) as exc_info2:
            convert(100.0, "kWh", "W/m²")
        assert "Incompatible physical dimensions" in str(exc_info2.value)

    def test_unknown_source_unit_raises_error(self) -> None:
        with pytest.raises(UnknownConversionError) as exc_info:
            convert(50.0, "horsepower", "W")
        assert "Unrecognized unit 'horsepower'" in str(exc_info.value)

    def test_unknown_target_unit_raises_error(self) -> None:
        with pytest.raises(UnknownConversionError) as exc_info:
            convert(50.0, "kW", "lightyears")
        assert "Unrecognized unit 'lightyears'" in str(exc_info.value)

    def test_unsupported_value_type_raises_type_error(self) -> None:
        with pytest.raises(TypeError) as exc_info:
            convert("100", "kW", "W")  # type: ignore[call-overload]
        assert "Unsupported value type 'str'" in str(exc_info.value)
