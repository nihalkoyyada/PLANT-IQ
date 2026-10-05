from sqlalchemy import text
from app.db.database import engine

query = text("""
SELECT id, name, asset_type, metadata
FROM assets
WHERE metadata->>'source_key' IS NOT NULL
ORDER BY name
""")

with engine.connect() as conn:
    rows = conn.execute(query).all()

print("Assets with SOURCE_KEY:", len(rows))

for row in rows:
    print(row)
