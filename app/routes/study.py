import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_async_conn
from app.services.storage import StorageService
from app.services.study import StudyService

router = APIRouter(prefix="/api", tags=["study"])


class QuizRequest(BaseModel):
    num_questions: int = 10


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _get_best_notes(conn, session_id: int) -> tuple[str, str]:
    """Return (notes_text, data_dir) using the best available notes file.

    Priority: polished.md > merged.md > live_draft.md
    """
    row = await conn.execute(
        "SELECT data_dir FROM sessions WHERE id = ?", (session_id,)
    )
    session = await row.fetchone()
    if not session:
        raise HTTPException(
            status_code=404, detail=f"Session {session_id} not found"
        )
    data_dir = session["data_dir"]
    notes_dir = os.path.join(data_dir, "notes")
    for name in ("polished.md", "merged.md", "live_draft.md"):
        path = os.path.join(notes_dir, name)
        if os.path.exists(path):
            return StorageService.read_text(path), data_dir
    raise HTTPException(
        status_code=400, detail="No notes available for this session."
    )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.post("/sessions/{session_id}/study/guide")
async def generate_study_guide(session_id: int) -> dict:
    """Generate a study guide from the session's best available notes."""
    conn = await get_async_conn()
    try:
        notes, data_dir = await _get_best_notes(conn, session_id)

        study_svc = StudyService()
        guide_md = await study_svc.generate_study_guide(notes)

        study_dir = os.path.join(data_dir, "study")
        os.makedirs(study_dir, exist_ok=True)
        StorageService.write_text(os.path.join(study_dir, "guide.md"), guide_md)

        return {"session_id": session_id, "status": "generated", "guide": guide_md}
    finally:
        await conn.close()


@router.post("/sessions/{session_id}/study/quiz")
async def generate_quiz(session_id: int, body: QuizRequest) -> dict:
    """Generate a multiple-choice quiz from the session's best available notes."""
    conn = await get_async_conn()
    try:
        notes, data_dir = await _get_best_notes(conn, session_id)

        study_svc = StudyService()
        questions = await study_svc.generate_quiz(notes, body.num_questions)

        study_dir = os.path.join(data_dir, "study")
        os.makedirs(study_dir, exist_ok=True)
        StorageService.write_json(
            os.path.join(study_dir, "quiz.json"), questions
        )

        return {
            "session_id": session_id,
            "status": "generated",
            "questions": questions,
        }
    finally:
        await conn.close()
