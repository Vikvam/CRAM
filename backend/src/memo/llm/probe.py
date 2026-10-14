"""Capability probe (PLAN 3.6).

Run once when a provider is configured, and stored, because "OpenAI-compatible"
says nothing about structured output: the answer is one of three tiers, and the
rest of the pipeline is written against the tiers, not against providers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from memo.llm.client import ChatMessage, LLMClient, LLMError, image_part, text_part
from memo.llm.jsonblock import extract_json_object

_PROBE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok"],
    "properties": {"ok": {"type": "boolean"}},
}


class StructuredOutput(StrEnum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    TEXT = "text"


@dataclass(slots=True)
class Capabilities:
    structured_output: StructuredOutput
    vision: bool
    model: str
    notes: list[str]

    def dump(self) -> dict[str, object]:
        data = asdict(self)
        data["structured_output"] = str(self.structured_output)
        return data


def probe(client: LLMClient, *, model: str | None = None, image: Path | None = None) -> Capabilities:
    """Ask the provider what it can do by trying, from strictest to loosest."""
    model = model or client.settings.llm_model
    notes: list[str] = []
    ask = [ChatMessage(role="user", content='Reply with {"ok": true} and nothing else.')]

    tier = StructuredOutput.TEXT
    for candidate, response_format in (
        (
            StructuredOutput.JSON_SCHEMA,
            {
                "type": "json_schema",
                "json_schema": {"name": "probe", "strict": True, "schema": _PROBE_SCHEMA},
            },
        ),
        (StructuredOutput.JSON_OBJECT, {"type": "json_object"}),
        (StructuredOutput.TEXT, None),
    ):
        try:
            text = client.chat(ask, model=model, response_format=response_format)
            if extract_json_object(text).get("ok") is True:
                tier = candidate
                break
            notes.append(f"{candidate}: answered but not as asked")
        except (LLMError, ValueError) as exc:
            notes.append(f"{candidate}: {exc}")

    vision = False
    if image is not None:
        look = ChatMessage(
            role="user",
            content=[text_part("Answer with one word: what is in this image?"), image_part(image)],
        )
        try:
            client.chat([look], model=model, max_tokens=16)
            vision = True
        except LLMError as exc:
            notes.append(f"vision: {exc}")

    return Capabilities(structured_output=tier, vision=vision, model=model, notes=notes)
