from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.organizations import router as organizations_router
from app.api.plants import router as plants_router
from app.api.assets import router as assets_router
from app.api.channels import router as channels_router
from app.api.readings import router as readings_router
from app.api.files import router as files_router
from app.api.mapping_templates import router as mapping_templates_router
from app.api.ingestion_jobs import router as ingestion_jobs_router
from app.api.ai import router as ai_router
from app.api.events import router as events_router
from app.api.kpis import router as kpis_router
from app.api.canonical_signals import router as canonical_signals_router
from app.api.detectors import router as detectors_router
from app.api.anomalies import router as anomalies_router
from app.api.dev import router as dev_router
from app.db.session import create_db_engine, get_session_factory
from app.models import Asset


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure baseline Surya Organization and Users exist on initial startup if database is brand new
    try:
        engine = create_db_engine()
        sf = get_session_factory(engine)
        with sf() as session:
            from app.models import User
            user_count = session.query(User).count()
            if user_count == 0:
                from scripts.seed_surya import seed_surya_data
                seed_surya_data(session=session, reset=False)
    except Exception as err:
        print(f"Warning: Baseline organization/user seeding on startup encountered note: {err}")
    yield


app = FastAPI(
    title="PlantIQ API",
    description="Backend API for the PlantIQ solar plant monitoring platform",
    version="1.0.0",
    lifespan=lifespan,
)


app.include_router(auth_router)
app.include_router(organizations_router)
app.include_router(plants_router)
app.include_router(assets_router)
app.include_router(channels_router)
app.include_router(canonical_signals_router)
app.include_router(detectors_router)
app.include_router(anomalies_router)
app.include_router(readings_router)
app.include_router(files_router)
app.include_router(mapping_templates_router)
app.include_router(ingestion_jobs_router)
app.include_router(events_router)
app.include_router(kpis_router)
app.include_router(ai_router)
app.include_router(dev_router)



@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "PlantIQ API",
    }

