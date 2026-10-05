from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.db.database import engine

try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("Database connection: OK")
        print("Result:", result.scalar())
except Exception as e:
    print("Database connection failed:")
    print(type(e).__name__)
    print(e)
