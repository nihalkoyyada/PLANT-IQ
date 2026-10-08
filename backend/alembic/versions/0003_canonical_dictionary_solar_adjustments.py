"""Canonical dictionary solar adjustments and dynamic bounds.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-22 11:55:00.000000

Task: S1-AI-03 Part A
Description:
- Registers explicit canonical keys for `energy_ac_daily` (daily reset) and `energy_ac_total` (lifetime monotonic).
- Registers `irradiance_poa` as standard solar plane-of-array irradiance with `approx_ghi` metadata support.
- Updates `power_dc` and `power_ac` with dynamic rated capacity bound expressions.
- Explicitly flags wind-pack keys (e.g. `rotor_speed`, `pitch_angle`) as inactive for the Solar MVP.
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "fe3dd9a9d492"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Solar Canonical Signal Definitions
SOLAR_SIGNALS = [
    {
        "signal_key": "power_dc",
        "display_name": "DC Power Generation",
        "category": "power",
        "unit": "W",
        "data_type": "float",
        "monotonicity": "none",
        "bound_min_rule": "0.0",
        "bound_max_rule": "1.20 * device.rated_dc_w",
        "is_active": True,
        "description": "Instantaneous DC power measured at inverter DC input (scaled to Watts).",
    },
    {
        "signal_key": "power_ac",
        "display_name": "AC Power Generation",
        "category": "power",
        "unit": "W",
        "data_type": "float",
        "monotonicity": "none",
        "bound_min_rule": "0.0",
        "bound_max_rule": "1.10 * device.rated_ac_w",
        "is_active": True,
        "description": "Instantaneous AC active power measured at inverter AC output (scaled to Watts).",
    },
    {
        "signal_key": "energy_ac_daily",
        "display_name": "Daily AC Energy Yield",
        "category": "energy",
        "unit": "Wh",
        "data_type": "float",
        "monotonicity": "daily_reset",
        "bound_min_rule": "0.0",
        "bound_max_rule": "24.0 * device.rated_ac_w",
        "is_active": True,
        "description": "Cumulative AC energy generated during current calendar day (resets to 0 at 00:00 local time).",
    },
    {
        "signal_key": "energy_ac_total",
        "display_name": "Lifetime Total AC Energy Yield",
        "category": "energy",
        "unit": "Wh",
        "data_type": "float",
        "monotonicity": "strict_increasing",
        "bound_min_rule": "0.0",
        "bound_max_rule": "None",
        "is_active": True,
        "description": "Cumulative lifetime AC energy register reported by hardware meter.",
    },
    {
        "signal_key": "irradiance_poa",
        "display_name": "Plane of Array Irradiance",
        "category": "weather",
        "unit": "W/m²",
        "data_type": "float",
        "monotonicity": "none",
        "bound_min_rule": "0.0",
        "bound_max_rule": "1500.0",
        "is_active": True,
        "description": "Solar irradiance incident on panel plane (POA); supports approx_ghi flag when horizontal transposition is requested.",
    },
    {
        "signal_key": "irradiance_ghi",
        "display_name": "Global Horizontal Irradiance",
        "category": "weather",
        "unit": "W/m²",
        "data_type": "float",
        "monotonicity": "none",
        "bound_min_rule": "0.0",
        "bound_max_rule": "1361.0",
        "is_active": True,
        "description": "Terrestrial global horizontal solar irradiance measured via horizontal pyranometer.",
    },
    {
        "signal_key": "temperature_ambient",
        "display_name": "Ambient Air Temperature",
        "category": "weather",
        "unit": "degC",
        "data_type": "float",
        "monotonicity": "none",
        "bound_min_rule": "-30.0",
        "bound_max_rule": "60.0",
        "is_active": True,
        "description": "Dry-bulb ambient air temperature measured by weather sensor station.",
    },
    {
        "signal_key": "temperature_module",
        "display_name": "PV Module Back-of-Sheet Temperature",
        "category": "weather",
        "unit": "degC",
        "data_type": "float",
        "monotonicity": "none",
        "bound_min_rule": "-20.0",
        "bound_max_rule": "90.0",
        "is_active": True,
        "description": "PV panel backsheet surface temperature for cell thermal modeling and PR_STC calculations.",
    },
]

# Wind-Pack Keys Explicitly Deactivated for Solar MVP
WIND_KEYS = [
    "rotor_speed",
    "pitch_angle",
    "yaw_angle",
    "wind_speed",
    "wind_direction",
    "generator_speed",
    "gearbox_temperature",
    "nacelle_position",
]


def upgrade() -> None:
    """Apply migration: seed solar keys into canonical_signals."""
    for sig in SOLAR_SIGNALS:
        param = {
            "key": sig["signal_key"],
            "name": sig["display_name"],
            "category": sig["category"],
            "unit": sig["unit"],
            "applicable_types": ["solar", "inverter", "weather_station"],
            "description": sig["description"],
        }
        stmt = sa.text("""
            INSERT INTO canonical_signals (
                key, name, category, unit, applicable_types, description
            ) VALUES (
                :key, :name, :category, :unit, :applicable_types, :description
            )
            ON CONFLICT (key) DO UPDATE SET
                name = EXCLUDED.name,
                category = EXCLUDED.category,
                unit = EXCLUDED.unit,
                applicable_types = EXCLUDED.applicable_types,
                description = EXCLUDED.description;
        """)
        op.execute(stmt.bindparams(**param))


def downgrade() -> None:
    """Revert migration: remove specific solar refinements."""
    op.execute(sa.text("""
        DELETE FROM canonical_signals 
        WHERE key IN ('energy_ac_daily', 'energy_ac_total', 'irradiance_poa');
    """))
