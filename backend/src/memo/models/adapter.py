"""extraction → storage (PLAN 3.6).

One function, so the storage format can grow without touching prompts and each
importer can use its own extraction shape. Also merges the pages of a
multi-page job (PLAN 4): groups and context carry across page breaks, duplicates
within the job are dropped, and every note remembers the page it came from.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from memo.models.datafile import (
    Accept,
    DataFile,
    Group,
    ImportInfo,
    Note,
    NoteStatus,
    NoteType,
    Source,
)
from memo.models.extraction import Confidence, ExtractedItem, ExtractionResult
from memo.models.ids import datafile_id, note_id

#: The word the model reports → the number the review screen sorts on.
CONFIDENCE_VALUE = {Confidence.HIGH: 1.0, Confidence.MEDIUM: 0.6, Confidence.LOW: 0.3}


class Page:
    """One extracted page of an import job, with the file it came from."""

    def __init__(self, result: ExtractionResult, *, number: int | None = None, file: str | None = None):
        self.result = result
        self.number = number
        self.file = file


def _clean(value: str | None) -> str | None:
    """Trim and drop footnote markers the extractor may have left behind."""
    if value is None:
        return None
    text = unicodedata.normalize("NFC", value).strip()
    text = re.sub(r"[¹²³⁰-₟]+$", "", text).strip()
    return text or None


def _dedupe_key(front: str | None, back: str | None) -> tuple[str, str]:
    """Same front *and* back means the same note, ignoring case and spacing."""

    def norm(v: str | None) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", v or "")).strip().casefold()

    return norm(front), norm(back)


def _accept_list(values: list[str], displayed: str | None) -> list[str] | None:
    """Keep only explicit alternatives that add something to the displayed answer."""
    shown = _dedupe_key(displayed, None)[0]
    out: list[str] = []
    for value in values:
        cleaned = _clean(value)
        if not cleaned or _dedupe_key(cleaned, None)[0] == shown:
            continue
        if cleaned not in out:
            out.append(cleaned)
    return out or None


def _note_from_item(
    item: ExtractedItem,
    *,
    page: int | None,
    default_type: NoteType,
) -> Note:
    front = _clean(item.front)
    back = _clean(item.back)
    accept_front = _accept_list(item.front_accepted, front)
    accept_back = _accept_list(item.back_accepted, back)
    accept = Accept(front=accept_front, back=accept_back) if (accept_front or accept_back) else None
    return Note(
        id=note_id(),
        type=default_type,
        front=front,
        back=back,
        accept=accept,
        note=_clean(item.note),
        group=item.group or None,
        status=NoteStatus.UNVERIFIED,
        confidence=CONFIDENCE_VALUE.get(item.confidence),
        page=page,
    )


def _label(native: str | None, translated: str | None, native_lang: str) -> dict[str, str] | None:
    """A label is a language map, so the native side is keyed by its language code."""
    pairs = ((native_lang, _clean(native)), ("en", _clean(translated)))
    label = {k: v for k, v in pairs if v is not None}
    return label or None


def _title(result: ExtractionResult | None, context: dict[str, Any] | None) -> str | None:
    """One plain line: the number of the innermost printed level, then the page's
    own title, then the English of it — ``"2-1 · 어휘와 표현 · Vocabulary & Expressions"``.

    A file has a single name (PLAN 3.1), so the parts are joined here rather than
    kept as a language map and joined again by whatever displays it.
    """
    if result is None:
        return None
    # Context is ordered outermost first, so the last number printed is the most specific.
    number = next((v["number"] for v in reversed(list((context or {}).values())) if v.get("number")), None)
    parts = [number, _clean(result.title_native), _clean(result.title_translated)]
    return " · ".join(dict.fromkeys(p for p in parts if p)) or None


def _context(pages: list[Page], native_lang: str) -> dict[str, Any] | None:
    """Hierarchy printed on the pages, first sighting wins (PLAN 4: carry across breaks)."""
    context: dict[str, Any] = {}
    for page in pages:
        for entry in page.result.context:
            key = (entry.kind or "level").strip().lower() or "level"
            if key in context:
                continue
            value = _label(entry.native, entry.translated, native_lang) or {}
            number = _clean(entry.number)
            if number is not None:
                value = {"number": number, **value}
            if value:
                context[key] = value
    return context or None


def to_datafile(
    pages: list[Page],
    *,
    profile: str | None = None,
    model: str | None = None,
    prompt_version: int | None = None,
    job: str | None = None,
    default_type: NoteType = NoteType.BIDIRECTIONAL,
    front_lang: str | None = None,
    back_lang: str | None = None,
    source_kind: str = "image",
    at: datetime | None = None,
) -> DataFile:
    """Merge extracted pages into one data file, in page order."""
    native_lang = front_lang or "native"
    groups: list[Group] = []
    seen_groups: set[str] = set()
    notes: list[Note] = []
    seen_notes: set[tuple[str, str]] = set()
    unreadable: list[str] = []

    for page in pages:
        for group in page.result.groups:
            key = (group.key or "").strip()
            if not key or key in seen_groups:
                continue
            seen_groups.add(key)
            groups.append(
                Group(id=key, label=_label(group.label_native, group.label_translated, native_lang))
            )

        for item in page.result.items:
            note = _note_from_item(item, page=page.number, default_type=default_type)
            key = _dedupe_key(note.front, note.back)
            if key in seen_notes and key != ("", ""):
                continue  # same pair twice in one job — an overlap between photos
            seen_notes.add(key)
            if note.group and note.group not in seen_groups:
                note.group = None  # a group reference we never saw a heading for
            notes.append(note)

        unreadable.extend(u for u in page.result.unreadable if u)

    first = pages[0].result if pages else None
    context = _context(pages, native_lang)
    title = _title(first, context)
    files = [p.file for p in pages if p.file]
    page_numbers = [p.number for p in pages if p.number is not None]

    return DataFile(
        id=datafile_id(),
        title=title,
        default_type=default_type,
        front_lang=front_lang,
        back_lang=back_lang,
        source=Source(
            kind=source_kind,
            files=files or None,
            page=page_numbers[0] if len(page_numbers) == 1 else None,
            context=context,
            import_=ImportInfo(
                profile=profile,
                model=model,
                prompt_version=prompt_version,
                at=(at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
                job_id=job,
            ),
        ),
        groups=groups,
        notes=notes,
        extra={"unreadable": unreadable} if unreadable else None,
    )
