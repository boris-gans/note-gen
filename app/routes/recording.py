import asyncio
import os
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.config import settings
from app.database import get_async_conn
from app.recording import RecordingWorker
from app.services.notes import NotesService
from app.services.storage import StorageService

router = APIRouter(tags=["recording"])

# In-memory registry of active recording sessions.
# session_id -> {"worker": RecordingWorker | None, "websockets": [WebSocket],
#                "loop": asyncio.AbstractEventLoop, "data_dir": str}
_active: dict[int, dict[str, Any]] = {}


# ==================================================================
# REST endpoints
# ==================================================================


@router.post("/api/sessions/{session_id}/recording/start")
async def start_recording(session_id: int) -> dict:
    """Start audio recording for a session."""
    if session_id in _active and _active[session_id].get("worker") is not None:
        raise HTTPException(
            status_code=409, detail="Recording already active for this session."
        )

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
        data_dir = session["data_dir"]

        await conn.execute(
            "UPDATE sessions SET status = 'recording' WHERE id = ?", (session_id,)
        )
        await conn.commit()
    finally:
        await conn.close()

    # Create worker and register the async bridge callback
    loop = asyncio.get_event_loop()
    worker = RecordingWorker(session_id, data_dir)

    def _on_chunk(chunk_meta: dict) -> None:
        """Called from the worker thread. Bridges to the event loop."""
        asyncio.run_coroutine_threadsafe(
            _handle_chunk_transcribed(session_id, chunk_meta), loop
        )

    worker.on_chunk_transcribed(_on_chunk)

    # Preserve any existing websocket list (client may connect before start)
    existing_ws = _active.get(session_id, {}).get("websockets", [])
    _active[session_id] = {
        "worker": worker,
        "websockets": existing_ws,
        "loop": loop,
        "data_dir": data_dir,
    }

    try:
        worker.start()
    except Exception as e:
        _active[session_id]["worker"] = None
        # Revert DB status
        conn2 = await get_async_conn()
        await conn2.execute(
            "UPDATE sessions SET status = 'idle' WHERE id = ?", (session_id,)
        )
        await conn2.commit()
        await conn2.close()
        raise HTTPException(status_code=500, detail=str(e))

    # Notify connected clients
    await _send_to_all(session_id, {"type": "recording_status", "status": "recording"})

    return {"session_id": session_id, "status": "recording"}


@router.post("/api/sessions/{session_id}/recording/stop")
async def stop_recording(session_id: int) -> dict:
    """Stop recording and finalize the session."""
    if session_id not in _active or _active[session_id].get("worker") is None:
        raise HTTPException(
            status_code=400, detail="No active recording for this session."
        )

    entry = _active[session_id]
    worker: RecordingWorker = entry["worker"]
    data_dir = entry["data_dir"]
    worker.stop()
    entry["worker"] = None  # keep websockets alive for the stop broadcast

    # Persist transcript summary and update session
    conn = await get_async_conn()
    try:
        rows = await conn.execute(
            "SELECT * FROM transcript_chunks WHERE session_id = ? ORDER BY chunk_index",
            (session_id,),
        )
        chunks = [dict(row) for row in await rows.fetchall()]

        transcript_dir = os.path.join(data_dir, "transcript")
        os.makedirs(transcript_dir, exist_ok=True)
        StorageService.write_json(
            os.path.join(transcript_dir, "chunks.json"), chunks
        )

        await conn.execute(
            "UPDATE sessions SET status = 'stopped' WHERE id = ?", (session_id,)
        )
        await conn.commit()

        StorageService.write_index(data_dir, {
            "session_id": session_id,
            "status": "stopped",
            "total_chunks": len(chunks),
            "total_duration_seconds": chunks[-1]["end_time"] if chunks else 0,
        })

        await _send_to_all(
            session_id, {"type": "recording_status", "status": "stopped"}
        )

        return {
            "session_id": session_id,
            "status": "stopped",
            "chunks": len(chunks),
        }
    finally:
        await conn.close()


# ==================================================================
# WebSocket endpoint
# ==================================================================


@router.websocket("/ws/session/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: int) -> None:
    """Live update stream for a recording session."""
    await websocket.accept()

    # Ensure an entry exists (client may connect before or after start)
    if session_id not in _active:
        _active[session_id] = {
            "worker": None,
            "websockets": [],
            "loop": asyncio.get_event_loop(),
            "data_dir": "",
        }
    _active[session_id]["websockets"].append(websocket)

    # Send current status immediately
    worker = _active[session_id].get("worker")
    is_recording = worker is not None and worker.is_running
    await websocket.send_json({
        "type": "recording_status",
        "status": "recording" if is_recording else "idle",
    })

    try:
        while True:
            await websocket.receive_text()  # keep-alive; client sends pings
    except WebSocketDisconnect:
        if session_id in _active:
            ws_list = _active[session_id]["websockets"]
            if websocket in ws_list:
                ws_list.remove(websocket)
            # Clean up entry if no websockets and no active worker
            if not ws_list and _active[session_id].get("worker") is None:
                del _active[session_id]


# ==================================================================
# Internal helpers (run on the event loop)
# ==================================================================


async def _send_to_all(session_id: int, message: dict) -> None:
    """Broadcast a JSON message to all connected WebSocket clients."""
    if session_id not in _active:
        return
    for ws in list(_active[session_id]["websockets"]):
        try:
            await ws.send_json(message)
        except Exception:
            pass  # client may have already disconnected


async def _handle_chunk_transcribed(session_id: int, chunk_meta: dict) -> None:
    """Bridged from the worker thread via run_coroutine_threadsafe.

    1. Broadcast the new chunk to WebSocket clients.
    2. Every N chunks, trigger live notes generation via Groq.
    """
    await _send_to_all(session_id, {"type": "chunk_transcribed", **chunk_meta})

    # Trigger live notes on the configured interval
    if (chunk_meta["chunk_index"] + 1) % settings.live_notes_interval_chunks == 0:
        await _trigger_live_notes(session_id)


async def _trigger_live_notes(session_id: int) -> None:
    """Fetch all chunks so far, generate live notes, broadcast + persist."""
    conn = await get_async_conn()
    try:
        rows = await conn.execute(
            "SELECT * FROM transcript_chunks WHERE session_id = ? ORDER BY chunk_index",
            (session_id,),
        )
        chunks = [dict(row) for row in await rows.fetchall()]
    finally:
        await conn.close()

    if not chunks:
        return

    # Read existing live draft if any
    data_dir = _active.get(session_id, {}).get("data_dir", "")
    notes_path = os.path.join(data_dir, "notes", "live_draft.md") if data_dir else ""
    existing_notes = ""
    if notes_path and os.path.exists(notes_path):
        existing_notes = StorageService.read_text(notes_path)

    try:
        notes_svc = NotesService()
        live_notes = await notes_svc.generate_live_notes(chunks, existing_notes)

        # Persist
        if data_dir:
            notes_dir = os.path.join(data_dir, "notes")
            os.makedirs(notes_dir, exist_ok=True)
            StorageService.write_text(notes_path, live_notes)

        # Broadcast
        await _send_to_all(
            session_id, {"type": "live_notes_updated", "notes": live_notes}
        )
    except Exception:
        pass  # don't crash the recording loop if Groq is unreachable
