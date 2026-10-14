"""Files that already have structure: no model has to read them (PLAN 6, phase 2).

A data file, a spreadsheet export, a list of pairs, an Anki deck — each of these
says what the front and the back are, so an import from one is parsing, not
extraction. A PDF is not one of them: it goes to the model, like a photo
(``importpipe/units.py``). They land in the same draft → review → commit path as a photo, so
nothing reaches the collection without being looked at.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import tempfile
import unicodedata
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from memo.models.datafile import DataFile, Group, Note, NoteStatus, NoteType, Source, load_datafile

#: Extensions this module can read, and what to call the import.
READERS: dict[str, str] = {
    ".json": "json",
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "text",
    ".md": "text",
    ".apkg": "anki",
    ".colpkg": "anki",
}

#: Column names understood in a spreadsheet header, in the order they are tried.
COLUMNS: dict[str, tuple[str, ...]] = {
    "front": ("front", "term", "word", "question", "prompt", "expression", "kanji", "hangul"),
    "back": ("back", "meaning", "translation", "answer", "definition", "english"),
    "group": ("group", "section", "heading", "category", "deck", "lesson", "chapter"),
    "note": ("note", "notes", "comment", "example", "hint"),
    "tags": ("tags", "tag", "labels"),
}

#: What separates the two sides of a pair in a plain text file.
SEPARATORS = ("\t", " = ", " — ", " – ", " - ", " : ", ";", "=", "|")

_TAG = re.compile(r"<[^>]+>")
#: Uploads are stored as ``01-words.csv``; the title should not carry the number.
_UPLOAD_PREFIX = re.compile(r"^\d{2}-")
_ANKI_FIELD = "\x1f"


class UnreadableFile(ValueError):
    """The file is of a kind we read, but nothing in it looked like notes."""


def reader_for(path: str | Path) -> str | None:
    """The importer name for this file, or None when it needs a model to read it."""
    return READERS.get(Path(path).suffix.lower())


def strip_markup(value: str) -> str:
    """Anki fields and spreadsheet cells carry HTML; the notes should not."""
    text = _TAG.sub(" ", value).replace("&nbsp;", " ")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
    return " ".join(unicodedata.normalize("NFC", text).split())


@dataclass(slots=True)
class Pair:
    front: str
    back: str
    group: str | None = None
    note: str | None = None
    tags: list[str] | None = None


def _datafile(pairs: Iterable[Pair], *, kind: str, name: str, title: str | None = None) -> DataFile:
    """One parsed file → a draft, with every note left ``unverified`` for review."""
    notes: list[Note] = []
    groups: dict[str, Group] = {}
    for pair in pairs:
        if pair.group and pair.group not in groups:
            groups[pair.group] = Group(id=pair.group, label={"en": pair.group})
        notes.append(
            Note(
                front=pair.front,
                back=pair.back,
                group=pair.group,
                note=pair.note,
                tags=pair.tags,
                status=NoteStatus.UNVERIFIED,
            )
        )
    if not notes:
        raise UnreadableFile(f"{name}: no front/back pairs found")
    return DataFile(
        title=title or _UPLOAD_PREFIX.sub("", Path(name).stem),
        default_type=NoteType.BIDIRECTIONAL,
        source=Source(kind=kind, files=[Path(name).name]),
        groups=list(groups.values()),
        notes=notes,
    )


# --- one reader per kind ----------------------------------------------------


def read_json(path: Path) -> DataFile:
    """A data file this app wrote, or any list of pairs."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and raw.get("format") == "memo.datafile":
        datafile = load_datafile(raw)
        # Re-imported notes are new notes: the ids in the file belong to wherever
        # it came from, and progress is keyed on ids (PLAN 3.4).
        for note in datafile.notes:
            note.id = None
            note.status = NoteStatus.UNVERIFIED
        datafile.id = None
        return datafile

    items = raw.get("notes") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise UnreadableFile(f"{path.name}: expected a data file or a list of notes")
    pairs = []
    for item in items:
        if not isinstance(item, dict):
            continue
        front = _first(item, COLUMNS["front"])
        back = _first(item, COLUMNS["back"])
        if front and back:
            pairs.append(
                Pair(
                    front=front,
                    back=back,
                    group=_first(item, COLUMNS["group"]),
                    note=_first(item, COLUMNS["note"]),
                )
            )
    return _datafile(pairs, kind="json", name=path.name)


def _first(item: dict, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = item.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def read_csv(path: Path) -> DataFile:
    """A spreadsheet export. Columns are found by name, or taken in order."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        raise UnreadableFile(f"{path.name}: the file is empty")

    header = [strip_markup(cell).lower() for cell in rows[0]]
    index = {field: _column(header, names) for field, names in COLUMNS.items()}
    if index["front"] is None or index["back"] is None:
        index = {"front": 0, "back": 1, "group": None, "note": 2 if len(rows[0]) > 2 else None, "tags": None}
    else:
        rows = rows[1:]

    def cell(row: list[str], i: int | None) -> str:
        return strip_markup(row[i]) if i is not None and i < len(row) else ""

    pairs = []
    for row in rows:
        front, back = cell(row, index["front"]), cell(row, index["back"])
        if not front or not back:
            continue
        tags = [t for t in re.split(r"[,\s]+", cell(row, index["tags"])) if t]
        pairs.append(
            Pair(
                front=front,
                back=back,
                group=cell(row, index["group"]) or None,
                note=cell(row, index["note"]) or None,
                tags=tags or None,
            )
        )
    return _datafile(pairs, kind="csv", name=path.name)


def _column(header: list[str], names: tuple[str, ...]) -> int | None:
    for name in names:
        if name in header:
            return header.index(name)
    return None


def read_text(path: Path) -> DataFile:
    """One pair per line: ``나라 = country``, a tab, a dash — whichever it uses."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    separator = _separator(lines)
    if separator is None:
        raise UnreadableFile(
            f"{path.name}: no separator found — put the two sides on one line, e.g. 나라 = country"
        )

    pairs, group = [], None
    for line in lines:
        if separator not in line:
            # A line on its own is a heading for what follows.
            group = line.lstrip("#").strip(" *_-") or None
            continue
        front, _, back = line.partition(separator)
        front, back = front.strip(), back.strip()
        if front and back:
            pairs.append(Pair(front=front, back=back, group=group))
    return _datafile(pairs, kind="text", name=path.name)


def _separator(lines: list[str]) -> str | None:
    """The separator that splits the most lines into two non-empty halves."""
    best, best_score = None, 0
    for candidate in SEPARATORS:
        score = sum(
            1
            for line in lines
            if candidate in line
            and line.partition(candidate)[0].strip()
            and line.partition(candidate)[2].strip()
        )
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score else None


def read_anki(path: Path) -> DataFile:
    """An ``.apkg`` export: a zip with an SQLite collection inside."""
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n in ("collection.anki21", "collection.anki2")]
        if not names:
            raise UnreadableFile(f"{path.name}: no Anki collection inside (is it a newer .apkg?)")
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(archive.extract(sorted(names)[-1], tmp))
            pairs = _anki_pairs(extracted)
    return _datafile(pairs, kind="anki", name=path.name)


def _anki_pairs(db_path: Path) -> list[Pair]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute("select flds, tags from notes").fetchall()
    except sqlite3.DatabaseError as exc:  # a collection format we do not know
        raise UnreadableFile(f"could not read the Anki collection: {exc}") from exc
    finally:
        connection.close()

    pairs = []
    for fields, tags in rows:
        parts = [strip_markup(part) for part in str(fields).split(_ANKI_FIELD)]
        parts = [p for p in parts if p]
        if len(parts) < 2:
            continue
        tag_list = [t for t in str(tags or "").split() if t]
        pairs.append(
            Pair(
                front=parts[0],
                back=parts[1],
                note=" · ".join(parts[2:]) or None,
                tags=tag_list or None,
            )
        )
    return pairs


_READERS = {
    "json": read_json,
    "csv": read_csv,
    "text": read_text,
    "anki": read_anki,
}


def merge_datafiles(files: list[DataFile]) -> DataFile:
    """Several files uploaded together become one draft, in the order given."""
    base = files[0]
    for other in files[1:]:
        keys = {group.id for group in base.groups}
        base.groups.extend(group for group in other.groups if group.id not in keys)
        base.notes.extend(other.notes)
        if base.source is not None and other.source is not None:
            base.source.files = (base.source.files or []) + (other.source.files or [])
    return base


def read_structured_file(path: str | Path) -> tuple[str, DataFile]:
    """Parse a file that needs no model. Returns the importer name and the draft."""
    file = Path(path)
    name = reader_for(file)
    if name is None:
        raise UnreadableFile(f"{file.name}: not a file this importer can read")
    return name, _READERS[name](file)


__all__ = [
    "COLUMNS",
    "READERS",
    "Pair",
    "UnreadableFile",
    "merge_datafiles",
    "read_structured_file",
    "reader_for",
    "strip_markup",
]
