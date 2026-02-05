from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_async_conn
from app.services.storage import StorageService

router = APIRouter(prefix="/api", tags=["sessions"])


# ------------------------------------------------------------------
# Request bodies
# ------------------------------------------------------------------


class CourseCreate(BaseModel):
    name: str


class SessionCreate(BaseModel):
    course_id: int
    session_number: int


# ------------------------------------------------------------------
# Course endpoints
# ------------------------------------------------------------------


@router.post("/courses")
async def create_course(body: CourseCreate) -> dict:
    conn = await get_async_conn()
    try:
        cursor = await conn.execute(
            "INSERT INTO courses (name) VALUES (?)", (body.name,)
        )
        await conn.commit()
        row = await conn.execute(
            "SELECT * FROM courses WHERE id = ?", (cursor.lastrowid,)
        )
        course = await row.fetchone()
        return dict(course)
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(
                status_code=409, detail=f"Course '{body.name}' already exists"
            )
        raise
    finally:
        await conn.close()


@router.get("/courses")
async def list_courses() -> list[dict]:
    conn = await get_async_conn()
    try:
        rows = await conn.execute("SELECT * FROM courses ORDER BY created_at DESC")
        return [dict(row) for row in await rows.fetchall()]
    finally:
        await conn.close()


# ------------------------------------------------------------------
# Session endpoints
# ------------------------------------------------------------------


@router.post("/sessions")
async def create_session(body: SessionCreate) -> dict:
    conn = await get_async_conn()
    print(body)
    try:
        # Verify course exists
        row = await conn.execute(
            "SELECT name FROM courses WHERE id = ?", (body.course_id,)
        )
        course = await row.fetchone()
        if not course:
            raise HTTPException(
                status_code=404, detail=f"Course {body.course_id} not found"
            )

        course_name = course["name"]
        session_name = f"session_{body.session_number:02d}"
        data_dir = StorageService.session_dir(course_name, session_name)
        StorageService.ensure_dirs(data_dir)

        cursor = await conn.execute(
            "INSERT INTO sessions (course_id, session_number, status, data_dir) "
            "VALUES (?, ?, 'idle', ?)",
            (body.course_id, body.session_number, data_dir),
        )
        await conn.commit()
        row = await conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (cursor.lastrowid,)
        )
        session = await row.fetchone()
        return dict(session)
    except HTTPException:
        raise
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Session {body.session_number} already exists "
                    f"for course {body.course_id}"
                ),
            )
        raise
    finally:
        await conn.close()


@router.get("/sessions/{session_id}")
async def get_session(session_id: int) -> dict:
    conn = await get_async_conn()
    try:
        row = await conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        session = await row.fetchone()
        if not session:
            raise HTTPException(
                status_code=404, detail=f"Session {session_id} not found"
            )
        return dict(session)
    finally:
        await conn.close()


@router.get("/sessions")
async def list_sessions(course_id: int | None = None) -> list[dict]:
    conn = await get_async_conn()
    try:
        if course_id is not None:
            rows = await conn.execute(
                "SELECT * FROM sessions WHERE course_id = ? ORDER BY session_number",
                (course_id,),
            )
        else:
            rows = await conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            )
        return [dict(row) for row in await rows.fetchall()]
    finally:
        await conn.close()
