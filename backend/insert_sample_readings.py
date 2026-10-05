from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from app.db.database import engine


CHANNEL_ID = "1d6fcee3-3ff2-4f3a-b4cd-1429a90d3771"


readings = [
    (datetime(2026, 9, 23, 11, 50, tzinfo=timezone(timedelta(hours=5, minutes=30))), 128.7),
    (datetime(2026, 9, 23, 11, 55, tzinfo=timezone(timedelta(hours=5, minutes=30))), 131.2),
    (datetime(2026, 9, 23, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))), 135.8),
    (datetime(2026, 9, 23, 12, 5, tzinfo=timezone(timedelta(hours=5, minutes=30))), 139.1),
]


with engine.begin() as conn:
    for ts, value in readings:
        conn.execute(
            text("""
                INSERT INTO readings
                    (channel_id, ts, value, quality, ingestion_job_id)
                VALUES
                    (:channel_id, :ts, :value, :quality, :ingestion_job_id)
            """),
            {
                "channel_id": CHANNEL_ID,
                "ts": ts,
                "value": value,
                "quality": 0,
                "ingestion_job_id": None,
            },
        )

print("Multiple readings inserted successfully.")
