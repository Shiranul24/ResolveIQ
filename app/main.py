"""ResolveIQ - AI-assisted IT service desk API."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import triage
from app.database import Base, engine, get_db
from app.routers import analytics, auth, tickets


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    triage.get_model()  # load/train once at startup so the first request is not slow
    yield


app = FastAPI(
    title="ResolveIQ",
    description="AI-assisted IT service desk: auto-triaged tickets, role-based workflows and SLA tracking.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(analytics.router)


@app.get("/health", tags=["ops"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Liveness + database connectivity check (used by Docker and load balancers)."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


# The dashboard is a static single page served by the same app (mounted last so /api wins).
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="dashboard")
