from sqlalchemy import text
from app.db.database import engine

query = text("""
INSERT INTO mapping_templates
    (org_id, name, source_signature, mappings)
VALUES
    (
        :org_id,
        :name,
        :source_signature,
        CAST(:mappings AS jsonb)
    )
RETURNING id, name, source_signature, mappings
""")

params = {
    "org_id": "2ed55e3d-80a4-476c-8bf0-3fa455bd6a68",
    "name": "Kaggle Solar Generation Mapping",
    "source_signature": "kaggle_solar_generation_v1",
    "mappings": '{"timestamp":"DATE_TIME","source_key":"SOURCE_KEY","power_dc":"DC_POWER","power_ac":"AC_POWER","daily_yield":"DAILY_YIELD","total_yield":"TOTAL_YIELD"}',
}

with engine.begin() as conn:
    row = conn.execute(query, params).fetchone()
    print("INSERTED:")
    print(row)
