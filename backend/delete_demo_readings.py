from sqlalchemy import text
from app.db.database import engine

q = text("DELETE FROM readings WHERE ingestion_job_id IS NULL")

with engine.begin() as conn:
    result = conn.execute(q)

print("Deleted demo readings:", result.rowcount)
