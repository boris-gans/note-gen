import numpy as np
import soundfile as sf


def samples_to_wav(samples: np.ndarray, sample_rate: int, path: str) -> None:
    """Write float32 samples to a 16-bit PCM WAV file (Whisper-compatible)."""
    sf.write(path, samples, sample_rate, subtype="PCM_16")


def compute_chunk_boundaries(
    total_samples: int,
    last_chunk_end: int,
    samples_per_chunk: int,
) -> list[tuple[int, int]]:
    """Return (start, end) sample offsets for every complete chunk since *last_chunk_end*.

    Pure function — no side effects.  The worker calls this every second;
    if fewer than *samples_per_chunk* new samples have accumulated, returns [].
    """
    boundaries: list[tuple[int, int]] = []
    pos = last_chunk_end
    while pos + samples_per_chunk <= total_samples:
        boundaries.append((pos, pos + samples_per_chunk))
        pos += samples_per_chunk
    return boundaries
