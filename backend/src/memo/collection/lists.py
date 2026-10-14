"""A named set of words, and a dated focus on it (PLAN 6, phase 4).

A mark on a note says "this word matters", for ever and everywhere. A test says
"these twenty words matter until Friday", and the two are not the same thing —
which is why using the mark for a test leaves sediment, and how a collection
ends up with more than half its words marked and the mark meaning nothing.

A list is a **selection, not a place**. The notes stay in the lesson they were
extracted from, keep their own marks and keep their history; nothing is moved
and nothing is copied. That is also what makes it safe: a list cannot reach the
scheduler, because what a list changes is the order of a queue, and the order of
a queue is never written down.

The focus is the half that expires. While ``focus_until`` is ahead, the list's
words are pushed up the queue; once it passes they stop, with nothing to
remember to undo. The list outlives its focus on purpose — what was on a test is
worth keeping, and worth being able to drill again.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

# The same sentinel the category editor uses: "the caller said nothing" has to be
# distinguishable from "the caller said null", because ending a focus *is*
# setting ``focus_until`` to null.
from memo.collection.categories import UNSET
from memo.db.models import DataFileRow, NoteGroup, Profile, WordList, WordListNote
from memo.db.models import Note as NoteRow
from memo.models.ids import new_id


@dataclass(slots=True)
class ListView:
    """One list as the screens show it, with its focus already judged."""

    id: str
    name: str
    note: str | None
    focus_until: datetime | None
    #: True only while ``focus_until`` is still ahead. A list whose date has gone
    #: by is not focused and never silently becomes focused again.
    focused: bool
    #: How many words are on it.
    count: int
    created_at: datetime


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def get_list(session: Session, profile: Profile, list_id: str) -> WordList:
    """One list of this profile's, or :class:`KeyError`."""
    found = session.get(WordList, list_id)
    if found is None or found.profile_id != profile.id:
        raise KeyError(f"no such list: {list_id}")
    return found


def view(word_list: WordList, *, words: int | None = None, now: datetime | None = None) -> ListView:
    until = word_list.focus_until
    return ListView(
        id=word_list.id,
        name=word_list.name,
        note=word_list.note,
        focus_until=until,
        focused=until is not None and until > _now(now),
        count=len(word_list.notes) if words is None else words,
        created_at=word_list.created_at,
    )


def all_lists(session: Session, profile: Profile, *, now: datetime | None = None) -> list[ListView]:
    """Every list, focused ones first, then the most recently made.

    Counted in one query rather than by walking each list's rows, because this is
    what the Collection page asks for on every visit.
    """
    # ``.all()`` because ``dict(result)`` would take the mapping protocol — a
    # Result has ``keys()`` — and then try to subscript the result set.
    counts = dict(
        session.execute(
            select(WordListNote.list_id, func.count())
            .join(WordList, WordList.id == WordListNote.list_id)
            .where(WordList.profile_id == profile.id)
            .group_by(WordListNote.list_id)
        ).all()
    )
    found = [
        view(row, words=counts.get(row.id, 0), now=now)
        for row in session.scalars(select(WordList).where(WordList.profile_id == profile.id))
    ]
    found.sort(key=lambda item: (not item.focused, -item.created_at.timestamp()))
    return found


def create_list(
    session: Session,
    profile: Profile,
    *,
    name: str,
    note: str | None = None,
    focus_until: datetime | None = None,
) -> WordList:
    name = (name or "").strip()
    if not name:
        raise ValueError("a list needs a name")
    clash = session.scalar(select(WordList).where(WordList.profile_id == profile.id, WordList.name == name))
    if clash is not None:
        raise ValueError(f"there is already a list called {name!r}")
    row = WordList(id=new_id("wl"), profile_id=profile.id, name=name, note=note, focus_until=focus_until)
    session.add(row)
    session.flush()
    return row


def update_list(
    session: Session,
    profile: Profile,
    list_id: str,
    *,
    name: str | object = UNSET,
    note: str | None | object = UNSET,
    focus_until: datetime | None | object = UNSET,
) -> WordList:
    """Rename a list, re-date its focus, or end it.

    ``focus_until=None`` ends the focus now; leaving it out keeps whatever it was.
    """
    row = get_list(session, profile, list_id)
    if name is not UNSET:
        wanted = str(name).strip()
        if not wanted:
            raise ValueError("a list needs a name")
        clash = session.scalar(
            select(WordList).where(
                WordList.profile_id == profile.id, WordList.name == wanted, WordList.id != row.id
            )
        )
        if clash is not None:
            raise ValueError(f"there is already a list called {wanted!r}")
        row.name = wanted
    if note is not UNSET:
        row.note = note  # type: ignore[assignment]
    if focus_until is not UNSET:
        row.focus_until = focus_until  # type: ignore[assignment]
    session.flush()
    return row


def delete_list(session: Session, profile: Profile, list_id: str) -> None:
    """Forget the set. The words, their marks and their history are untouched."""
    session.delete(get_list(session, profile, list_id))
    session.flush()


def _wanted(
    session: Session,
    *,
    note_ids: Iterable[str] | None,
    file_id: str | None,
    group: str | None,
) -> list[str]:
    """The notes an add refers to, in the collection's own order.

    A whole lesson or a single heading can be named instead of twenty ids, which
    is the one bulk gesture this app has: a heading is already a set you think in
    — it is how the textbook prints them, and practice can already take one on
    its own.
    """
    if note_ids is not None:
        found = list(dict.fromkeys(note_ids))
        if file_id is not None or group is not None:
            raise ValueError("name notes, or a lesson, not both")
        known = set(
            session.scalars(select(NoteRow.id).where(NoteRow.id.in_(found), NoteRow.archived_at.is_(None)))
        )
        missing = [one for one in found if one not in known]
        if missing:
            raise KeyError(f"no such note: {missing[0]}")
        return found
    if file_id is None:
        raise ValueError("name some notes, or a lesson")
    query = (
        select(NoteRow.id)
        .join(DataFileRow, NoteRow.data_file_id == DataFileRow.id)
        .where(NoteRow.data_file_id == file_id, NoteRow.archived_at.is_(None))
        .order_by(NoteRow.position)
    )
    if group is not None:
        query = query.join(NoteGroup, NoteRow.group_id == NoteGroup.id).where(NoteGroup.key == group)
    found = list(session.scalars(query))
    if not found:
        raise KeyError(f"no notes in {file_id}" + (f" under {group!r}" if group else ""))
    return found


def add_notes(
    session: Session,
    profile: Profile,
    list_id: str,
    *,
    note_ids: Sequence[str] | None = None,
    file_id: str | None = None,
    group: str | None = None,
) -> tuple[WordList, int]:
    """Put words on a list, and say how many were not already on it.

    Adding something twice is not an error — half the point of searching for a
    word is that you cannot remember whether you dealt with it already.
    """
    row = get_list(session, profile, list_id)
    wanted = _wanted(session, note_ids=note_ids, file_id=file_id, group=group)
    already = {member.note_id for member in row.notes}
    position = max((member.position for member in row.notes), default=-1)
    added = 0
    for note in wanted:
        if note in already:
            continue
        position += 1
        session.add(WordListNote(list_id=row.id, note_id=note, position=position))
        added += 1
    session.flush()
    session.refresh(row)
    return row, added


def remove_note(session: Session, profile: Profile, list_id: str, note_id: str) -> WordList:
    row = get_list(session, profile, list_id)
    session.execute(
        delete(WordListNote).where(WordListNote.list_id == row.id, WordListNote.note_id == note_id)
    )
    session.flush()
    session.refresh(row)
    return row


def members(session: Session, profile: Profile, list_id: str) -> list[str]:
    """The note ids on a list, in the order they were added."""
    row = get_list(session, profile, list_id)
    return [member.note_id for member in row.notes]


def focused(session: Session, profile: Profile, *, now: datetime | None = None) -> set[str]:
    """Note ids on any list whose focus has not yet passed.

    A union, because two tests can be coming at once and there is no reason for
    the second one to have to wait. Empty when nothing is focused, and the queue
    then behaves exactly as it did before lists existed.
    """
    return set(
        session.scalars(
            select(WordListNote.note_id)
            .join(WordList, WordList.id == WordListNote.list_id)
            .where(WordList.profile_id == profile.id, WordList.focus_until > _now(now))
        )
    )


def focus_names(session: Session, profile: Profile, *, now: datetime | None = None) -> dict[str, str]:
    """``note id → the name of the focused list it is on``, for a card to show.

    A card pushed up by a focus should say *why* — "Friday test" is the honest
    label, where a priority chip reading ``high`` would be describing the session
    and lying about the setting. First list wins when a word is on two.
    """
    found: dict[str, str] = {}
    for note_id, name in session.execute(
        select(WordListNote.note_id, WordList.name)
        .join(WordList, WordList.id == WordListNote.list_id)
        .where(WordList.profile_id == profile.id, WordList.focus_until > _now(now))
        .order_by(WordList.created_at)
    ):
        found.setdefault(note_id, name)
    return found
