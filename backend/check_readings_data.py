from sqlalchemy import text
from app.db.database import engine

with engine.connect() as conn:
    result = conn.execute(
        text("""
            SELECT channel_id, ts, value, quality, ingestion_job_id
            FROM readings
            ORDER BY ts DESC
        """)
    )

    print("Readings:")
    for row in result:
        print(row)
