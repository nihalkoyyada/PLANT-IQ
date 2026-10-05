from sqlalchemy import text
from app.db.database import engine

with engine.connect() as conn:
    result = conn.execute(
        text("SELECT id, name, created_at FROM organizations ORDER BY created_at DESC")
    )

    print("Organizations:")
    for row in result:
        print(row)
