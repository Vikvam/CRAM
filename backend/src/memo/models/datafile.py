"""The data file: import, export and LLM-interchange format (PLAN 3).

SQLite is the runtime truth, but this format is binding — the tables mirror it
field for field, an import produces one, an export writes one, and the
round-trip test compares one.

Design rules (PLAN 3): null tolerant, extensible/lossless, versioned, stable
server-assigned IDs, and types that describe *practice shape*, not domain.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from memo.models.base import LenientModel

FORMAT = "memo.datafile"
CATEGORY_FORMAT = "memo.category"
CURRENT_VERSION = 1

#: A bilingual (or multilingual) label: ``{"ko": "나라", "en": "Countries"}``.
#: Groups and categories still use one; a data file's title does not (PLAN 3.1).
Label = dict[str, str]


def _native_first(label: Label) -> list[tuple[str, str]]:
    """Label entries with English last, the order a bilingual label reads in."""
    return sorted(label.items(), key=lambda kv: kv[0] == "en")


class NoteType(StrEnum):
    """Practice shape, never domain (PLAN 3.4)."""

    BIDIRECTIONAL = "bidirectional"
    DIRECTIONAL = "directional"


class Direction(StrEnum):
    FWD = "fwd"
    REV = "rev"


class NoteStatus(StrEnum):
    CONFIRMED = "confirmed"
    UNVERIFIED = "unverified"


class Priority(StrEnum):
    """How often a word should come up, as the person asked for it (PLAN 3.2).

    The ordinary middle is *absent*, not a third member: a collection nobody has
    marked exports exactly as it did before there was a mark to set. What the
    mark is finally worth is damped by how well the card is already known —
    :mod:`memo.practice.priority`.
    """

    LOW = "low"
    HIGH = "high"
    CRUCIAL = "crucial"


#: The middle one, which is never stored. The control that sets a priority has
#: three buttons, so the ordinary case needs a name to send; the column keeps
#: null for it.
NORMAL = "normal"


class Accept(LenientModel):
    """Answers counted as correct when typed, in addition to the displayed one.

    Always explicit — filled by the extractor or by the "that's the same thing"
    button during practice, never guessed from punctuation at runtime (PLAN 3.5).
    """

    front: list[str] | None = None
    back: list[str] | None = None


class Group(LenientModel):
    """A heading inside a data file (``나라 Countries``)."""

    id: str | None = None
    label: Label | None = None
    note: str | None = None
    extra: dict[str, Any] | None = None


class Note(LenientModel):
    """One note; generates one or two cards depending on :attr:`type` (PLAN 3.2)."""

    id: str | None = None
    type: NoteType | None = None
    front: str | None = None
    back: str | None = None
    front_lang: str | None = None
    back_lang: str | None = None
    fields: dict[str, str | None] | None = None
    accept: Accept | None = None
    modes: list[str] | None = None
    note: str | None = None
    group: str | None = None
    tags: list[str] | None = None
    status: NoteStatus | None = None
    confidence: float | None = None
    suspended: bool | None = None
    priority: Priority | None = None
    page: int | None = None
    extra: dict[str, Any] | None = None

    @field_validator("type", mode="before")
    @classmethod
    def _unknown_type_is_directional(cls, v: Any) -> Any:
        """An unrecognised type must not fail the load (PLAN 3.2)."""
        if v is None or isinstance(v, NoteType):
            return v
        if isinstance(v, str) and v not in {t.value for t in NoteType}:
            return NoteType.DIRECTIONAL
        return v

    @property
    def is_practisable(self) -> bool:
        """A note missing a side is kept and flagged, but generates no cards."""
        return bool((self.front or "").strip()) and bool((self.back or "").strip())

    def resolved_type(self, default: NoteType = NoteType.DIRECTIONAL) -> NoteType:
        """Fallback chain is note → file → category → ``directional``."""
        return self.type or default

    def directions(self, default: NoteType = NoteType.DIRECTIONAL) -> list[Direction]:
        if not self.is_practisable:
            return []
        if self.resolved_type(default) is NoteType.BIDIRECTIONAL:
            return [Direction.FWD, Direction.REV]
        return [Direction.FWD]


class ImportInfo(LenientModel):
    """Which importer produced this file, with which prompt and model."""

    profile: str | None = None
    model: str | None = None
    prompt_version: int | None = None
    at: str | None = None
    job_id: str | None = None
    extra: dict[str, Any] | None = None


class Source(LenientModel):
    """Provenance. Entirely optional — a hand-made file has none."""

    kind: Literal["image", "pdf", "text", "json", "csv", "anki", "manual"] | str | None = None
    files: list[str] | None = None
    page: int | None = None
    context: dict[str, Any] | None = None
    import_: ImportInfo | None = Field(default=None, alias="import")
    extra: dict[str, Any] | None = None


class DataFile(LenientModel):
    """One raw upload's worth of notes (PLAN 3.1)."""

    format: str = FORMAT
    version: int = CURRENT_VERSION
    id: str | None = None
    #: One plain line, not a language map: a file has a single name, whatever
    #: scripts it mixes ("2-1 · 어휘와 표현 · Vocabulary & Expressions").
    title: str | None = None
    default_type: NoteType | None = None
    front_lang: str | None = None
    back_lang: str | None = None
    source: Source | None = None
    groups: list[Group] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)
    tags: list[str] | None = None
    extra: dict[str, Any] | None = None

    @field_validator("title", mode="before")
    @classmethod
    def _one_line(cls, value: Any) -> Any:
        """Accept the label map version 1 files were written with, native side first."""
        if isinstance(value, dict):
            parts = [str(v).strip() for _, v in _native_first(value) if str(v).strip()]
            return " · ".join(dict.fromkeys(parts)) or None
        if isinstance(value, str):
            return value.strip() or None
        return value

    def note_default_type(self) -> NoteType:
        return self.default_type or NoteType.DIRECTIONAL

    def flagged(self) -> list[Note]:
        """Notes kept but unusable — the review screen shows these first."""
        return [n for n in self.notes if not n.is_practisable]


# --- versioning -------------------------------------------------------------

#: ``{from_version: migration}``; each returns the raw dict at ``from_version + 1``.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Bring a raw data-file dict up to :data:`CURRENT_VERSION`."""
    version = raw.get("version", CURRENT_VERSION)
    if not isinstance(version, int):
        raise ValueError(f"version must be an integer, got {version!r}")
    if version > CURRENT_VERSION:
        raise ValueError(f"data file is version {version}, this build understands up to {CURRENT_VERSION}")
    while version < CURRENT_VERSION:
        try:
            step = MIGRATIONS[version]
        except KeyError:  # pragma: no cover - guarded by a test over the whole chain
            raise ValueError(f"no migration from version {version}") from None
        raw = step(raw)
        version += 1
        raw["version"] = version
    return raw


def load_datafile(raw: dict[str, Any] | str | bytes) -> DataFile:
    """Parse and migrate a data file. Raises only on damage, never on missing fields."""
    if isinstance(raw, str | bytes):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("a data file must be a JSON object")
    fmt = raw.get("format", FORMAT)
    if fmt != FORMAT:
        raise ValueError(f"not a {FORMAT}: format is {fmt!r}")
    return DataFile.model_validate(migrate(dict(raw)))


def read_datafile(path: str | Path) -> DataFile:
    return load_datafile(Path(path).read_text(encoding="utf-8"))
