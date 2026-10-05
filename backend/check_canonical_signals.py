from sqlalchemy import select

from app.db.database import SessionLocal
from app.models import CanonicalSignal


db = SessionLocal()

try:
    result = db.execute(
        select(
            CanonicalSignal.key,
            CanonicalSignal.name,
            CanonicalSignal.category,
            CanonicalSignal.unit,
            CanonicalSignal.applicable_types,
        ).order_by(CanonicalSignal.key)
    )

    print("Canonical Signals:")

    for row in result.all():
        print(row)

finally:
    db.close()
