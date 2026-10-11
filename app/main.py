"""Application entry point. Run with: uvicorn app.main:app --reload"""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.routes import router
from app.services import resume_unfinished_jobs

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    # Pick up jobs that were cut off by a previous shutdown, without delaying startup.
    threading.Thread(target=resume_unfinished_jobs, daemon=True).start()
    yield


app = FastAPI(
    title="Bulk Certificate Generator",
    description="Submit a list of recipients, track the job, download the generated certificates.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
