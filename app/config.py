from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Groq
    groq_api_key: str = "gsk_placeholder"
    default_model: str = "llama-3.3-70b-versatile"

    # Whisper
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Recording
    sample_rate: int = 16000
    chunk_duration_seconds: int = 60
    live_notes_interval_chunks: int = 5

    # Storage
    courses_root: str = "courses"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
