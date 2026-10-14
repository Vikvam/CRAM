"""Writing the collection back out as a tree of data files (PLAN 6, phase 2).

The database is the truth; this is the readable copy beside it, one directory
per category, named after the category path:

    data/korean/02-introduction/_category.json
    data/korean/02-introduction/2-1-vocabulary.json
    data/korean/02-introduction/raw/vocab1.jpg

Nothing is ever deleted: a JSON file this export did not write is reported so
the person can decide, because a mirror that deletes is a mirror that can lose
work. Export is manual (PLAN 5) — it happens when asked, never on a write.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from memo.collection.categories import slugify
from memo.collection.store import export_datafile
from memo.dataio.datafile_io import write_datafile
from memo.db.models import Category, DataFileRow, ImportJob
from memo.models.category import CategoryConfig
from memo.models.datafile import FORMAT

#: The category's own settings, beside its data files.
CATEGORY_FILE = "_category.json"
#: Photos and PDFs an import read, copied next to the notes they became.
RAW_DIR = "raw"


@dataclass(slots=True)
class ExportedFile:
    data_file_id: str
    path: Path
    notes: int


@dataclass(slots=True)
class ExportReport:
    root: Path
    files: list[ExportedFile] = field(default_factory=list)
    categories: list[Path] = field(default_factory=list)
    photos: list[Path] = field(default_factory=list)
    #: JSON files found in the tree that this export did not write.
    unknown: list[Path] = field(default_factory=list)

    @property
    def notes(self) -> int:
        return sum(f.notes for f in self.files)


def _write_json(path: Path, data: dict) -> Path:
    """Same canonical spelling and atomic replace as a data file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def existing_names(directory: Path) -> dict[str, str]:
    """``{data file id: file name}`` for the JSON already in this directory.

    A file keeps the name it has, whatever it was retitled or renamed to — the
    id inside is the identity, so an export never scatters copies of one file.
    """
    found: dict[str, str] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name == CATEGORY_FILE or not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict) and raw.get("format") == FORMAT and isinstance(raw.get("id"), str):
            found.setdefault(raw["id"], path.name)
    return found


def file_name(file: DataFileRow, taken: set[str], known: dict[str, str] | None = None) -> str:
    """``2-1-vocabulary.json``: readable, from the title. The id inside stays the identity."""
    already = (known or {}).get(file.id)
    if already and already not in taken:
        taken.add(already)
        return already
    stem = slugify(file.slug or file.title or file.id)
    name, n = f"{stem}.json", 1
    while name in taken:
        n += 1
        name = f"{stem}-{n}.json"
    taken.add(name)
    return name


def category_file(session: Session, category: Category) -> dict:
    """The category's own settings only — inheritance is applied when reading."""
    config = CategoryConfig.model_validate(category.config) if category.config else CategoryConfig()
    if category.label:
        config.label = category.label
    return config.dumps()


def _raw_sources(session: Session, file: DataFileRow) -> list[Path]:
    """The uploaded pages that became this data file, in page order."""
    jobs = session.scalars(
        select(ImportJob).where(ImportJob.target_data_file_id == file.id).order_by(ImportJob.created_at)
    ).all()
    return [Path(page.path) for job in jobs for page in job.pages if page.path]


def _categories(session: Session, category_id: str | None) -> list[Category]:
    query = select(Category).order_by(Category.path)
    if category_id is not None:
        category = session.get(Category, category_id)
        if category is None:
            raise KeyError(f"no such category: {category_id}")
        query = query.where(or_(Category.path == category.path, Category.path.like(f"{category.path}/%")))
    return list(session.scalars(query))


def export_tree(
    session: Session,
    root: Path,
    *,
    category_id: str | None = None,
    raw_root: Path | None = None,
    copy_photos: bool = True,
) -> ExportReport:
    """Write every live data file under ``root``, one directory per category.

    ``raw_root`` is ``var/raw``; pages are copied to ``<category>/raw/`` and the
    data file's ``source.files`` are rewritten to point at the copies, so the
    exported tree can be read on a machine that never had the database.
    """
    root = Path(root)
    report = ExportReport(root=root)

    for category in _categories(session, category_id):
        directory = root / category.path
        report.categories.append(_write_json(directory / CATEGORY_FILE, category_file(session, category)))

        taken: set[str] = set()
        known = existing_names(directory)
        files = session.scalars(
            select(DataFileRow)
            .where(DataFileRow.category_id == category.id, DataFileRow.archived_at.is_(None))
            .order_by(DataFileRow.position, DataFileRow.created_at)
        ).all()
        for row in files:
            datafile = export_datafile(session, row.id)
            if copy_photos and raw_root is not None:
                copied = _copy_photos(
                    _raw_sources(session, row), raw_root, directory / RAW_DIR, under=category.path
                )
                report.photos.extend(copied)
                if copied and datafile.source is not None:
                    datafile.source.files = [
                        f"{RAW_DIR}/{path.relative_to(directory / RAW_DIR).as_posix()}" for path in copied
                    ]
            path = write_datafile(directory / file_name(row, taken, known), datafile)
            report.files.append(ExportedFile(data_file_id=row.id, path=path, notes=len(datafile.notes)))

        written = {CATEGORY_FILE, *taken}
        report.unknown.extend(
            sorted(p for p in directory.glob("*.json") if p.name not in written and p.is_file())
        )

    return report


def _copy_photos(sources: list[Path], raw_root: Path, target: Path, *, under: str = "") -> list[Path]:
    """Copy the raw pages under ``<category>/raw/``, keeping the job folder they
    are in — two photos called ``vocab1.jpg`` must stay two files."""
    copied: list[Path] = []
    for source in sources:
        origin = source if source.is_absolute() else raw_root / source
        if not origin.is_file():
            continue
        try:
            inside = origin.relative_to(raw_root / under) if under else origin.relative_to(raw_root)
        except ValueError:
            inside = Path(origin.name)
        destination = target / inside
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.stat().st_size != origin.stat().st_size:
            shutil.copy2(origin, destination)
        copied.append(destination)
    return copied


__all__ = ["CATEGORY_FILE", "ExportReport", "ExportedFile", "export_tree", "file_name"]
