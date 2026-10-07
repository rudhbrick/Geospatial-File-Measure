from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  (registers tables with SQLAlchemy)
from app.api import files
from app.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Geospatial File Measurement API", lifespan=lifespan)
app.include_router(files.router)


@app.get("/health")
def health():
    return {"status": "ok"}