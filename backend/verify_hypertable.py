from sqlalchemy import text
from app.db.database import engine

with engine.connect() as conn:
    result = conn.execute(
        text("""
            SELECT hypertable_name, num_dimensions
            FROM timescaledb_information.hypertables
            WHERE hypertable_name = 'readings'
        """)
    )
    print("Hypertable:", result.fetchall())
