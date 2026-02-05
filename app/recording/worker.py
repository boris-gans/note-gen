import os
import threading
from typing import Callable

import numpy as np
import sounddevice as sd

from app.config import settings
from app.database import get_sync_conn
from app.recording.audio_utils import compute_chunk_boundaries, samples_to_wav
from app.services.transcription import WhisperService


class RecordingWorker:
    """Manages continuous audio recording and chunked transcription.

    Threading model (three contexts — never blur them):

    1. **Audio callback** — runs in sounddevice's internal C audio thread.
       May ONLY append to the buffer and increment the sample counter.
       No I/O, no logging, no heavy allocation.

    2. **Worker loop** — runs in a daemon Python thread.  Handles all I/O:
       writing WAV files, calling Whisper, inserting SQLite rows.
       Fires ``on_chunk_transcribed`` callbacks from this thread.

    3. **Event loop** — FastAPI/asyncio.  The route that starts recording
       registers a callback that uses ``asyncio.run_coroutine_threadsafe``
       to push events onto the event loop for WebSocket broadcast.
    """

    def __init__(self, session_id: int, session_dir: str) -> None:
        self.session_id = session_id
        self.session_dir = session_dir
        self.sample_rate = settings.sample_rate
        self.samples_per_chunk = self.sample_rate * settings.chunk_duration_seconds

        # Audio buffer — guarded by _lock
        self._buffer: list[np.ndarray] = []
        self._total_samples: int = 0
        self._lock = threading.Lock()

        # Chunk state — only touched by the worker thread (no lock needed)
        self._last_chunk_end: int = 0
        self._chunk_index: int = 0

        # Lifecycle
        self._running = False
        self._stream: sd.InputStream | None = None
        self._thread: threading.Thread | None = None

        # Callback registry
        self._callbacks: list[Callable[[dict], None]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_chunk_transcribed(self, fn: Callable[[dict], None]) -> None:
        """Register a callback invoked (from the worker thread) after each chunk.

        ``fn`` receives::

            {
                "session_id": int,
                "chunk_index": int,
                "start_time": float,   # seconds from recording start
                "end_time": float,
                "text": str,           # concatenated segment texts
                "segments": [...]      # raw Whisper segment dicts
            }
        """
        self._callbacks.append(fn)

    def start(self) -> None:
        """Open the microphone and start the worker loop."""
        self._running = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._audio_callback,
            blocksize=1024,
        )
        self._stream.start()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop recording, join the worker thread, flush remaining audio."""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        # Flush any samples that didn't fill a complete chunk
        self._flush_remaining()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def total_duration_seconds(self) -> float:
        with self._lock:
            return self._total_samples / self.sample_rate

    # ------------------------------------------------------------------
    # Audio callback — C audio thread
    # ------------------------------------------------------------------

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        timeinfo,  # noqa: ANN001
        status: sd.CallbackFlags,
    ) -> None:
        """sounddevice callback.  Must be fast — buffer only, no I/O."""
        with self._lock:
            self._buffer.append(indata.copy())
            self._total_samples += frames

    # ------------------------------------------------------------------
    # Worker loop — daemon thread
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while self._running:
            self._maybe_process_chunks()
            threading.Event().wait(1.0)  # non-busy 1 s poll

    def _maybe_process_chunks(self) -> None:
        """Check for complete chunks and process each one sequentially."""
        with self._lock:
            total = self._total_samples

        boundaries = compute_chunk_boundaries(
            total, self._last_chunk_end, self.samples_per_chunk
        )
        if not boundaries:
            return

        # Grab the full audio buffer once (under lock)
        with self._lock:
            if not self._buffer:
                return
            full_audio = np.concatenate(self._buffer, axis=0).flatten()

        for start, end in boundaries:
            if end > len(full_audio):
                break  # guard against a rare race between total_samples and buffer
            self._process_single_chunk(full_audio[start:end])
            self._last_chunk_end = end
            self._chunk_index += 1

    # ------------------------------------------------------------------
    # Chunk processing — worker thread
    # ------------------------------------------------------------------

    def _process_single_chunk(self, samples: np.ndarray) -> None:
        """Write WAV -> transcribe -> insert DB row -> fire callbacks."""
        audio_dir = os.path.join(self.session_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)

        wav_path = os.path.join(audio_dir, f"chunk_{self._chunk_index:04d}.wav")
        samples_to_wav(samples, self.sample_rate, wav_path)

        # Transcribe (blocking — fine, we're in the daemon thread)
        whisper = WhisperService.get()
        segments = whisper.transcribe(wav_path)

        # Time offsets relative to recording start
        chunk_start_time = round(self._last_chunk_end / self.sample_rate, 2)
        chunk_end_time = round(
            (self._last_chunk_end + len(samples)) / self.sample_rate, 2
        )

        text = " ".join(seg["text"] for seg in segments)
        confidence = (
            sum(seg["confidence"] for seg in segments) / len(segments)
            if segments
            else 0.0
        )

        # Insert into SQLite
        conn = get_sync_conn()
        try:
            conn.execute(
                """INSERT INTO transcript_chunks
                   (session_id, chunk_index, start_time, end_time, text, confidence)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    self.session_id,
                    self._chunk_index,
                    chunk_start_time,
                    chunk_end_time,
                    text,
                    confidence,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # Fire callbacks (runs on the worker thread; callers bridge to event loop)
        chunk_meta = {
            "session_id": self.session_id,
            "chunk_index": self._chunk_index,
            "start_time": chunk_start_time,
            "end_time": chunk_end_time,
            "text": text,
            "segments": segments,
        }
        for fn in self._callbacks:
            try:
                fn(chunk_meta)
            except Exception:
                pass  # don't let a bad callback kill the worker

    # ------------------------------------------------------------------
    # Flush remaining audio on stop
    # ------------------------------------------------------------------

    def _flush_remaining(self) -> None:
        """Emit leftover samples (< 1 full chunk) as a final short chunk.

        Skipped if fewer than 1 second of audio remains (noise only).
        """
        with self._lock:
            if not self._buffer:
                return
            full_audio = np.concatenate(self._buffer, axis=0).flatten()

        remaining = full_audio[self._last_chunk_end:]
        if len(remaining) < self.sample_rate:
            return  # less than 1 second — not worth transcribing

        self._process_single_chunk(remaining)
        self._last_chunk_end = len(full_audio)
        self._chunk_index += 1
