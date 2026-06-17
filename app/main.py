from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import logging
import os

from app.database import engine, Base
from app.models import Monitor
from app.scheduler import start_scheduler, stop_scheduler, add_monitor_job
from app.routers import monitors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    start_scheduler()

    # Re-schedule any active monitors that survived a restart
    from app.database import SessionLocal
    from app.models import Monitor as MonitorModel
    db = SessionLocal()
    try:
        active = db.query(MonitorModel).filter(
            MonitorModel.is_active == True,
            MonitorModel.got_it == False,
        ).all()
        for m in active:
            add_monitor_job(m.id, m.check_interval)
        logger.info("Re-scheduled %d active monitors on startup", len(active))
    finally:
        db.close()

    yield

    # Shutdown
    stop_scheduler()


app = FastAPI(title="StockSentinel", lifespan=lifespan)

app.include_router(monitors.router)

# Serve static frontend
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
def health():
    return {"status": "ok"}
