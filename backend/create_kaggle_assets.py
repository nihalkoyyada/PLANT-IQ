from sqlalchemy import text
from app.db.database import engine

PLANT_ID = "064eb65e-30fb-4a9a-aa8b-1d5ab04a1e2b"

SOURCE_KEYS = [
    "1BY6WEcLGh8j5v7",
    "1IF53ai7Xc0U56Y",
    "3PZuoBAID5Wc2HD",
    "7JYdWkrLSPkdwr4",
    "McdE0feGgRqW7Ca",
    "VHMLBKoKgIrUVDU",
    "WRmjgnKYAwPKWDb",
    "YxYtjZvoooNbGkE",
    "ZnxXDlPa8U1GXgE",
    "ZoEaEvLYb1n2sOq",
    "adLQvlD726eNBSB",
    "bvBOhCH3iADSZry",
    "iCRJl6heRkivqQ3",
    "ih0vzX44oOqAx2f",
    "pkci93gMrogZuBj",
    "rGa61gmuvPhdLxV",
    "sjndEbLyjtCKgGv",
    "uHbuxQJl8lW7ozc",
    "wCURE6d3bPkepu2",
    "z9Y9gH1T5YWrNuG",
    "zBIq5rxdHJRwDNY",
    "zVJPv84UY57bAof",
]

with engine.begin() as conn:

    for index, source_key in enumerate(SOURCE_KEYS, start=1):

        asset_name = f"Inverter {index:02d}"

        existing = conn.execute(
            text("""
                SELECT id
                FROM assets
                WHERE plant_id = :plant_id
                  AND name = :name
            """),
            {
                "plant_id": PLANT_ID,
                "name": asset_name,
            },
        ).fetchone()

        if existing:
            asset_id = existing[0]

            conn.execute(
                text("""
                    UPDATE assets
                    SET metadata = metadata || CAST(:metadata AS jsonb)
                    WHERE id = :asset_id
                """),
                {
                    "asset_id": asset_id,
                    "metadata": (
                        '{"source_key":"' + source_key + '",'
                        '"source":"kaggle_solar_generation"}'
                    ),
                },
            )

            print(f"Updated {asset_name} -> {source_key}")

        else:
            row = conn.execute(
                text("""
                    INSERT INTO assets
                        (
                            plant_id,
                            name,
                            asset_type,
                            metadata
                        )
                    VALUES
                        (
                            :plant_id,
                            :name,
                            'inverter',
                            CAST(:metadata AS jsonb)
                        )
                    RETURNING id
                """),
                {
                    "plant_id": PLANT_ID,
                    "name": asset_name,
                    "metadata": (
                        '{"source_key":"' + source_key + '",'
                        '"source":"kaggle_solar_generation"}'
                    ),
                },
            ).fetchone()

            asset_id = row[0]

            print(f"Created {asset_name} -> {source_key}")

        channel_exists = conn.execute(
            text("""
                SELECT id
                FROM channels
                WHERE asset_id = :asset_id
                  AND canonical_key = 'power_ac'
                  AND source_name = 'AC Power'
            """),
            {
                "asset_id": asset_id,
            },
        ).fetchone()

        if channel_exists:
            print(f"  AC Power channel already exists")
        else:
            conn.execute(
                text("""
                    INSERT INTO channels
                        (
                            asset_id,
                            canonical_key,
                            source_name,
                            receive_unit,
                            conversion,
                            interval_s,
                            agg_semantics
                        )
                    VALUES
                        (
                            :asset_id,
                            'power_ac',
                            'AC Power',
                            'kW',
                            NULL,
                            300,
                            'avg'
                        )
                """),
                {
                    "asset_id": asset_id,
                },
            )

            print(f"  Created AC Power channel")

print("")
print("SOURCE_KEY asset/channel mapping completed.")
print("Total SOURCE_KEYs:", len(SOURCE_KEYS))
