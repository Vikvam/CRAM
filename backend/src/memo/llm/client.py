"""A thin OpenAI-compatible chat client.

Thin on purpose: "OpenAI-compatible" providers agree on ``/chat/completions``
and disagree on everything else, so the differences are handled one level up,
in the capability probe.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from memo.config import Settings, get_settings


class LLMError(RuntimeError):
    """The provider refused, timed out, or answered something unusable."""


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str | list[dict[str, Any]]

    def dump(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}


def image_part(path: str | Path) -> dict[str, Any]:
    """Inline an image as a data URL — no provider-specific upload endpoint needed."""
    file = Path(path)
    media_type = mimetypes.guess_type(file.name)[0] or "image/jpeg"
    encoded = base64.b64encode(file.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}}


def text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


class LLMClient:
    def __init__(self, settings: Settings | None = None, *, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owned = client is None

    def _http(self) -> httpx.Client:
        if self._client is None:
            key = self.settings.llm_api_key
            headers = {"Content-Type": "application/json"}
            if key is not None:
                headers["Authorization"] = f"Bearer {key.get_secret_value()}"
            self._client = httpx.Client(
                base_url=self.settings.llm_base_url.rstrip("/"),
                headers=headers,
                timeout=self.settings.llm_timeout,
            )
        return self._client

    def close(self) -> None:
        if self._owned and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> LLMClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.settings.llm_model,
            "messages": [m.dump() for m in messages],
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            response = self._http().post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:  # network, DNS, timeout
            raise LLMError(f"request to the LLM provider failed: {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(f"provider returned {response.status_code}: {response.text[:500]}")

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError(f"unexpected response shape: {response.text[:500]}") from exc

        if isinstance(content, list):  # some providers return content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str):
            raise LLMError(f"expected text content, got {type(content).__name__}")
        return content
