"""Making and changing the collection by hand (PLAN 6, phase 2).

The grid editor lands here. The import review screen keeps its own path: it
edits a draft data file as JSON and only becomes rows when it is committed.

Deleting is archiving (``archived_at``): a note that has been practised keeps
its cards, its state and its place in the append-only log, and simply stops
appearing in practice, counts and exports.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from memo.collection.store import sync_cards
from memo.db.models import Category, DataFileRow, NoteGroup
from memo.db.models import Note as NoteRow
from memo.models.datafile import NORMAL, NoteType, Priority
from memo.models.ids import new_id, note_id

#: Fields of a note the editor may set; everything else is importer territory.
NOTE_FIELDS = frozenset(
    {
        "type",
        "front",
        "back",
        "front_lang",
        "back_lang",
        "fields",
        "accept",
        "modes",
        "note",
        "tags",
        "status",
        "confidence",
        "suspended",
        "priority",
        "page",
        "extra",
    }
)

FILE_FIELDS = frozenset({"title", "default_type", "front_lang", "back_lang", "tags", "slug", "extra"})


#: Every dash a printed page might use, folded to a plain hyphen, and the soft
#: hyphen dropped because it is invisible. Same set as ``spec/answer-check.md``
#: §1.2 — U+30FC stays out of it, being a letter in Japanese.
DASHES = {cp: "-" for cp in (*range(0x2010, 0x2016), 0x2043, 0x2212, 0x2E3A, 0x2E3B, 0xFE58, 0xFE63, 0xFF0D)}
DASHES[0x00AD] = None


def normalise(text: str | None) -> str:
    """The form two notes are compared in: NFC, dashes folded, case-folded, whitespace collapsed.

    Deliberately blunter than the answer checker (``spec/answer-check.md``):
    this decides whether to *warn* about a duplicate, not whether an answer is
    right, so it may not silently drop markup that the two notes differ by.

    Dashes are the one thing it folds the same way the checker does: a page
    that prints ``–씨`` and a row you typed as ``-씨`` are the same card, and
    nobody should have to notice which dash the model transcribed.
    """
    folded = unicodedata.normalize("NFC", text or "").translate(DASHES)
    return " ".join(folded.split()).casefold()


def file_default_type(file: DataFileRow) -> NoteType:
    return NoteType(file.default_type) if file.default_type else NoteType.DIRECTIONAL


def live_notes(file: DataFileRow) -> list[NoteRow]:
    return [n for n in file.notes if n.archived_at is None]


# --- data files -------------------------------------------------------------


def create_file(
    session: Session,
    category: Category,
    *,
    title: str | None = None,
    front_lang: str | None = None,
    back_lang: str | None = None,
    default_type: str | None = None,
    slug: str | None = None,
) -> DataFileRow:
    """An empty data file to type notes into."""
    position = (
        session.scalar(select(func.max(DataFileRow.position)).where(DataFileRow.category_id == category.id))
        or 0
    )
    row = DataFileRow(
        id=new_id("df"),
        category_id=category.id,
        slug=slug,
        title=title or None,
        default_type=default_type,
        front_lang=front_lang,
        back_lang=back_lang,
        position=position + 1,
    )
    session.add(row)
    session.flush()
    return row


def update_file(session: Session, file: DataFileRow, patch: Mapping[str, Any]) -> DataFileRow:
    unknown = set(patch) - FILE_FIELDS - {"category_id"}
    if unknown:
        raise ValueError(f"cannot set {', '.join(sorted(unknown))} on a data file")
    if "category_id" in patch:
        category = session.get(Category, patch["category_id"])
        if category is None:
            raise ValueError(f"no such category: {patch['category_id']}")
        file.category_id = category.id
    retype = "default_type" in patch and patch["default_type"] != file.default_type
    for key in patch.keys() & FILE_FIELDS:
        setattr(file, key, patch[key])
    if retype:
        # The file's default decides how many cards a note without its own type has.
        for note in live_notes(file):
            sync_cards(session, note, file_default_type(file))
    session.flush()
    return file


def archive_file(session: Session, file: DataFileRow, *, archived: bool = True) -> DataFileRow:
    """Archive (or restore) a file and every note in it, in one move."""
    at = datetime.now(UTC) if archived else None
    file.archived_at = at
    for note in file.notes:
        note.archived_at = at
    session.flush()
    return file


# --- groups -----------------------------------------------------------------


def ensure_group(
    session: Session, file: DataFileRow, key: str, *, label: dict[str, str] | None = None
) -> NoteGroup:
    """A heading inside the file, created on first use by the grid's group column."""
    key = key.strip()
    if not key:
        raise ValueError("a group needs a key")
    row = session.scalar(select(NoteGroup).where(NoteGroup.data_file_id == file.id, NoteGroup.key == key))
    if row is None:
        position = session.scalar(
            select(func.max(NoteGroup.position)).where(NoteGroup.data_file_id == file.id)
        )
        row = NoteGroup(
            id=new_id("g"),
            data_file_id=file.id,
            key=key,
            label=label,
            position=(position or 0) + 1,
        )
        session.add(row)
        session.flush()
    elif label:
        row.label = {**(row.label or {}), **label}
    return row


def update_group(session: Session, group: NoteGroup, patch: Mapping[str, Any]) -> NoteGroup:
    for key in patch.keys() & {"label", "note", "key"}:
        setattr(group, key, patch[key])
    session.flush()
    return group


# --- notes ------------------------------------------------------------------


def _apply(session: Session, row: NoteRow, file: DataFileRow, patch: Mapping[str, Any]) -> None:
    unknown = set(patch) - NOTE_FIELDS - {"group"}
    if unknown:
        raise ValueError(f"cannot set {', '.join(sorted(unknown))} on a note")
    for key in patch.keys() & NOTE_FIELDS:
        value = patch[key]
        if key == "type" and value is not None:
            value = NoteType(value).value
        if key == "priority" and value is not None:
            # The control has three buttons and the middle one is the absence of a
            # mark, so "normal" arrives as a word and is stored as nothing.
            value = None if value == NORMAL else Priority(value).value
        setattr(row, key, value)
    if "group" in patch:
        key = (patch["group"] or "").strip()
        row.group_id = ensure_group(session, file, key).id if key else None


def create_notes(session: Session, file: DataFileRow, items: Sequence[Mapping[str, Any]]) -> list[NoteRow]:
    """Append notes to ``file`` in the order given; blank rows are the caller's problem."""
    position = session.scalar(select(func.max(NoteRow.position)).where(NoteRow.data_file_id == file.id))
    position = position or 0
    default_type = file_default_type(file)
    created: list[NoteRow] = []
    for item in items:
        position += 1
        row = NoteRow(id=note_id(), data_file_id=file.id, position=position)
        session.add(row)
        _apply(session, row, file, item)
        session.flush()
        sync_cards(session, row, default_type)
        created.append(row)
    session.flush()
    return created


def update_note(session: Session, note: NoteRow, patch: Mapping[str, Any]) -> NoteRow:
    _apply(session, note, note.data_file, patch)
    session.flush()
    sync_cards(session, note, file_default_type(note.data_file))
    session.flush()
    return note


def archive_note(session: Session, note: NoteRow, *, archived: bool = True) -> NoteRow:
    note.archived_at = datetime.now(UTC) if archived else None
    session.flush()
    return note


def reorder_notes(session: Session, file: DataFileRow, note_ids: Sequence[str]) -> None:
    """Put ``note_ids`` in that order first; notes not named keep their order after."""
    order = {note_id: index for index, note_id in enumerate(note_ids)}
    tail = len(order)
    ordered = sorted(file.notes, key=lambda n: (order.get(n.id, tail), n.position))
    for position, note in enumerate(ordered):
        note.position = position
    session.flush()


# --- duplicates -------------------------------------------------------------


@dataclass(slots=True)
class Duplicate:
    """An existing note that a row being typed or imported looks like."""

    note_id: str
    front: str | None
    back: str | None
    data_file_id: str
    file_title: str | None
    category_id: str
    category_path: str
    #: True when the back matches too — the same note, not just the same prompt.
    same_back: bool
    #: Which side matched. ``"back"`` is the awkward one: a different word with
    #: the same meaning, which makes that meaning an unanswerable prompt in the
    #: reverse direction unless the two accept each other.
    by: str = "front"


def _accepts(note: NoteRow, front: str) -> bool:
    """True when typing ``front`` (already normalised) is taken as an answer here."""
    alternatives = (note.accept or {}).get("front") or []
    return front in {normalise(text) for text in alternatives}


def find_duplicates(
    session: Session,
    pairs: Iterable[tuple[str | None, str | None]],
    *,
    category_id: str | None = None,
    exclude_note_ids: Iterable[str] = (),
) -> dict[int, list[Duplicate]]:
    """Which of ``pairs`` already exist, by front *or* by back (PLAN 6, phase 2).

    The whole tree is searched unless ``category_id`` narrows it, because a word
    learned twice under two books is exactly the case worth knowing about.

    A **front** match is the same prompt: the same note if the back agrees
    (``same_back``), a clash if it does not. A **back** match is the same
    meaning on a different word, which is the one an extractor makes by
    accident — asked what 그게 means it says "that", exactly as it does for 그것,
    and the reverse direction then has two right answers. It is not reported
    when the existing note already accepts the front being typed, since the two
    are then deliberate alternatives rather than an ambiguity.
    """
    wanted: dict[str, list[int]] = {}
    by_gloss: dict[str, list[int]] = {}
    fronts: dict[int, str] = {}
    backs: dict[int, str] = {}
    for index, (front, back) in enumerate(pairs):
        key = normalise(front)
        if not key:
            continue
        wanted.setdefault(key, []).append(index)
        fronts[index] = key
        backs[index] = normalise(back)
        if backs[index]:
            by_gloss.setdefault(backs[index], []).append(index)
    if not wanted:
        return {}

    query = (
        select(NoteRow, DataFileRow, Category)
        .join(DataFileRow, NoteRow.data_file_id == DataFileRow.id)
        .join(Category, DataFileRow.category_id == Category.id)
        .where(NoteRow.archived_at.is_(None), DataFileRow.archived_at.is_(None))
    )
    if category_id is not None:
        category = session.get(Category, category_id)
        if category is None:
            raise KeyError(f"no such category: {category_id}")
        ids = select(Category.id).where(
            or_(Category.path == category.path, Category.path.like(f"{category.path}/%"))
        )
        query = query.where(DataFileRow.category_id.in_(ids))

    skip = set(exclude_note_ids)
    found: dict[int, list[Duplicate]] = {}
    # A scan: the collection is one person's, and normalisation has no SQL equivalent.
    for note, file, category in session.execute(query):
        if note.id in skip:
            continue
        front = normalise(note.front)
        back = normalise(note.back)
        hits = [(index, "front") for index in wanted.get(front, ())]
        already = {index for index, _ in hits}
        hits += [
            (index, "back")
            for index in by_gloss.get(back, ())
            if index not in already and fronts[index] != front and not _accepts(note, fronts[index])
        ]
        for index, by in hits:
            found.setdefault(index, []).append(
                Duplicate(
                    note_id=note.id,
                    front=note.front,
                    back=note.back,
                    data_file_id=file.id,
                    file_title=file.title,
                    category_id=category.id,
                    category_path=category.path,
                    same_back=back == backs[index],
                    by=by,
                )
            )
    return found


__all__ = [
    "Duplicate",
    "archive_file",
    "archive_note",
    "create_file",
    "create_notes",
    "ensure_group",
    "file_default_type",
    "find_duplicates",
    "live_notes",
    "normalise",
    "reorder_notes",
    "update_file",
    "update_group",
    "update_note",
]
