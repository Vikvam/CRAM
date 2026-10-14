"""Import jobs in the database (PLAN 4, PLAN 5).

A job is staged in the ``import_job`` table from upload to commit: the raw
files are written under ``var/raw`` at once, extraction runs in the background,
and the draft waits there — reviewable, editable, resumable — until you commit.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from memo.collection.categories import category_config
from memo.collection.store import append_datafile, store_datafile
from memo.config import Settings
from memo.db.base import session_scope
from memo.db.models import Category, DataFileRow, ImportJob, ImportPage
from memo.importers import AnyImporter, DatafileImporter, load_registry, route
from memo.importers.files import READERS, UnreadableFile, merge_datafiles, read_structured_file, reader_for
from memo.importpipe.run import run_import
from memo.importpipe.units import PDF_MODES, PDF_SUFFIX, page_count, units_for
from memo.llm.client import LLMClient
from memo.models.datafile import DataFile, NoteStatus, load_datafile
from memo.models.ids import job_id, new_id

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
#: Everything an import accepts: photos and PDFs for the model, and files that read themselves.
ALLOWED_SUFFIXES = IMAGE_SUFFIXES | {PDF_SUFFIX} | set(READERS)


class JobStatus:
    PENDING = "pending"  # uploaded, extraction not started
    RUNNING = "running"
    REVIEW = "review"  # draft ready for you
    COMMITTED = "committed"
    FAILED = "failed"


@dataclass(slots=True)
class Upload:
    filename: str
    content: bytes


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^\w.-]+", "-", Path(name).name, flags=re.UNICODE).strip("-.")
    return stem or "page"


def create_job(
    session: Session,
    settings: Settings,
    category: Category,
    uploads: list[Upload],
    *,
    importer: str | None = None,
    first_page: int | None = None,
    target_data_file_id: str | None = None,
    instructions: str | None = None,
    pdf_mode: str | None = None,
) -> ImportJob:
    """Store the raw files and stage a job. Nothing is sent to the LLM yet.

    ``target_data_file_id`` makes this job the next pages of a file that already
    exists, so a chapter photographed over several days stays one data file.
    ``instructions`` is what the person typed for the model, kept with the job so
    a retry asks the same thing. ``pdf_mode`` is how a PDF reaches it: its
    ``text`` (the default) or its pages as ``images``.
    """
    if importer:
        load_registry(settings.importers_dir).get(importer)  # an unknown name fails here, not later
    if not uploads:
        raise ValueError("an import needs at least one file")
    kinds = set()
    for upload in uploads:
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"not a file this app can import: {upload.filename}")
        kinds.add("model" if suffix in IMAGE_SUFFIXES or suffix == PDF_SUFFIX else "file")
    if len(kinds) > 1:
        raise ValueError("upload photos and PDFs, or data files, not both in one import")
    if pdf_mode and pdf_mode not in PDF_MODES:
        raise ValueError(f"pdf_mode must be one of {', '.join(PDF_MODES)}, not {pdf_mode!r}")

    target = session.get(DataFileRow, target_data_file_id) if target_data_file_id else None
    if target_data_file_id and target is None:
        raise ValueError(f"no such data file: {target_data_file_id}")
    if target is not None and target.archived_at is not None:
        raise ValueError("that data file is archived; restore it first")

    job = ImportJob(
        id=job_id(),
        category_id=category.id,
        importer=importer,
        status=JobStatus.PENDING,
        target_data_file_id=target.id if target else None,
        options={
            k: v
            for k, v in (
                ("first_page", first_page),
                ("instructions", (instructions or "").strip()),
                ("pdf_mode", pdf_mode),
            )
            if v
        }
        or None,
    )
    session.add(job)

    folder = settings.raw_dir / category.path / job.id
    folder.mkdir(parents=True, exist_ok=True)
    offset = 0  # pages so far: a photo is one, a PDF is as many as it has
    for position, upload in enumerate(uploads):
        target = folder / f"{position + 1:02d}-{_safe_name(upload.filename)}"
        target.write_bytes(upload.content)
        pages = page_count(target) if target.suffix.lower() == PDF_SUFFIX else 1  # a broken PDF fails here
        session.add(
            ImportPage(
                id=new_id("pg"),
                job_id=job.id,
                position=position,
                path=str(target.relative_to(settings.raw_dir)),
                page_number=(first_page + offset) if first_page else None,
            )
        )
        offset += pages
    session.flush()
    return job


def run_job(
    factory: sessionmaker[Session],
    settings: Settings,
    job_key: str,
    *,
    client_factory: Callable[[], LLMClient] | None = None,
) -> None:
    """Extract every page and leave a draft for review. Safe to run in a thread."""
    with session_scope(factory) as session:
        job = session.get(ImportJob, job_key)
        if job is None:
            return
        job.status = JobStatus.RUNNING
        job.error = None
        paths = [settings.raw_dir / page.path for page in job.pages if page.path]
        importer_name = job.importer
        options = job.options or {}
        first_page = options.get("first_page")
        category = session.get(Category, job.category_id) if job.category_id else None
        hints = _category_lines(session, category)
        typed = options.get("instructions")
        pdf_mode = options.get("pdf_mode") or "text"

    if paths and all(reader_for(path) for path in paths):
        # These files say what the front and the back are; no model is involved.
        _read_files(factory, job_key, paths)
        return

    make_client = client_factory or (lambda: LLMClient(settings))
    tier = settings.llm_structured_output or "text"
    try:
        registry = load_registry(settings.importers_dir)
        with make_client() as client:
            reason = None
            if importer_name:
                importer = registry.get(importer_name)
            else:
                [first, *_] = units_for(
                    paths[:1], pdf_mode=pdf_mode, pages_per_call=settings.pdf_pages_per_call
                )
                kind = "pdf" if first.is_pdf else "image"
                importer, reason = route(client, first.parts(), registry=registry, tier=tier, kind=kind)
            outcome = run_import(
                client,
                importer,
                paths,
                tier=tier,
                first_page_number=first_page,
                router_reason=reason,
                instructions=instruction_lines(importer, hints, typed),
                pdf_mode=pdf_mode,
                pages_per_call=settings.pdf_pages_per_call,
            )
    except Exception as exc:  # the job must end in a visible state, whatever happened
        with session_scope(factory) as session:
            job = session.get(ImportJob, job_key)
            if job is not None:
                job.status = JobStatus.FAILED
                job.error = f"{type(exc).__name__}: {exc}"
        return

    with session_scope(factory) as session:
        job = session.get(ImportJob, job_key)
        if job is None:
            return
        for page in job.pages:
            # A photo is one call; a PDF is one per few pages, and fails only if every one did.
            results = [o for o in outcome.pages if o.file_index == page.position]
            if not results:
                continue
            page.status = "done" if any(r.ok for r in results) else "failed"
            page.error = "; ".join(r.error for r in results if r.error) or None
            kept = [_page_result(r.result) for r in results]
            page.extraction = kept[0] if len(kept) == 1 else {"parts": kept}
        # Raw file references are relative to the category, like in a data file (PLAN 3.1).
        # The job folder stays in the name: two photos called vocab1.jpg are two photos.
        datafile = outcome.datafile
        if datafile.source is not None:
            datafile.source.files = [f"raw/{raw_reference(job, page)}" for page in job.pages if page.path]
        job.importer = outcome.importer
        job.draft = datafile.dumps()
        job.options = {**(job.options or {}), "router_reason": outcome.router_reason}
        if outcome.failed_pages and not outcome.pages_ok:
            job.status = JobStatus.FAILED
            job.error = "; ".join(f"{_pages(p.number, p.count)}: {p.error}" for p in outcome.failed_pages)
        else:
            job.status = JobStatus.REVIEW


def _pages(first: int, count: int) -> str:
    return f"page {first}" if count == 1 else f"pages {first}–{first + count - 1}"


def _category_lines(session: Session, category: Category | None) -> list[str]:
    """What the category already says about its cards, as defaults for the model."""
    if category is None:
        return []
    config = category_config(session, category)
    lines = [f'These cards go into the category "{category.path}".']
    if config.front_lang and config.back_lang:
        lines.append(
            f'Unless the material says otherwise, use front_lang "{config.front_lang}" and back_lang '
            f'"{config.back_lang}".'
        )
    if config.default_type:
        lines.append(f'Unless the material calls for the other, use default_type "{config.default_type}".')
    return lines


def instruction_lines(importer: AnyImporter, hints: list[str], typed: str | None) -> list[str]:
    """The lines that fill "My instructions": the category's defaults, then what was typed.

    An extraction importer already knows its languages and type, so it gets only
    the typed text. Typed text comes last because the prompt lets it override.
    """
    lines = list(hints) if isinstance(importer, DatafileImporter) else []
    if typed:
        lines.append(typed)
    return lines


def raw_reference(job: ImportJob, page: ImportPage) -> str:
    """``<job id>/01-vocab1.jpg`` — what a data file calls this page, under ``raw/``."""
    path = Path(page.path or "")
    return f"{job.id}/{path.name}" if path.name else ""


def _page_result(result) -> dict | None:
    """What one page produced, kept for debugging an import."""
    if result is None:
        return None
    if isinstance(result, list):
        return {"datafiles": [datafile.dumps() for datafile in result]}
    return result.model_dump(mode="json")


def _read_files(factory: sessionmaker[Session], job_key: str, paths: list[Path]) -> None:
    """Parse structured uploads into one draft (PLAN 6, phase 2)."""
    results: list[tuple[DataFile | None, str | None]] = []
    name = "file"
    for path in paths:
        try:
            name, datafile = read_structured_file(path)
            results.append((datafile, None))
        except (UnreadableFile, OSError, ValueError) as exc:
            results.append((None, f"{type(exc).__name__}: {exc}"))

    parsed = [datafile for datafile, _ in results if datafile is not None]
    errors = [error for _, error in results if error]

    with session_scope(factory) as session:
        job = session.get(ImportJob, job_key)
        if job is None:
            return
        # Pages and paths are both in upload order, so they line up.
        for page, (_, error) in zip(job.pages, results, strict=False):
            page.status = "failed" if error else "done"
            page.error = error
        job.importer = name
        job.error = "; ".join(errors) or None
        if parsed:
            job.draft = merge_datafiles(parsed).dumps()
            job.status = JobStatus.REVIEW
        else:
            job.status = JobStatus.FAILED
            job.error = job.error or "nothing could be read"


def save_draft(session: Session, job: ImportJob, draft: dict) -> DataFile:
    """Validate an edited draft before accepting it — a bad edit fails here, not at commit."""
    if job.status not in (JobStatus.REVIEW, JobStatus.FAILED):
        raise ValueError(f"job is {job.status}; only a draft under review can be edited")
    datafile = load_datafile(draft)
    job.draft = datafile.dumps()
    session.flush()
    return datafile


def move_job(session: Session, job: ImportJob, category: Category) -> ImportJob:
    """Send a staged job to a different category, before it is committed.

    The raw files stay where they were written: a data file refers to them by path,
    so moving them would break the provenance of every job that shares the folder.
    """
    if job.status == JobStatus.COMMITTED:
        raise ValueError("job is committed; move the data file instead")
    if job.category_id != category.id:
        job.category_id = category.id
        job.target_data_file_id = None  # that file is in the category we just left
    session.flush()
    return job


def set_job_target(session: Session, job: ImportJob, data_file_id: str | None) -> ImportJob:
    """Choose whether these pages start a new data file (``None``) or join one."""
    if job.status == JobStatus.COMMITTED:
        raise ValueError("job is committed; its pages are in the collection already")
    if data_file_id is None:
        job.target_data_file_id = None
        session.flush()
        return job
    target = session.get(DataFileRow, data_file_id)
    if target is None:
        raise ValueError(f"no such data file: {data_file_id}")
    if target.archived_at is not None:
        raise ValueError("that data file is archived; restore it first")
    if target.category_id != job.category_id:
        raise ValueError("that data file is in another category")
    job.target_data_file_id = target.id
    session.flush()
    return job


def discard_job(session: Session, settings: Settings, job: ImportJob) -> None:
    """Throw a staged job away, raw files and all.

    A committed job is kept: it is where the notes came from, and its photos are
    what the data file points at. Archive the data file instead (PLAN 6, phase 2).
    """
    if job.status == JobStatus.COMMITTED:
        raise ValueError("job is committed; archive the data file instead")
    if job.status == JobStatus.RUNNING:
        raise ValueError("job is running; wait for it to finish")

    root = settings.raw_dir.resolve()
    folders: set[Path] = set()
    for page in job.pages:
        if not page.path:
            continue
        path = (settings.raw_dir / page.path).resolve()
        if not path.is_relative_to(root):  # a path from outside var/raw is not ours to delete
            continue
        path.unlink(missing_ok=True)
        folders.add(path.parent)
    for folder in folders:
        # Only the job's own folder, and only when nothing else is left in it.
        if folder != root and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    session.delete(job)
    session.flush()


def commit_job(session: Session, job: ImportJob, *, category: Category | None = None):
    """Reviewed → stored. Every note you kept becomes ``confirmed`` (PLAN 3.2)."""
    if job.status != JobStatus.REVIEW:
        raise ValueError(f"job is {job.status}; only a reviewed draft can be committed")
    if not job.draft:
        raise ValueError("job has no draft")
    target = category or (session.get(Category, job.category_id) if job.category_id else None)
    if target is None:
        raise ValueError("job has no category to store into")

    datafile = load_datafile(job.draft)
    for note in datafile.notes:
        note.status = NoteStatus.CONFIRMED

    into = session.get(DataFileRow, job.target_data_file_id) if job.target_data_file_id else None
    if into is not None:
        # The job was uploaded as the next pages of this file (PLAN 6, phase 2).
        append_datafile(session, into, datafile)
        row = into
    else:
        row = store_datafile(session, datafile, category_path=target.path)
    job.target_data_file_id = row.id
    job.status = JobStatus.COMMITTED
    session.flush()
    return row
