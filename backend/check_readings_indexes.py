from sqlalchemy import text
from app.db.database import engine

with engine.connect() as conn:
    result = conn.execute(
        text("""
            SELECT
                indexname,
                indexdef
            FROM pg_indexes
            WHERE tablename = 'readings'
            ORDER BY indexname
        """)
    )

    print("Readings indexes:")
    for row in result:
        print(row)
