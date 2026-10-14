"""Which importer should read this upload (PLAN 4).

One cheap call on page 1 proposes an importer; the UI preselects it and you can
override. A failure here is never fatal — it falls back to the general reader.
With only the general reader installed there is nothing to choose, and no call.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from memo.importers.base import AnyImporter
from memo.importers.registry import FALLBACK, Registry
from memo.llm.client import ChatMessage, LLMClient, LLMError, image_part, text_part
from memo.llm.probe import StructuredOutput
from memo.llm.structured import complete_structured
from memo.models.extraction import StrictModel

ROUTER_PROMPT = """\
You are shown the first page of an upload and a numbered list of readers.
Answer with the number of the reader that fits the page best.
If none clearly fits, choose the one described as the fallback.
"""


class RouterChoice(StrictModel):
    choice: int = Field(description="The number of the reader that fits best")
    why: str = Field(description="One short sentence saying why")


def _menu(importers: list[AnyImporter]) -> str:
    return "\n".join(f"{i}. {imp.description}" for i, imp in enumerate(importers, 1))


def _material(first: str | Path | list[dict]) -> list[dict]:
    """A photo, or the content parts of the first few PDF pages."""
    return first if isinstance(first, list) else [image_part(first)]


def route(
    client: LLMClient,
    image: str | Path | list[dict],
    *,
    registry: Registry,
    tier: StructuredOutput | str = StructuredOutput.TEXT,
    model: str | None = None,
    kind: str = "image",
) -> tuple[AnyImporter, str | None]:
    """Return the proposed importer and the model's reason (``None`` if it failed)."""
    importers = registry.all(kind) or registry.all()
    if len(importers) == 1:
        return importers[0], None

    messages = [
        ChatMessage(role="system", content=ROUTER_PROMPT),
        ChatMessage(role="user", content=[text_part(_menu(importers)), *_material(image)]),
    ]
    try:
        answer = complete_structured(
            client, RouterChoice, messages, tier=tier, model=model, schema_name="router"
        )
    except (LLMError, ValueError, OSError):
        return registry.get(FALLBACK), None

    index = answer.choice - 1
    if not 0 <= index < len(importers):
        return registry.get(FALLBACK), None
    return importers[index], answer.why
