from faster_whisper import WhisperModel

from app.config import settings


class WhisperService:
    """Lazy singleton around a faster-whisper model.

    The model is downloaded and loaded on the first call to ``get()``,
    not at import time or server startup.  On Apple Silicon with ``int8``,
    ``small`` takes roughly 5-10 s per 60 s audio chunk.
    """

    _instance: "WhisperService | None" = None

    def __init__(self) -> None:
        print(f"STARTING MODEL: {settings.whisper_model}")
        self.model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )

    @classmethod
    def get(cls) -> "WhisperService":
        """Return the singleton, creating it (and downloading the model) if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def transcribe(self, wav_path: str) -> list[dict]:
        """Transcribe a WAV file.  Blocking — always call from a worker thread.

        Returns::

            [{"start": float, "end": float, "text": str, "confidence": float}, ...]

        ``confidence`` is the raw average log-probability from Whisper
        (negative; closer to 0 means higher confidence).
        """
        segments, _info = self.model.transcribe(wav_path, beam_size=5)
        # segments is a lazy generator — the list comprehension forces evaluation
        return [
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "confidence": round(seg.avg_logprob, 4),
            }
            for seg in segments
        ]
