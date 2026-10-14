"""Reading a page with an importer that answers in data files (``DatafileImporter``).

The prompt asks for ```json blocks, so the call is plain text whatever tier the
provider has: a schema in ``response_format`` would fight the prompt, and the
storage format is too loose to be a strict schema anyway (PLAN 3.6). What
stands in for the schema is the same repair loop the extraction tiers use.

Whatever the model wrote is cleaned the way an uploaded file is (``read_json``):
its ids, statuses and provenance are not its to set.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from memo.importers.base import DatafileImporter
from memo.llm.client import ChatMessage, LLMClient, image_part, text_part
from memo.llm.jsonblock import extract_json_objects
from memo.llm.structured import MAX_REPAIRS, StructuredError
from memo.models.adapter import _clean, _dedupe_key
from memo.models.datafile import DataFile, ImportInfo, Note, NoteStatus, Source, load_datafile
from memo.models.ids import datafile_id, note_id


def prompt_sha(prompt: str) -> str:
    """Changes whenever the words do, so a draft says which prompt read it."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def page_prompt(importer: DatafileImporter, instructions: list[str]) -> str:
    """The prompt as written, with these lines in its "My instructions" slot."""
    return importer.prompt.rstrip("\n") + "\n" + "\n".join(instructions)


def read_page(
    client: LLMClient,
    importer: DatafileImporter,
    path: str | Path | None = None,
    *,
    instructions: list[str],
    model: str | None = None,
    max_repairs: int = MAX_REPAIRS,
    parts: list[dict] | None = None,
) -> list[DataFile]:
    """One page (or a few PDF pages, as ``parts``), one call plus repairs, one or more data files."""
    material = parts if parts is not None else [image_part(path)]
    conversation = [
        ChatMessage(role="user", content=[text_part(page_prompt(importer, instructions)), *material])
    ]
    problem = ""
    for attempt in range(max_repairs + 1):
        text = client.chat(conversation, model=model, response_format=None)
        try:
            return _parse(text)
        except ValueError as exc:
            problem = str(exc)
            if attempt == max_repairs:
                break
            conversation += [
                ChatMessage(role="assistant", content=text),
                ChatMessage(
                    role="user",
                    content=(
                        "That could not be used. Fix these problems and answer again with the complete "
                        f"corrected ```json blocks only:\n{exc}"
                    ),
                ),
            ]
    raise StructuredError(f"no usable data file after {max_repairs + 1} attempt(s): {problem[:500]}")


def _parse(text: str) -> list[DataFile]:
    files = []
    for index, raw in enumerate(extract_json_objects(text), 1):
        where = f"object {index}"
        if not isinstance(raw.get("notes"), list):
            raise ValueError(f'{where} has no "notes" list')
        try:
            datafile = load_datafile(raw)
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from None
        if not any(n.front or n.back for n in datafile.notes):
            raise ValueError(f"{where} has no notes with a front or a back")
        files.append(datafile)
    return files


def merge_pages(
    pages: list[tuple[int | None, str | None, list[DataFile]]],
    *,
    importer: DatafileImporter,
    model: str | None,
    job: str,
    known_pages: bool,
    source_kind: str = "image",
) -> DataFile:
    """Every object from every page into one draft, in page order (PLAN 4: one job, one file).

    The first object names the file and sets its languages and type. A later
    object whose type differs keeps it on its own notes, and its groups join in,
    so two sections on one page are two headings in one file.
    """
    objects = [(number, df) for number, _, files in pages for df in files]
    first = objects[0][1] if objects else None
    default_type = (first.default_type if first else None) or importer.default_type
    groups, seen_groups = [], set()
    notes: list[Note] = []
    seen_notes: set[tuple[str, str]] = set()

    for number, datafile in objects:
        own = {g.id for g in datafile.groups}
        for group in datafile.groups:
            if group.id and group.id not in seen_groups:
                seen_groups.add(group.id)
                groups.append(group)
        for note in datafile.notes:
            _clean_note(note, own_groups=own)
            if note.type is None and datafile.default_type and datafile.default_type != default_type:
                note.type = datafile.default_type
            if note.page is None and known_pages and number is not None:
                note.page = number
            key = _dedupe_key(note.front, note.back)
            if key in seen_notes and key != ("", ""):
                continue  # the same pair twice: an overlap between photos
            seen_notes.add(key)
            notes.append(note)

    numbers = [number for number, _, _ in pages if number is not None]
    context = first.source.context if first and first.source else None
    return DataFile(
        id=datafile_id(),
        title=first.title if first else None,
        default_type=default_type,
        front_lang=(first.front_lang if first else None) or importer.front_lang,
        back_lang=(first.back_lang if first else None) or importer.back_lang,
        source=Source(
            kind=source_kind,
            files=list(dict.fromkeys(name for _, name, _ in pages if name)) or None,
            page=numbers[0] if known_pages and len(pages) == 1 and numbers else None,
            context=context,
            import_=ImportInfo(
                profile=importer.name,
                model=model,
                prompt_version=importer.prompt_version,
                at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                job_id=job,
                extra={"prompt_sha": prompt_sha(importer.prompt)},
            ),
        ),
        groups=groups,
        notes=notes,
        tags=first.tags if first else None,
    )


def _clean_note(note: Note, *, own_groups: set[str]) -> None:
    note.id = note_id()
    note.status = NoteStatus.UNVERIFIED
    note.suspended = None
    note.front = _clean(note.front)
    note.back = _clean(note.back)
    if note.confidence is not None:
        note.confidence = min(1.0, max(0.0, note.confidence))
    if note.group and note.group not in own_groups:
        note.group = None  # a heading the model named but never defined
