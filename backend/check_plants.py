from sqlalchemy import text
from app.db.database import engine

with engine.connect() as conn:
    result = conn.execute(
        text("SELECT id, org_id, name, plant_type, metadata FROM plants ORDER BY created_at DESC")
    )

    print("Plants:")
    for row in result.fetchall():
        print(row)
