from sqlalchemy import text
from app.db.database import engine

with engine.connect() as conn:
    result = conn.execute(
        text("""
            SELECT channel_id, ts, COUNT(*) AS count
            FROM readings
            GROUP BY channel_id, ts
            HAVING COUNT(*) > 1
        """)
    )

    rows = result.fetchall()

    if rows:
        print("Duplicate readings found:")
        for row in rows:
            print(row)
    else:
        print("No duplicate readings found.")
