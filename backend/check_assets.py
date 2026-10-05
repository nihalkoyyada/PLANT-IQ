from sqlalchemy import text
from app.db.database import engine

with engine.connect() as conn:
    result = conn.execute(
        text("""
            SELECT
                id,
                plant_id,
                name,
                asset_type,
                make,
                model,
                rated_kw
            FROM assets
            ORDER BY name
        """)
    )

    print("Assets:")
    for row in result.fetchall():
        print(row)
