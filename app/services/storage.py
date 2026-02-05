import json
import os

from app.config import settings


class StorageService:
    @staticmethod
    def session_dir(course_name: str, session_name: str) -> str:
        """Return the path for a session directory under courses_root."""
        return os.path.join(settings.courses_root, course_name, session_name)

    @staticmethod
    def ensure_dirs(session_dir: str) -> None:
        """Create the standard subdirectory layout for a session."""
        for sub in ("audio", "transcript", "slides", "slides/images", "notes", "study"):
            os.makedirs(os.path.join(session_dir, sub), exist_ok=True)

    @staticmethod
    def write_json(path: str, data: dict | list) -> None:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def read_json(path: str) -> dict | list:
        with open(path) as f:
            return json.load(f)

    @staticmethod
    def write_text(path: str, text: str) -> None:
        with open(path, "w") as f:
            f.write(text)

    @staticmethod
    def read_text(path: str) -> str:
        with open(path) as f:
            return f.read()

    @staticmethod
    def write_index(session_dir: str, metadata: dict) -> None:
        """Write session metadata to index.json."""
        StorageService.write_json(os.path.join(session_dir, "index.json"), metadata)
