"""The LLM-facing extraction model (PLAN 3.6).

Deliberately *not* the storage model: flat, small, fixed keys, no IDs, no
provenance, no review state, and only strings / string lists / null. Every
property is required (nullable where empty is meaningful) because that is what
strict structured output demands.

The strict JSON Schema is generated from these classes, so the prompt and the
validator can never drift apart.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """``additionalProperties: false`` and no defaults — see module docstring."""

    model_config = ConfigDict(extra="forbid")


class Confidence(StrEnum):
    """A word, not a number: models report words far more reliably."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExtractedContext(StrictModel):
    """One level of hierarchy printed on the page (chapter, lesson, section)."""

    kind: str = Field(description="chapter | lesson | section | unit — whatever the page calls it")
    number: str | None = Field(description='Printed number such as "02" or "2-1"; null if none')
    native: str | None = Field(description="The heading in the source language; null if absent")
    translated: str | None = Field(description="The heading in English; null if absent")


class ExtractedGroup(StrictModel):
    """A heading above a block of items (``나라 Countries``)."""

    key: str = Field(description="Short lowercase ascii id, unique in this page, e.g. 'countries'")
    label_native: str | None = Field(description="Heading in the source language; null if absent")
    label_translated: str | None = Field(description="Heading in English; null if absent")


class ExtractedItem(StrictModel):
    """One vocabulary pair / question-answer pair found on the page."""

    group: str | None = Field(description="key of the group this item sits under; null if none")
    front: str = Field(description="The prompt side exactly as printed, without footnote markers")
    back: str = Field(description="The answer side exactly as printed")
    front_accepted: list[str] = Field(
        description=(
            "Other spellings that mean the same as `front` and should count as correct "
            "when typed. Empty list if there are none. Never invent variants."
        )
    )
    back_accepted: list[str] = Field(
        description=(
            'Each separate meaning of `back` as a standalone answer: "what, which" gives '
            '["what", "which"]; "I/me (honorific)" gives ["I", "me"]. Empty list if `back` '
            "is a single meaning."
        )
    )
    note: str | None = Field(description="Footnote or usage note attached to this item; null if none")
    confidence: Confidence = Field(description="How sure you are that this row was read correctly")


class ExtractionResult(StrictModel):
    """Everything one page yields. The adapter turns this into a data file."""

    title_native: str | None = Field(description="Title of the section this page belongs to; else null")
    title_translated: str | None = Field(description="English title; else null")
    context: list[ExtractedContext] = Field(
        description="Hierarchy printed on the page, outermost first. Empty list if none is visible."
    )
    groups: list[ExtractedGroup] = Field(description="Headings found; empty list if the page has none")
    items: list[ExtractedItem] = Field(description="Every pair on the page, in reading order")
    unreadable: list[str] = Field(
        description="Rows you could not read confidently, quoted as best you can. Empty list if none."
    )


#: Bumped whenever a prompt or this shape changes, and recorded in `source.import`.
PROMPT_VERSION = 1


def strict_json_schema(model: type[BaseModel] = ExtractionResult) -> dict[str, Any]:
    """JSON Schema that satisfies OpenAI-style strict structured output.

    Pydantic almost gets there; this tightens the two things it leaves loose:
    every object forbids extra properties, and every property is required
    (strict mode has no notion of an optional key — absence is spelled ``null``).
    """
    schema = model.model_json_schema(mode="serialization")
    _tighten(schema)
    return schema


def _tighten(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _tighten(item)
        return
    if not isinstance(node, dict):
        return
    if node.get("type") == "object" or "properties" in node:
        properties = node.get("properties", {})
        node["additionalProperties"] = False
        node["required"] = list(properties)
    for key, value in node.items():
        if key != "required":
            _tighten(value)


#: Which side an extraction fills; the importer decides, not the model.
Side = Literal["front", "back"]
