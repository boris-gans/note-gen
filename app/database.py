import sqlite3

import aiosqlite

DB_PATH = "note_gen.db"

CREATE_COURSES = """
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    session_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    data_dir TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (course_id) REFERENCES courses(id),
    UNIQUE(course_id, session_number)
)
"""

CREATE_TRANSCRIPT_CHUNKS = """
CREATE TABLE IF NOT EXISTS transcript_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    text TEXT NOT NULL,
    confidence REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
)
"""

CREATE_SLIDE_OUTLINES = """
CREATE TABLE IF NOT EXISTS slide_outlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    outline_json TEXT NOT NULL DEFAULT '[]',
    images_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
)
"""

_DDL = [CREATE_COURSES, CREATE_SESSIONS, CREATE_TRANSCRIPT_CHUNKS, CREATE_SLIDE_OUTLINES]


async def init_db() -> None:
    """Create all tables. Called once at server startup via FastAPI lifespan."""
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in _DDL:
            await db.execute(stmt)
        await db.commit()


def get_sync_conn() -> sqlite3.Connection:
    """Synchronous connection for use in worker threads (RecordingWorker)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


async def get_async_conn() -> aiosqlite.Connection:
    """Async connection for use in FastAPI route handlers."""
    conn = await aiosqlite.connect(DB_PATH)
    await conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = aiosqlite.Row
    return conn
