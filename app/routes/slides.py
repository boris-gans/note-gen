import asyncio
import json
import os

import aiofiles
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.database import get_async_conn
from app.services.slides import SlideService

router = APIRouter(prefix="/api", tags=["slides"])


@router.post("/sessions/{session_id}/slides")
async def upload_slides(
    session_id: int, file: UploadFile = File(...)
) -> dict:
    """Upload a PDF or PPTX file, parse it, and store the outline."""
    conn = await get_async_conn()
    try:
        # Verify session exists
        row = await conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        session = await row.fetchone()
        if not session:
            raise HTTPException(
                status_code=404, detail=f"Session {session_id} not found"
            )

        data_dir = session["data_dir"]

        # Validate extension
        filename = file.filename or "upload"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".pdf", ".pptx", ".ppt"):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {ext}. Use .pdf or .pptx",
            )

        # Save the uploaded file
        slides_dir = os.path.join(data_dir, "slides")
        os.makedirs(slides_dir, exist_ok=True)
        saved_path = os.path.join(slides_dir, filename)
        async with aiofiles.open(saved_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        # Parse slides (CPU-bound; offload to thread pool)
        parsed = await asyncio.to_thread(SlideService.parse, saved_path, data_dir)

        # Persist outline to DB (upsert)
        outline_json = json.dumps(parsed["sections"])
        images_json = json.dumps([
            img
            for section in parsed["sections"]
            for img in section.get("image_paths", [])
        ])
        await conn.execute(
            "DELETE FROM slide_outlines WHERE session_id = ?", (session_id,)
        )
        await conn.execute(
            "INSERT INTO slide_outlines (session_id, file_path, outline_json, images_json) "
            "VALUES (?, ?, ?, ?)",
            (session_id, saved_path, outline_json, images_json),
        )
        await conn.commit()

        return {
            "session_id": session_id,
            "file": filename,
            "sections_count": len(parsed["sections"]),
            "images_count": sum(
                len(s.get("image_paths", [])) for s in parsed["sections"]
            ),
            "outline": parsed["sections"],
        }
    finally:
        await conn.close()


@router.get("/sessions/{session_id}/slides/outline")
async def get_outline(session_id: int) -> dict:
    """Return the parsed slide outline for a session."""
    conn = await get_async_conn()
    try:
        row = await conn.execute(
            "SELECT * FROM slide_outlines WHERE session_id = ?", (session_id,)
        )
        outline = await row.fetchone()
        if not outline:
            raise HTTPException(
                status_code=404,
                detail=f"No slides uploaded for session {session_id}",
            )
        return {
            "session_id": session_id,
            "file_path": outline["file_path"],
            "sections": json.loads(outline["outline_json"]),
            "images": json.loads(outline["images_json"]),
        }
    finally:
        await conn.close()
