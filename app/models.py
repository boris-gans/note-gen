from dataclasses import dataclass


@dataclass
class Course:
    id: int
    name: str
    created_at: str


@dataclass
class Session:
    id: int
    course_id: int
    session_number: int
    status: str  # idle | recording | stopped
    data_dir: str
    created_at: str


@dataclass
class TranscriptChunk:
    id: int
    session_id: int
    chunk_index: int
    start_time: float
    end_time: float
    text: str
    confidence: float


@dataclass
class SlideOutline:
    id: int
    session_id: int
    file_path: str
    outline_json: str  # JSON string
    images_json: str  # JSON string
