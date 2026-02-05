import json
import os

from fastapi import APIRouter, HTTPException

from app.database import get_async_conn
from app.services.notes import NotesService
from app.services.storage import StorageService

router = APIRouter(prefix="/api", tags=["notes"])


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _get_session_or_404(conn, session_id: int) -> dict:
    row = await conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    )
    session = await row.fetchone()
    if not session:
        raise HTTPException(
            status_code=404, detail=f"Session {session_id} not found"
        )
    return dict(session)


async def _get_chunks(conn, session_id: int) -> list[dict]:
    rows = await conn.execute(
        "SELECT * FROM transcript_chunks WHERE session_id = ? ORDER BY chunk_index",
        (session_id,),
    )
    return [dict(row) for row in await rows.fetchall()]


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get("/sessions/{session_id}/notes")
async def get_notes(session_id: int) -> dict:
    """Return all available notes for a session (live_draft, merged, polished)."""
    conn = await get_async_conn()
    try:
        session = await _get_session_or_404(conn, session_id)
        notes_dir = os.path.join(session["data_dir"], "notes")
        result: dict = {"session_id": session_id}
        for name in ("live_draft.md", "merged.md", "polished.md"):
            path = os.path.join(notes_dir, name)
            if os.path.exists(path):
                result[name.replace(".md", "")] = StorageService.read_text(path)
        return result
    finally:
        await conn.close()


@router.post("/sessions/{session_id}/notes/merge")
async def trigger_merge(session_id: int) -> dict:
    """Merge transcript into slide outline structure and save as merged.md."""
    conn = await get_async_conn()
    try:
        session = await _get_session_or_404(conn, session_id)
        data_dir = session["data_dir"]

        # Transcript chunks
        chunks = await _get_chunks(conn, session_id)
        if not chunks:
            raise HTTPException(
                status_code=400, detail="No transcript chunks available."
            )

        # Slide outline
        row = await conn.execute(
            "SELECT outline_json FROM slide_outlines WHERE session_id = ?",
            (session_id,),
        )
        outline_row = await row.fetchone()
        if not outline_row:
            raise HTTPException(
                status_code=400,
                detail="No slide outline available. Upload slides first.",
            )
        slide_outline = json.loads(outline_row["outline_json"])

        # Generate merged notes via Groq
        notes_svc = NotesService()
        merged = await notes_svc.merge_with_slides(chunks, slide_outline)

        # Render to markdown with inline citations
        md_lines: list[str] = []
        for section in merged.get("sections", []):
            md_lines.append(f"## {section['heading']}")
            for bullet in section.get("bullets", []):
                md_lines.append(f"- {bullet}")
            for cite in section.get("citations", []):
                md_lines.append(
                    f"  [^t{cite['chunk_index']}]: "
                    f"{cite['start_time']:.0f}s\u2013{cite['end_time']:.0f}s"
                )
            md_lines.append("")
        merged_md = "\n".join(md_lines)

        # Persist
        notes_dir = os.path.join(data_dir, "notes")
        os.makedirs(notes_dir, exist_ok=True)
        StorageService.write_text(os.path.join(notes_dir, "merged.md"), merged_md)
        StorageService.write_json(
            os.path.join(notes_dir, "merged_raw.json"), merged
        )

        return {
            "session_id": session_id,
            "sections": len(merged.get("sections", [])),
            "status": "merged",
        }
    finally:
        await conn.close()


@router.post("/sessions/{session_id}/notes/polish")
async def trigger_polish(session_id: int) -> dict:
    """Polish the best available notes and save as polished.md."""
    conn = await get_async_conn()
    try:
        session = await _get_session_or_404(conn, session_id)
        notes_dir = os.path.join(session["data_dir"], "notes")

        # Read source notes: prefer merged, fall back to live draft
        merged_path = os.path.join(notes_dir, "merged.md")
        live_path = os.path.join(notes_dir, "live_draft.md")
        if os.path.exists(merged_path):
            source = StorageService.read_text(merged_path)
        elif os.path.exists(live_path):
            source = StorageService.read_text(live_path)
        else:
            raise HTTPException(
                status_code=400,
                detail="No notes to polish. Run merge first or wait for live notes.",
            )

        notes_svc = NotesService()
        polished = await notes_svc.polish_notes(source)

        StorageService.write_text(os.path.join(notes_dir, "polished.md"), polished)
        return {"session_id": session_id, "status": "polished"}
    finally:
        await conn.close()
