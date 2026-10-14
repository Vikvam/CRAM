"""Data file ↔ database.

Both directions are written next to each other on purpose: the round-trip test
(file → DB → file) is what keeps the DB from quietly becoming the only truth
anyone can read (PLAN 5, the risk accepted with storage option D).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memo.collection.categories import ensure_category
from memo.db.models import Card, Category, DataFileRow, NoteGroup
from memo.db.models import Note as NoteRow
from memo.models.datafile import (
    Accept,
    DataFile,
    Direction,
    Group,
    ImportInfo,
    Note,
    NoteType,
    Priority,
    Source,
)
from memo.models.ids import new_id, note_id


def card_key(note: str, direction: Direction | str) -> str:
    """PLAN 3.4: progress is keyed on this, never on a path."""
    return f"{note}:{Direction(direction).value}"


def sync_cards(session: Session, row: NoteRow, default_type: NoteType) -> None:
    """Make the note's cards match its type, without touching cards that survive.

    A note that gains a side gains a card; one that loses a side loses it, along
    with its schedule. Cards that stay keep their key, so their history stays.
    """
    note = Note(
        id=row.id,
        type=NoteType(row.type) if row.type else None,
        front=row.front,
        back=row.back,
    )
    wanted = {card_key(row.id, d) for d in note.directions(default_type)}
    existing = {card.key: card for card in row.cards}
    for key in sorted(wanted - set(existing)):
        # Through the relationship, so a caller holding the note sees its new cards.
        row.cards.append(Card(key=key, note_id=row.id, direction=key.rsplit(":", 1)[1]))
    for key in set(existing) - wanted:
        row.cards.remove(existing[key])
        session.delete(existing[key])


def _group_rows(session: Session, file_row: DataFileRow, groups: list[Group]) -> dict[str, NoteGroup]:
    """Make this file's groups. A key already in the file is reused, never doubled."""
    by_key: dict[str, NoteGroup] = {row.key: row for row in file_row.groups}
    position = max((row.position for row in file_row.groups), default=-1)
    for offset, group in enumerate(groups):
        key = (group.id or "").strip() or f"group-{offset + 1}"
        row = by_key.get(key)
        if row is not None:
            row.label = row.label or group.label
            row.note = row.note or group.note
            continue
        position += 1
        row = NoteGroup(
            id=new_id("g"),
            data_file_id=file_row.id,
            key=key,
            label=group.label,
            note=group.note,
            position=position,
            extra=group.extra,
        )
        # Through the relationship, so a caller holding the file sees them at once.
        file_row.groups.append(row)
        by_key[key] = row
    session.flush()
    return by_key


def _note_rows(
    session: Session,
    file_row: DataFileRow,
    notes: list[Note],
    groups: dict[str, NoteGroup],
    default_type: NoteType,
    *,
    start: int = 0,
) -> list[NoteRow]:
    """Insert notes in the order given, keeping any IDs they already carry."""
    rows: list[NoteRow] = []
    for offset, note in enumerate(notes):
        group_row = groups.get(note.group) if note.group else None
        row = NoteRow(
            id=note.id or note_id(),
            data_file_id=file_row.id,
            group_id=group_row.id if group_row else None,
            type=note.type.value if note.type else None,
            front=note.front,
            back=note.back,
            front_lang=note.front_lang,
            back_lang=note.back_lang,
            fields=note.fields,
            accept=note.accept.dumps() if note.accept else None,
            modes=note.modes,
            note=note.note,
            tags=note.tags,
            status=note.status.value if note.status else None,
            confidence=note.confidence,
            suspended=note.suspended,
            priority=note.priority.value if note.priority else None,
            page=note.page,
            position=start + offset,
            extra=note.extra,
        )
        file_row.notes.append(row)
        session.flush()
        sync_cards(session, row, default_type)
        rows.append(row)
    session.flush()
    return rows


def store_datafile(
    session: Session,
    datafile: DataFile,
    *,
    category_path: str,
    slug: str | None = None,
) -> DataFileRow:
    """Insert a data file under ``category_path``, assigning any missing IDs."""
    category = ensure_category(session, category_path)
    # After the files already in this category, so the queue walks the book in
    # the order the lessons arrived rather than interleaving all of them.
    position = (
        session.scalar(select(func.max(DataFileRow.position)).where(DataFileRow.category_id == category.id))
        or 0
    )
    file_row = DataFileRow(
        id=datafile.id or new_id("df"),
        category_id=category.id,
        position=position + 1,
        slug=slug,
        title=datafile.title,
        default_type=datafile.default_type.value if datafile.default_type else None,
        front_lang=datafile.front_lang,
        back_lang=datafile.back_lang,
        source=datafile.source.dumps() if datafile.source else None,
        tags=datafile.tags,
        extra=datafile.extra,
        version=datafile.version,
    )
    session.add(file_row)
    session.flush()

    groups = _group_rows(session, file_row, datafile.groups)
    _note_rows(session, file_row, datafile.notes, groups, datafile.note_default_type())
    return file_row


def append_datafile(session: Session, file_row: DataFileRow, datafile: DataFile) -> list[NoteRow]:
    """Add a second page's worth of notes to a file that already exists (PLAN 6, phase 2).

    The notes land at the end; groups with a key the file already has are joined
    rather than repeated, and the new import's provenance is kept beside the
    first one instead of overwriting it.
    """
    groups = _group_rows(session, file_row, datafile.groups)
    start = max((row.position for row in file_row.notes), default=-1) + 1
    rows = _note_rows(
        session,
        file_row,
        datafile.notes,
        groups,
        NoteType(file_row.default_type) if file_row.default_type else datafile.note_default_type(),
        start=start,
    )
    if datafile.source is not None:
        file_row.source = _merge_source(file_row.source, datafile.source)
    session.flush()
    return rows


def _merge_source(existing: dict | None, added: Source) -> dict:
    """Keep the first import as ``source``; later ones stack under ``extra.appended``."""
    if not existing:
        return added.dumps()
    merged = dict(existing)
    files = list(merged.get("files") or [])
    for name in added.files or []:
        if name not in files:
            files.append(name)
    if files:
        merged["files"] = files
    extra = dict(merged.get("extra") or {})
    appended = list(extra.get("appended") or [])
    appended.append(added.dumps())
    extra["appended"] = appended
    merged["extra"] = extra
    return merged


def export_datafile(session: Session, file_id: str) -> DataFile:
    """Rebuild the data file exactly as it was stored."""
    file_row = session.get(DataFileRow, file_id)
    if file_row is None:
        raise KeyError(f"no such data file: {file_id}")

    group_key = {group.id: group.key for group in file_row.groups}
    return DataFile(
        version=file_row.version,
        id=file_row.id,
        title=file_row.title,
        default_type=NoteType(file_row.default_type) if file_row.default_type else None,
        front_lang=file_row.front_lang,
        back_lang=file_row.back_lang,
        source=Source.model_validate(file_row.source) if file_row.source else None,
        groups=[
            Group(id=group.key, label=group.label, note=group.note, extra=group.extra)
            for group in file_row.groups
        ],
        notes=[
            Note(
                id=row.id,
                type=NoteType(row.type) if row.type else None,
                front=row.front,
                back=row.back,
                front_lang=row.front_lang,
                back_lang=row.back_lang,
                fields=row.fields,
                accept=Accept.model_validate(row.accept) if row.accept else None,
                modes=row.modes,
                note=row.note,
                group=group_key.get(row.group_id) if row.group_id else None,
                tags=row.tags,
                status=row.status,
                confidence=row.confidence,
                suspended=row.suspended,
                priority=Priority(row.priority) if row.priority else None,
                page=row.page,
                extra=row.extra,
            )
            for row in file_row.notes
            if row.archived_at is None
        ],
        tags=file_row.tags,
        extra=file_row.extra,
    )


def find_category(session: Session, path: str) -> Category | None:
    return session.scalar(select(Category).where(Category.path == path))


__all__ = [
    "ImportInfo",
    "card_key",
    "export_datafile",
    "find_category",
    "store_datafile",
    "sync_cards",
]
