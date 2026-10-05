from sqlalchemy import text
from app.db.database import engine

with engine.begin() as conn:
    conn.execute(
        text("""
            SELECT create_hypertable(
                'readings',
                'ts',
                if_not_exists => TRUE
            )
        """)
    )

print("Readings hypertable created successfully.")
