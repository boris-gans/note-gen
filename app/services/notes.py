from app.clients import GroqClient

# ---------------------------------------------------------------------------
# JSON Schemas — Groq strict mode requires additionalProperties: false
# everywhere and all properties in "required".
# ---------------------------------------------------------------------------

LIVE_NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {"type": "string"},
    },
    "required": ["notes"],
    "additionalProperties": False,
}

MERGED_NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "chunk_index": {"type": "integer"},
                                "start_time": {"type": "number"},
                                "end_time": {"type": "number"},
                            },
                            "required": ["chunk_index", "start_time", "end_time"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["heading", "bullets", "citations"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sections"],
    "additionalProperties": False,
}

POLISHED_NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {"type": "string"},
    },
    "required": ["notes"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_chunks(chunks: list[dict]) -> str:
    """Format transcript chunks into a timestamped string for the LLM."""
    lines = []
    for c in chunks:
        t = f"[{c['start_time']:.0f}s\u2013{c['end_time']:.0f}s]"
        lines.append(f"{t} {c['text']}")
    return "\n".join(lines)


def _format_slide_outline(sections: list[dict]) -> str:
    """Format slide outline sections into a readable string for the LLM."""
    lines = []
    for s in sections:
        lines.append(f"## {s['title']}")
        for b in s.get("bullets", []):
            lines.append(f"  - {b}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class NotesService:
    """Generate and transform lecture notes via the Groq API."""

    def __init__(self, groq: GroqClient | None = None) -> None:
        self.groq = groq or GroqClient()

    async def generate_live_notes(
        self,
        chunks: list[dict],
        existing_notes: str = "",
    ) -> str:
        """Generate or update live notes from accumulated transcript chunks.

        Called every N chunks during an active recording session.
        Returns markdown-formatted notes.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a lecture note-taker. Given a rolling transcript of a lecture, "
                    "produce concise, well-structured notes as a markdown string. "
                    "Capture key points, definitions, and important details. "
                    "If existing notes are provided, update and expand them — do not repeat "
                    "information that is already well-covered. Keep notes evolving but coherent."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Transcript so far:\n{_format_chunks(chunks)}\n\n"
                    f"Existing notes:\n{existing_notes or '(none yet)'}\n\n"
                    "Produce updated lecture notes."
                ),
            },
        ]
        result = await self.groq.chat_json(
            messages, LIVE_NOTES_SCHEMA, schema_name="live_notes"
        )
        return result["notes"]

    async def merge_with_slides(
        self,
        chunks: list[dict],
        slide_outline: list[dict],
    ) -> dict:
        """Merge transcript-derived notes into the slide outline structure.

        Returns a dict matching MERGED_NOTES_SCHEMA — each section has a
        heading (from slides), bullets (from transcript), and citations
        (time ranges linking back to transcript chunks).
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a lecture note compiler. You have a slide outline (the authoritative "
                    "structure) and a timestamped transcript. Your job is to place transcript "
                    "content under the best-matching slide headings as concise bullet points. "
                    "For each bullet, include the citation (chunk_index, start_time, end_time) "
                    "of the transcript segment it came from. If a transcript segment spans "
                    "multiple sections, split it appropriately. Do not invent information."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Slide outline:\n{_format_slide_outline(slide_outline)}\n\n"
                    f"Transcript:\n{_format_chunks(chunks)}\n\n"
                    "Merge the transcript into the slide outline structure with citations."
                ),
            },
        ]
        return await self.groq.chat_json(
            messages, MERGED_NOTES_SCHEMA, schema_name="merged_notes"
        )

    async def polish_notes(self, notes_markdown: str) -> str:
        """Rewrite notes for clarity and coherence.  Preserves citation markers.

        Returns polished markdown string.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert note editor. Rewrite the following lecture notes for "
                    "clarity, removing redundancy and improving flow. Preserve all citation "
                    "markers (e.g. [^t12]) exactly as they appear — do not remove or renumber them. "
                    "Keep the heading structure intact."
                ),
            },
            {
                "role": "user",
                "content": f"Notes to polish:\n{notes_markdown}",
            },
        ]
        result = await self.groq.chat_json(
            messages, POLISHED_NOTES_SCHEMA, schema_name="polished_notes"
        )
        return result["notes"]
