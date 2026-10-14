"""Finding a word again, by any of the words it is written with.

Until this existed the only way to a note was Collection → category → file →
read a fifty-six-row grid, because ``GET /files/{id}/notes`` was the whole
note-reading API. That is tolerable while a collection is one lesson and
absurd at two hundred words, and it is why marking twenty words for a test
meant hand-writing a patch file full of ids the screen never shows.

A **scan**, for the reason :func:`memo.collection.editing.find_duplicates`
already gives for scanning: the collection is one person's, and
:func:`~memo.collection.editing.normalise` has no SQL equivalent. Two hundred
notes cost nothing, and an index would be a second thing to keep true.

It searches everything, suspended and archived included. Hiding suspended notes
is the entire job of ``_practisable()``, and that is exactly why a word you set
aside used to be unfindable; a search that repeated the omission would be no
use at the one moment you need it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from memo.collection.editing import normalise
from memo.db.models import Card, Category, DataFileRow, NoteGroup, Profile
from memo.db.models import Note as NoteRow
from memo.models.datafile import NORMAL, Direction
from memo.overview.progress import BUCKETS, NEW, standings, weakest

#: Where a hit came from. Not itself the ranking — see :data:`TIER`.
WHERE = ("front", "back", "accept", "note", "group", "file")

#: How a match sits inside the field it matched: the whole of it, its start, or
#: somewhere in the middle. Best first.
HOW = ("exact", "prefix", "part")

#: What kind of thing matched: the word itself, a spelling it also answers to,
#: or something written *about* it. Ranking goes by tier **before** exactness,
#: and by exactness before which side of the pair it was — so an exact 아래 and
#: an exact "under" rank together, both ahead of a word merely containing
#: either, and a file title (which would otherwise drag in all thirty-two of
#: its notes) comes last however exactly it matches.
TIER = {"front": 0, "back": 0, "accept": 1, "note": 2, "group": 2, "file": 3}


def _rank(where: str, how: str) -> tuple[int, int, int]:
    """How good a hit this is, lowest first."""
    return TIER[where], HOW.index(how), WHERE.index(where)


@dataclass(slots=True)
class Hit:
    """One note as a result lists it — a word, not a direction.

    Note-shaped on purpose. A card is one way round and a search result is the
    word you were looking for, so both sides are here and the row decides which
    leads. ``forward`` and ``reverse`` carry the two cards' standings, which is
    the only part of a hit that comes from the review log.
    """

    note_id: str
    front: str
    back: str
    accept: dict[str, list[str]] | None
    note: str | None
    priority: str
    suspended: bool
    archived: bool
    data_file_id: str
    file_title: str | None
    category_id: str
    category_path: str
    group: dict[str, str] | None
    group_key: str | None
    forward: str | None
    reverse: str | None
    #: Which field matched, from :data:`WHERE`, and how, from :data:`HOW`.
    #: Both null for a word fetched by id rather than found — a list's own
    #: words are the same shape as results, but they matched nothing.
    where: str | None
    how: str | None


def _how(field: str, needle: str) -> str | None:
    """Whether ``needle`` is the whole of ``field``, its start, or inside it."""
    if not field or not needle:
        return None
    if field == needle:
        return "exact"
    if field.startswith(needle):
        return "prefix"
    return "part" if needle in field else None


def _best(
    candidates: Iterable[tuple[str, str | None]],
) -> tuple[str, str] | None:
    """The strongest ``(where, how)`` among the places a note matched."""
    found = [(where, how) for where, how in candidates if how is not None]
    if not found:
        return None
    return min(found, key=lambda pair: _rank(*pair))


def _match(note: NoteRow, file: DataFileRow, group: NoteGroup | None, needle: str) -> tuple[str, str] | None:
    """Where and how this note answers to ``needle``, or ``None``.

    Every side of a note is searched, not only the two printed ones: the
    spellings it also accepts are how 미국 is found by typing "america", and the
    free-text note is where the collection keeps its prose asides ("누구+가 →
    누가"), which are otherwise unreachable by any screen.
    """
    places: list[tuple[str, str | None]] = [
        ("front", _how(normalise(note.front), needle)),
        ("back", _how(normalise(note.back), needle)),
        ("note", _how(normalise(note.note), needle)),
        ("file", _how(normalise(file.title), needle)),
    ]
    for texts in (note.accept or {}).values():
        places += [("accept", _how(normalise(text), needle)) for text in texts or ()]
    if group is not None:
        # The key as well as the labels: it is what a heading is shown by when it
        # has no label, so it is also what someone would type to find one.
        labels = [group.key, *(group.label or {}).values()]
        places += [("group", _how(normalise(text), needle)) for text in labels]
    return _best(places)


def _rows(*, archived: bool) -> Select:
    """Every note with the four things a hit needs beside it."""
    query = (
        select(NoteRow, DataFileRow, Category, NoteGroup)
        .join(DataFileRow, NoteRow.data_file_id == DataFileRow.id)
        .join(Category, DataFileRow.category_id == Category.id)
        .outerjoin(NoteGroup, NoteRow.group_id == NoteGroup.id)
        .order_by(DataFileRow.position, NoteRow.position)
    )
    if not archived:
        query = query.where(NoteRow.archived_at.is_(None), DataFileRow.archived_at.is_(None))
    return query


def _standings_of(session: Session, profile: Profile) -> dict[str, dict[str, str]]:
    """``note id → {direction: bucket}``, for every note with cards."""
    where = standings(session, profile)
    found: dict[str, dict[str, str]] = {}
    for note_id, direction, key in session.execute(select(Card.note_id, Card.direction, Card.key)):
        found.setdefault(note_id, {})[direction] = where.get(key, NEW)
    return found


def _hit(
    note: NoteRow,
    file: DataFileRow,
    category: Category,
    group: NoteGroup | None,
    by_direction: dict[str, str],
    *,
    where: str | None = None,
    how: str | None = None,
) -> Hit:
    return Hit(
        note_id=note.id,
        front=note.front,
        back=note.back,
        accept=note.accept,
        note=note.note,
        priority=note.priority or NORMAL,
        suspended=bool(note.suspended),
        archived=note.archived_at is not None,
        data_file_id=file.id,
        file_title=file.title,
        category_id=category.id,
        category_path=category.path,
        group=group.label if group is not None else None,
        group_key=group.key if group is not None else None,
        forward=by_direction.get(Direction.FWD),
        reverse=by_direction.get(Direction.REV),
        where=where,
        how=how,
    )


def by_ids(session: Session, profile: Profile, note_ids: Sequence[str]) -> list[Hit]:
    """The same shape a search result has, for words named rather than found.

    In the order given, which for a list is the order they were added, and
    archived notes included — a list keeps a word that left the collection, and
    saying so is better than the word quietly vanishing off the list.
    """
    wanted = set(note_ids)
    if not wanted:
        return []
    by_note = _standings_of(session, profile)
    found: dict[str, Hit] = {}
    for note, file, category, group in session.execute(_rows(archived=True)):
        if note.id in wanted:
            found[note.id] = _hit(note, file, category, group, by_note.get(note.id, {}))
    return [found[one] for one in note_ids if one in found]


def search(
    session: Session,
    profile: Profile,
    *,
    q: str,
    category_id: str | None = None,
    mark: str | None = None,
    standing: str | None = None,
    aside: bool | None = None,
    archived: bool = False,
    limit: int | None = 50,
    offset: int = 0,
) -> tuple[list[Hit], int]:
    """Notes matching ``q``, best first, and how many there are in all.

    ``mark`` filters on the note's own priority — ``normal`` meaning the absence
    of one, as everywhere else. ``standing`` filters on how well the word is
    known, taking a note at its *weaker* direction, because a word you can only
    read is not a word you know. ``aside`` finds, or excludes, the words left out
    of practice.

    Order is strength of match first, then the collection's own order, so two
    equally good hits read in the sequence the lesson prints them.
    """
    if mark is not None and mark != NORMAL and mark not in {"low", "high", "crucial"}:
        raise ValueError(f"no such mark: {mark!r}")
    if standing is not None and standing not in BUCKETS:
        raise ValueError(f"no such standing: {standing!r}")

    needle = normalise(q)
    if not needle:
        return [], 0

    query = _rows(archived=archived)
    if category_id is not None:
        category = session.get(Category, category_id)
        if category is None:
            raise KeyError(f"no such category: {category_id}")
        ids = select(Category.id).where(
            or_(Category.path == category.path, Category.path.like(f"{category.path}/%"))
        )
        query = query.where(DataFileRow.category_id.in_(ids))

    # Always, not only when ``standing`` filters: a hit carries how well the word
    # is known either way round, and a row that said "new" about a mastered word
    # would be worse than saying nothing. One pass over the log, as /progress pays.
    by_note = _standings_of(session, profile)

    found: list[tuple[tuple[int, int, int], Hit]] = []
    # A scan, for the reason find_duplicates gives: normalisation has no SQL form.
    for note, file, category, group in session.execute(query):
        hit = _match(note, file, group, needle)
        if hit is None:
            continue
        suspended = bool(note.suspended)
        if aside is not None and suspended != aside:
            continue
        priority = note.priority or NORMAL
        if mark is not None and priority != mark:
            continue
        by_direction = by_note.get(note.id, {})
        if standing is not None and weakest(by_direction.values()) != standing:
            continue
        place, how = hit
        found.append(
            (
                _rank(place, how),
                _hit(note, file, category, group, by_direction, where=place, how=how),
            )
        )

    # Stable, so the query's collection order survives inside one rank.
    found.sort(key=lambda pair: pair[0])
    total = len(found)
    start = max(0, offset)
    page = found[start : None if limit is None else start + limit]
    return [hit for _, hit in page], total
