"""Edits the practice screen can make to a note."""

from __future__ import annotations

import unicodedata

from sqlalchemy.orm import Session

from memo.db.models import Note as NoteRow

SIDES = ("front", "back")


def add_accepted(session: Session, note_id: str, side: str, value: str) -> list[str]:
    """ "That's the same thing" (PLAN 3.5): the collection improves as it is used.

    Adds ``value`` to the note's explicit accept list for ``side`` and returns
    the list. A value already there, or equal to the displayed text, is a no-op.
    """
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}")
    note = session.get(NoteRow, note_id)
    if note is None:
        raise KeyError(f"no such note: {note_id}")

    cleaned = unicodedata.normalize("NFC", value).strip()
    accept = dict(note.accept or {})
    current = list(accept.get(side) or [])
    shown = getattr(note, side) or ""
    if cleaned and cleaned not in current and cleaned.casefold() != shown.strip().casefold():
        current.append(cleaned)
        accept[side] = current
        note.accept = accept  # reassign so SQLAlchemy sees the JSON change
        session.flush()
    return current
