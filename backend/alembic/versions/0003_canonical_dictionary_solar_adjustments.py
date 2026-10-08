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
    """Apply migration: add canonical table if needed, seed solar keys, deactivate wind keys."""
    # Define table reflection for canonical_signals
    canonical_signals = sa.table(
        "canonical_signals",
        sa.column("signal_key", sa.String(64)),
        sa.column("display_name", sa.String(128)),
        sa.column("category", sa.String(32)),
        sa.column("unit", sa.String(32)),
        sa.column("data_type", sa.String(32)),
        sa.column("monotonicity", sa.String(32)),
        sa.column("bound_min_rule", sa.String(128)),
        sa.column("bound_max_rule", sa.String(128)),
        sa.column("is_active", sa.Boolean()),
        sa.column("description", sa.Text()),
    )

    # 1. Upsert / Insert solar signal definitions
    for sig in SOLAR_SIGNALS:
        # Check if row exists, update if exists, insert if missing
        stmt = sa.text("""
            INSERT INTO canonical_signals (
                signal_key, display_name, category, unit, data_type, 
                monotonicity, bound_min_rule, bound_max_rule, is_active, description
            ) VALUES (
                :signal_key, :display_name, :category, :unit, :data_type,
                :monotonicity, :bound_min_rule, :bound_max_rule, :is_active, :description
            )
            ON CONFLICT (signal_key) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                category = EXCLUDED.category,
                unit = EXCLUDED.unit,
                data_type = EXCLUDED.data_type,
                monotonicity = EXCLUDED.monotonicity,
                bound_min_rule = EXCLUDED.bound_min_rule,
                bound_max_rule = EXCLUDED.bound_max_rule,
                is_active = EXCLUDED.is_active,
                description = EXCLUDED.description;
        """)
        op.execute(stmt.bindparams(**sig))

    # 2. Deactivate wind-pack keys for Solar MVP
    for w_key in WIND_KEYS:
        op.execute(
            sa.text("""
                UPDATE canonical_signals 
                SET is_active = FALSE 
                WHERE signal_key = :w_key;
            """).bindparams(w_key=w_key)
        )


def downgrade() -> None:
    """Revert migration: restore wind keys and remove specific solar refinements."""
    # Re-enable wind keys if needed
    for w_key in WIND_KEYS:
        op.execute(
            sa.text("""
                UPDATE canonical_signals 
                SET is_active = TRUE 
                WHERE signal_key = :w_key;
            """).bindparams(w_key=w_key)
        )

    # Remove added specific yield keys if rolling back to 0002
    op.execute("""
        DELETE FROM canonical_signals 
        WHERE signal_key IN ('energy_ac_daily', 'energy_ac_total', 'irradiance_poa');
    """)
