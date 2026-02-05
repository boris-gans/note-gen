import json

from groq import AsyncGroq

from app.config import settings

# Reference list of models currently available on Groq's platform.
# Update this list as Groq adds or retires models.
# See https://console.groq.com/docs/models for the authoritative list.
AVAILABLE_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma2-9b-it",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "qwen-qwq-32b",
    "deepseek-r1-distill-llama-70b",
    "moonshotai/kimi-k2-instruct",
]


class GroqClient:
    """Async wrapper around the official Groq SDK with easy model switching.

    Usage::

        groq = GroqClient()                          # uses DEFAULT_MODEL from env
        text = await groq.chat(messages)             # plain completion

        fast = groq.with_model("llama-3.1-8b-instant")  # zero-cost clone
        text = await fast.chat(messages)             # same session, different model

        data = await groq.chat_json(messages, MY_SCHEMA)  # structured output

    ``with_model()`` shares the underlying ``AsyncGroq`` HTTP session, so
    switching models mid-request is allocation-free beyond the wrapper object.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self._model = model or settings.default_model
        self._client = AsyncGroq(api_key=api_key or settings.groq_api_key)

    # ------------------------------------------------------------------
    # Model switching
    # ------------------------------------------------------------------
    @property
    def default_model(self) -> str:
        return self._model

    def with_model(self, model_name: str) -> "GroqClient":
        """Return a new GroqClient bound to *model_name*.

        The underlying ``AsyncGroq`` client (and its httpx session) is shared,
        so this is allocation-free beyond the new wrapper object.
        """
        clone = GroqClient.__new__(GroqClient)
        clone._model = model_name
        clone._client = self._client  # shared — no new HTTP connection
        return clone

    # ------------------------------------------------------------------
    # Completions
    # ------------------------------------------------------------------
    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Plain-text chat completion. Returns the content string."""
        kwargs: dict = {
            "model": model or self._model,
            "messages": messages,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        resp = await self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content

    async def chat_json(
        self,
        messages: list[dict],
        response_schema: dict,
        *,
        schema_name: str = "response",
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """Structured-output completion using Groq's strict JSON Schema mode.

        *response_schema* must be a valid JSON Schema dict.  Groq strict mode
        requires ``"additionalProperties": false`` on every object and all
        properties listed in ``"required"``.

        Returns the parsed JSON as a Python dict.
        """
        kwargs: dict = {
            "model": model or self._model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": response_schema,
                },
            },
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        resp = await self._client.chat.completions.create(**kwargs)
        return json.loads(resp.choices[0].message.content)
