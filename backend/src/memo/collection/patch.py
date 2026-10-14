"""Changing a batch of notes at once, from a file you can read before it runs.

There is no other way to do it. ``PATCH /notes/{id}`` is one note at a time and
the grid editor can only type three fields per row, while **re-importing an
edited export is not an edit at all**: ``store_datafile`` only ever inserts and
``importers/files.py`` blanks every id on the way in, so a round-tripped file
comes back as new notes with no history (PLAN 3.4 — progress belongs to the
collection the note is in). A patch goes through :func:`update_note`, the same
call the editor makes, so there is no second write path to keep honest.

The file exists so that a change to the only copy of every review can be read,
reviewed and kept beside the code that it was applied with. Four things make it
safe to point at a real collection:

* **nothing happens without ``apply=True``** — the default builds the diff and
  writes nothing;
* **every id must exist and be live**, or the whole file is refused;
* **``expect`` must match** what is there now, or the whole file is refused.
  This is what makes it safe for ``set`` to replace a field like ``accept``
  wholesale, which is what :func:`~memo.collection.editing.update_note` does;
* **the card and review-log counts are compared across the write** and a
  difference aborts the transaction. Editing text cannot change them —
  ``card_key`` is ``note:direction``, with no text in it — so if they move,
  something was understood wrongly and nothing should be kept.

A patch is idempotent: a field already holding its target value is reported as
settled and its ``expect`` is not held against it, so the same file can be run
twice without the second run looking like a conflict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memo.collection.editing import NOTE_FIELDS, update_note
from memo.db.models import Card, ReviewLog
from memo.db.models import Note as NoteRow
from memo.models.base import LenientModel

FORMAT = "memo.patch"
CURRENT_VERSION = 1


class NotePatch(LenientModel):
    """One note's worth of change."""

    id: str
    #: Current values this patch was written against. Checked, never written.
    expect: dict[str, Any] = Field(default_factory=dict)
    #: What to set, exactly as :func:`update_note` takes it — fields are
    #: replaced, not merged, so ``accept`` must be given whole.
    values: dict[str, Any] = Field(alias="set")


class Patch(LenientModel):
    format: Literal["memo.patch"] = FORMAT
    version: int = CURRENT_VERSION
    #: Why this file exists, in one line. Printed before the diff.
    why: str | None = None
    notes: list[NotePatch] = Field(default_factory=list)


@dataclass(slots=True, frozen=True)
class Change:
    note_id: str
    front: str | None
    key: str
    before: Any
    after: Any


@dataclass(slots=True)
class Report:
    changes: list[Change] = field(default_factory=list)
    #: Entries whose fields all already hold their target value.
    settled: list[str] = field(default_factory=list)
    cards: int = 0
    reviews: int = 0

    @property
    def notes(self) -> int:
        return len({change.note_id for change in self.changes})


def load_patch(path: Path) -> Patch:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != FORMAT:
        raise ValueError(f"not a {FORMAT} file: {payload.get('format')!r}")
    if payload.get("version", CURRENT_VERSION) > CURRENT_VERSION:
        raise ValueError(f"patch version {payload['version']} is newer than this build understands")
    return Patch.model_validate(payload)


def _counts(session: Session) -> tuple[int, int]:
    """Cards and review rows. Neither may move while a patch runs."""
    return (
        session.scalar(select(func.count()).select_from(Card)) or 0,
        session.scalar(select(func.count()).select_from(ReviewLog)) or 0,
    )


def _current(row: NoteRow, key: str) -> Any:
    if key == "group":
        return row.group.key if row.group else None
    return getattr(row, key)


def plan(session: Session, patch: Patch) -> tuple[Report, dict[str, NoteRow]]:
    """Work out what the patch would do, and refuse the whole file if anything is off."""
    report = Report()
    rows: dict[str, NoteRow] = {}
    problems: list[str] = []

    for entry in patch.notes:
        row = session.get(NoteRow, entry.id)
        if row is None:
            problems.append(f"{entry.id}: no such note")
            continue
        if row.archived_at is not None:
            problems.append(f"{entry.id}: archived")
            continue
        unknown = set(entry.values) - NOTE_FIELDS - {"group"}
        if unknown:
            problems.append(f"{entry.id}: cannot set {', '.join(sorted(unknown))}")
            continue
        rows[entry.id] = row

        changes = [
            Change(entry.id, row.front, key, _current(row, key), value)
            for key, value in entry.values.items()
            if _current(row, key) != value
        ]
        if not changes:
            report.settled.append(entry.id)
            continue
        # A field already holding its target is settled, so a re-run is not a
        # conflict; anything else must be what the patch was written against.
        for key, expected in entry.expect.items():
            if key in entry.values and _current(row, key) == entry.values[key]:
                continue
            found = _current(row, key)
            if found != expected:
                problems.append(f"{entry.id}: {key} is {found!r}, patch expected {expected!r}")
        report.changes.extend(changes)

    if problems:
        raise ValueError("the patch does not fit this collection:\n  " + "\n  ".join(problems))
    return report, rows


def apply_patch(session: Session, patch: Patch, *, apply: bool = False) -> Report:
    """The diff, and — only with ``apply`` — the write."""
    report, rows = plan(session, patch)
    if not apply:
        return report

    before = _counts(session)
    for entry in patch.notes:
        if entry.id in rows and entry.id not in report.settled:
            update_note(session, rows[entry.id], entry.values)
    session.flush()
    report.cards, report.reviews = _counts(session)
    if (report.cards, report.reviews) != before:
        raise RuntimeError(
            f"a patch may not add or remove cards or reviews: {before} became "
            f"{(report.cards, report.reviews)} — nothing has been kept"
        )
    return report


__all__ = ["Change", "NotePatch", "Patch", "Report", "apply_patch", "load_patch", "plan"]
