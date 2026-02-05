from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routes import notes, recording, sessions, slides, study


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create SQLite tables on startup. Nothing to tear down on shutdown
    (RecordingWorker threads are daemon threads)."""
    await init_db()
    yield


app = FastAPI(
    title="note-gen",
    description="Offline lecture note generation with Whisper and LLM-powered study tools",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(sessions.router)
app.include_router(recording.router)
app.include_router(slides.router)
app.include_router(notes.router)
app.include_router(study.router)
