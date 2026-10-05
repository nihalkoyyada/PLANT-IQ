from sqlalchemy import text

from app.db.database import engine


with engine.connect() as conn:
    table_name = conn.execute(
        text("SELECT to_regclass('public.files')")
    ).scalar()

    row_count = conn.execute(
        text("SELECT COUNT(*) FROM files")
    ).scalar()

    print("Files table:", table_name)
    print("Files row count:", row_count)