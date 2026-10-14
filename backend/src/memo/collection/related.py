"""Other words in the collection that have something to do with this one.

Built entirely out of what is already written down, which decides what it can
honestly offer. The collection records what a word *means*, so words that mean
the same thing, or nearly the same thing, fall straight out of it — and so does
whether the two already accept each other, which is the thing worth fixing when
they do not.

**It cannot offer antonyms.** Nothing in a note says that one word is the
opposite of another, and inventing the relation would mean asking a model about
Korean and presenting the answer as the collection's own. What stands in for it
is *the same heading*: a textbook prints 위 and 밑 under one heading precisely
because they are a pair, so the heading carries the relation the data does not.

The matching is :mod:`memo.collection.audit`'s, down to :func:`~.audit.bare`, so
"nearly the same gloss" means here exactly what it means in a report. The
difference is the purpose: an audit says what is broken, this says what is
nearby. Suspended words are included — a word you set aside still means what it
meant, and saying so is how you find out why you set it aside.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from memo.collection.audit import bare
from memo.collection.editing import normalise
from memo.db.models import DataFileRow, NoteGroup
from memo.db.models import Note as NoteRow

#: Why two words are put beside each other, strongest first.
SAME_MEANING = "same-meaning"
NEAR_MEANING = "near-meaning"
SAME_HEADING = "same-heading"
REASONS = (SAME_MEANING, NEAR_MEANING, SAME_HEADING)

#: At most this many words from the same heading. A heading is three to eight
#: words in a textbook, but nothing stops one being thirty, and thirty words is
#: a lesson rather than a hint.
HEADING_LIMIT = 8


@dataclass(slots=True)
class Related:
    """One other word, and what it has to do with the one asked about."""

    note_id: str
    front: str | None
    back: str | None
    data_file_id: str
    file_title: str | None
    group: dict[str, str] | None
    group_key: str | None
    suspended: bool
    #: One of :data:`REASONS`.
    how: str
    #: This word takes the other's spelling as an answer.
    accepts: bool
    #: The other takes this word's spelling.
    accepted_by: bool

    @property
    def one_sided(self) -> bool:
        """Only one of them accepts the other, so one direction still fails."""
        return self.accepts != self.accepted_by


def _takes(accept: dict | None, front: str | None) -> bool:
    """True when typing ``front`` would be taken as an answer by that note."""
    wanted = normalise(front)
    if not wanted:
        return False
    return wanted in {normalise(one) for one in (accept or {}).get("front") or ()}


def related(session: Session, note_id: str) -> list[Related]:
    """Words beside this one, closest relation first.

    A word is listed once, under the strongest reason it qualifies for, so a
    heading-mate that also shares the gloss reads as *same meaning* rather than
    being mentioned twice.
    """
    note = session.get(NoteRow, note_id)
    if note is None:
        raise KeyError(f"no such note: {note_id}")

    rows = session.execute(
        select(NoteRow, DataFileRow, NoteGroup)
        .join(DataFileRow, NoteRow.data_file_id == DataFileRow.id)
        .outerjoin(NoteGroup, NoteRow.group_id == NoteGroup.id)
        .where(
            NoteRow.id != note.id,
            NoteRow.archived_at.is_(None),
            DataFileRow.archived_at.is_(None),
        )
        .order_by(DataFileRow.position, NoteRow.position)
    )

    gloss = normalise(note.back)
    nearly = bare(note.back)
    heading = note.group_id
    found: list[Related] = []
    from_heading = 0
    for other, file, group in rows:
        if gloss and normalise(other.back) == gloss:
            how = SAME_MEANING
        elif nearly and bare(other.back) == nearly:
            how = NEAR_MEANING
        elif heading is not None and other.group_id == heading:
            if from_heading >= HEADING_LIMIT:
                continue
            from_heading += 1
            how = SAME_HEADING
        else:
            continue
        found.append(
            Related(
                note_id=other.id,
                front=other.front,
                back=other.back,
                data_file_id=file.id,
                file_title=file.title,
                group=group.label if group is not None else None,
                group_key=group.key if group is not None else None,
                suspended=bool(other.suspended),
                how=how,
                accepts=_takes(note.accept, other.front),
                accepted_by=_takes(other.accept, note.front),
            )
        )

    # Within a reason the collection's own order is kept, which the query set.
    found.sort(key=lambda one: REASONS.index(one.how))
    return found
