"""Looking the collection over for the wonkiness an import leaves behind (PLAN 6).

Read-only, and deliberately separate from :mod:`memo.collection.editing`: that
module warns about *one row being typed*, this one asks what is already wrong
with the whole tree. Both fold text with :func:`~memo.collection.editing.normalise`,
so a finding here and a warning there mean the same thing.

The one that matters is :attr:`Report.collisions`. A note's back is the answer
in the ``fwd`` direction and the *prompt* in ``rev``, so two notes that share a
back ask the same question with two different right answers — which is not a
hard card, it is an unanswerable one. The extractor produces them honestly:
asked for the meaning of 그게 it says "that", exactly as it says for 그것.

A collision stops being a defect when the notes accept each other's fronts,
because then either answer is taken whichever one is asked. Those groups are
reported under :attr:`Report.resolved` so the report can say "I looked and this
one is deliberate" rather than going quiet.

Nothing suspended or archived is considered: practice never asks it, so it
cannot be ambiguous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from memo.collection.editing import normalise
from memo.db.models import Card, Category, DataFileRow, ReviewLog
from memo.db.models import Note as NoteRow

#: A trailing ``(…)`` on a gloss: "that (over there)" beside a plain "that" is
#: not the same question, but it is close enough that the extractor meant them
#: to be told apart and may not have managed it.
TRAILING_BRACKET = re.compile(r"\s*\([^()]*\)\s*$")


def bare(text: str | None) -> str:
    """``"that (over there)"`` → ``"that"``; the normalised form with no trailing aside."""
    return normalise(TRAILING_BRACKET.sub("", text or ""))


@dataclass(slots=True, frozen=True)
class Entry:
    """One note, as a report names it."""

    note_id: str
    front: str | None
    back: str | None
    data_file_id: str
    file_title: str | None
    category_path: str
    #: Answers recorded against either of its cards — which copy to keep.
    answers: int
    accept: dict[str, Any] | None

    def accepts(self, other: Entry) -> bool:
        """True when typing ``other``'s front would be taken as an answer here."""
        fronts = (self.accept or {}).get("front") or []
        return normalise(other.front) in {normalise(f) for f in fronts}


@dataclass(slots=True, frozen=True)
class Finding:
    """Notes that belong together in a way nobody asked for."""

    key: str
    notes: tuple[Entry, ...]


@dataclass(slots=True, frozen=True)
class Report:
    #: Notes sharing a gloss, where that gloss is therefore an unanswerable prompt.
    collisions: tuple[Finding, ...]
    #: Sharing a gloss once a trailing ``(…)`` is dropped — a hint, not a finding.
    near: tuple[Finding, ...]
    #: Same word *and* same gloss: one note learned twice, with its history split.
    duplicates: tuple[Finding, ...]
    #: A accepts B's word but B does not accept A's, so one direction still fails.
    one_sided: tuple[tuple[Entry, Entry], ...]
    #: Shared glosses that are fine, because every member accepts the others.
    resolved: tuple[Finding, ...]

    @property
    def clean(self) -> bool:
        return not (self.collisions or self.duplicates or self.one_sided)


def _answers(session: Session) -> dict[str, int]:
    """Answers per note. ``card_key`` is ``note:direction``, so the join is by key."""
    rows = session.execute(
        select(Card.note_id, func.count(ReviewLog.id))
        .join(ReviewLog, ReviewLog.card_key == Card.key)
        .group_by(Card.note_id)
    )
    return {note_id: count for note_id, count in rows}


def entries(session: Session, *, category_id: str | None = None) -> list[Entry]:
    """Every note practice would consider, in a shape a report can print."""
    query = (
        select(NoteRow, DataFileRow, Category)
        .join(DataFileRow, NoteRow.data_file_id == DataFileRow.id)
        .join(Category, DataFileRow.category_id == Category.id)
        .where(
            or_(NoteRow.suspended.is_(None), NoteRow.suspended.is_(False)),
            NoteRow.archived_at.is_(None),
            DataFileRow.archived_at.is_(None),
        )
        .order_by(DataFileRow.position, NoteRow.position)
    )
    if category_id is not None:
        category = session.get(Category, category_id)
        if category is None:
            raise KeyError(f"no such category: {category_id}")
        ids = select(Category.id).where(
            or_(Category.path == category.path, Category.path.like(f"{category.path}/%"))
        )
        query = query.where(DataFileRow.category_id.in_(ids))

    answers = _answers(session)
    return [
        Entry(
            note_id=note.id,
            front=note.front,
            back=note.back,
            data_file_id=file.id,
            file_title=file.title,
            category_path=category.path,
            answers=answers.get(note.id, 0),
            accept=note.accept,
        )
        for note, file, category in session.execute(query)
    ]


def _grouped(rows: list[Entry], key) -> list[Finding]:
    buckets: dict[str, list[Entry]] = {}
    for row in rows:
        folded = key(row)
        if folded:
            buckets.setdefault(folded, []).append(row)
    return [
        Finding(key=folded, notes=tuple(notes)) for folded, notes in sorted(buckets.items()) if len(notes) > 1
    ]


def _spellings(finding: Finding) -> int:
    """How many different words share this gloss. One means a plain duplicate."""
    return len({normalise(note.front) for note in finding.notes})


def _mutual(notes: tuple[Entry, ...]) -> bool:
    """Every note in the group takes every other one's word as an answer."""
    return all(a.accepts(b) for a in notes for b in notes if a is not b)


def audit(session: Session, *, category_id: str | None = None) -> Report:
    """What is wrong with the collection as practice would meet it."""
    rows = entries(session, category_id=category_id)

    duplicates = _grouped(rows, lambda row: f"{normalise(row.front)}\x00{normalise(row.back)}")

    # Two copies of one word are not an ambiguous prompt — both answers are the
    # same word. That is the duplicate finding above; a collision needs the
    # fronts to actually differ.
    shared = [f for f in _grouped(rows, lambda row: normalise(row.back)) if _spellings(f) > 1]
    collisions = tuple(f for f in shared if not _mutual(f.notes))
    resolved = tuple(f for f in shared if _mutual(f.notes))

    # Only worth printing when the full glosses do *not* already collide: this
    # list is for the pair the extractor tried to tell apart and nearly did.
    already = {normalise(note.back) for f in shared for note in f.notes}
    near = tuple(
        f
        for f in _grouped(rows, lambda row: bare(row.back))
        if _spellings(f) > 1 and not _mutual(f.notes) and not {normalise(n.back) for n in f.notes} & already
    )

    one_sided = tuple(
        (a, b)
        for f in shared
        for a in f.notes
        for b in f.notes
        if a is not b and a.accepts(b) and not b.accepts(a)
    )

    return Report(
        collisions=collisions,
        near=near,
        duplicates=tuple(duplicates),
        one_sided=one_sided,
        resolved=resolved,
    )


__all__ = ["Entry", "Finding", "Report", "audit", "bare", "entries"]
