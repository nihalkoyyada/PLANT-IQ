import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL is not configured")

engine = create_engine(database_url)

with engine.connect() as connection:
    result = connection.execute(
        text("SELECT current_user, current_database();")
    )

    row = result.fetchone()

    print(f"Database user: {row[0]}")
    print(f"Database name: {row[1]}")