from app.clients import GroqClient

# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

STUDY_GUIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "guide": {"type": "string"},
    },
    "required": ["guide"],
    "additionalProperties": False,
}

QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "correct_index": {"type": "integer"},
                    "explanation": {"type": "string"},
                },
                "required": ["question", "options", "correct_index", "explanation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class StudyService:
    """Generate study guides and quizzes from lecture notes via the Groq API."""

    def __init__(self, groq: GroqClient | None = None) -> None:
        self.groq = groq or GroqClient()

    async def generate_study_guide(self, notes_markdown: str) -> str:
        """Generate a condensed study guide from notes.

        Returns a markdown string containing a condensed outline,
        key definitions, common confusions, and practice questions.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert study-guide writer for college students. "
                    "Given lecture notes, produce a comprehensive study guide in markdown. "
                    "Include: a condensed outline, key definitions, common confusions or "
                    "misconceptions to watch out for, and 3-5 practice questions with answers."
                ),
            },
            {
                "role": "user",
                "content": f"Lecture notes:\n{notes_markdown}\n\nGenerate a study guide.",
            },
        ]
        result = await self.groq.chat_json(
            messages, STUDY_GUIDE_SCHEMA, schema_name="study_guide"
        )
        return result["guide"]

    async def generate_quiz(
        self,
        notes_markdown: str,
        num_questions: int = 10,
    ) -> list[dict]:
        """Generate multiple-choice quiz questions from notes.

        Each question has: question text, 4 options (A-D), correct_index (0-3),
        and an explanation of the correct answer.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert quiz writer for college students. "
                    "Given lecture notes, generate exactly the requested number of "
                    "multiple-choice questions. Each question should have 4 options, "
                    "one correct answer, and a brief explanation. Questions should "
                    "test understanding, not just recall. Vary difficulty across the set."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Lecture notes:\n{notes_markdown}\n\n"
                    f"Generate exactly {num_questions} multiple-choice questions."
                ),
            },
        ]
        result = await self.groq.chat_json(
            messages, QUIZ_SCHEMA, schema_name="quiz"
        )
        return result["questions"]
