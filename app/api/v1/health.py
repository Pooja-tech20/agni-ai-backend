from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.schemas.health import DBTestResponse, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check():
    """Basic liveness check — no DB dependency, always fast."""
    return HealthResponse(
        status="ok",
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
    )


@router.get("/health/db", response_model=DBTestResponse)
def health_check_db(db: Session = Depends(get_db)):
    """Confirms FastAPI can actually read/write against Postgres."""
    db.execute(text("SELECT 1"))
    return DBTestResponse(status="ok", detail="Database connection successful")
