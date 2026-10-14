"""Command line for phase 0 — the pipeline before there is any UI (PLAN 6)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from memo.collection import export_datafile, store_datafile
from memo.collection.store import find_category
from memo.config import get_settings
from memo.dataio import dump_json, read_datafile, write_datafile
from memo.dataio.export_tree import export_tree
from memo.db import Base, make_engine, make_session_factory, session_scope
from memo.importers import UnknownImporter, load_registry, route
from memo.importpipe import run_import
from memo.importpipe.units import PDF_MODES, units_for
from memo.llm import LLMClient, StructuredOutput, probe
from memo.models.datafile import DataFile
from memo.models.extraction import ExtractionResult

app = typer.Typer(add_completion=False, help="Memorization app — collection and import tools.")
#: Not under /tmp and not inside the project, so a clean checkout cannot take it with it.
DEFAULT_BACKUP_DIR = Path.home() / "backups" / "memo"
err = typer.style


def _tier(explicit: str | None) -> StructuredOutput:
    settings = get_settings()
    return StructuredOutput(explicit or settings.llm_structured_output or StructuredOutput.TEXT)


def _sessions():
    settings = get_settings()
    settings.ensure_dirs()
    engine = make_engine(settings.db_path)
    Base.metadata.create_all(engine)  # phase 0 convenience; migrations own this from phase 1
    return make_session_factory(engine)


@app.command("importers")
def list_importers() -> None:
    """Show the importers a page can be read with, and any local one that failed to load."""
    settings = get_settings()
    registry = load_registry(settings.importers_dir)
    for importer in registry.all():
        typer.echo(f"{importer.name:<24} {importer.origin:<8} {importer.description}")
    for error in registry.errors:
        typer.echo(err(f"skipped {error}", fg="red"), err=True)


@app.command()
def probe_provider(
    image: Annotated[Path | None, typer.Option("--image", help="Probe vision with this file")] = None,
) -> None:
    """Ask the configured provider what it supports (PLAN 3.6)."""
    with LLMClient() as client:
        capabilities = probe(client, image=image)
    typer.echo(json.dumps(capabilities.dump(), indent=2))
    typer.echo(
        f"\nSet MEMO_LLM_STRUCTURED_OUTPUT={capabilities.structured_output} to skip this next time.",
    )


@app.command("import")
def import_pages(
    images: Annotated[list[Path], typer.Argument(help="Page images and PDFs, in order")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the draft data file here")] = None,
    importer: Annotated[
        str | None, typer.Option("--importer", help="Skip the router and use this importer")
    ] = None,
    category: Annotated[
        str | None, typer.Option("--category", help="Also store the draft under this category path")
    ] = None,
    tier: Annotated[str | None, typer.Option("--tier", help="json_schema | json_object | text")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Override the configured model")] = None,
    first_page: Annotated[
        int | None, typer.Option("--first-page", help="Printed page number of the first image")
    ] = None,
    instructions: Annotated[
        str | None, typer.Option("--instructions", help="What to tell the model, as you would in a chat")
    ] = None,
    pdf_mode: Annotated[
        str, typer.Option("--pdf-mode", help="How a PDF reaches the model: text | images")
    ] = "text",
) -> None:
    """Read photos and PDFs with the LLM and write one draft data file (PLAN 4)."""
    missing = [str(p) for p in images if not p.is_file()]
    if missing:
        raise typer.BadParameter(f"no such file: {', '.join(missing)}")
    if pdf_mode not in PDF_MODES:
        raise typer.BadParameter(f"--pdf-mode is text or images, not {pdf_mode!r}")
    pages_per_call = get_settings().pdf_pages_per_call

    structured = _tier(tier)
    registry = load_registry(get_settings().importers_dir)
    try:
        chosen = registry.get(importer) if importer else None
    except UnknownImporter as exc:
        raise typer.BadParameter(str(exc)) from None
    with LLMClient() as client:
        reason = None
        if chosen is None:
            [first, *_] = units_for(images[:1], pdf_mode=pdf_mode, pages_per_call=pages_per_call)
            kind = "pdf" if first.is_pdf else "image"
            chosen, reason = route(
                client, first.parts(), registry=registry, tier=structured, model=model, kind=kind
            )
            typer.echo(f"importer: {chosen.name}" + (f" — {reason}" if reason else ""))
        outcome = run_import(
            client,
            chosen,
            list(images),
            tier=structured,
            model=model,
            first_page_number=first_page,
            router_reason=reason,
            instructions=[instructions] if instructions else None,
            pdf_mode=pdf_mode,  # type: ignore[arg-type]
            pages_per_call=pages_per_call,
        )

    for failure in outcome.failed_pages:
        pages = (
            f"page {failure.number}"
            if failure.count == 1
            else f"pages {failure.number}–{failure.number + failure.count - 1}"
        )
        typer.echo(err(f"{pages} failed: {failure.error}", fg="red"), err=True)

    datafile = outcome.datafile
    typer.echo(
        f"{len(datafile.notes)} notes, {len(datafile.groups)} groups, "
        f"{len(datafile.flagged())} flagged, {len(outcome.failed_pages)} page(s) failed"
    )

    if out is not None:
        write_datafile(out, datafile)
        typer.echo(f"wrote {out}")
    else:
        typer.echo(dump_json(datafile))

    if category:
        with session_scope(_sessions()) as session:
            row = store_datafile(session, datafile, category_path=category)
            typer.echo(f"stored as {row.id} under {category}")

    if outcome.failed_pages and not outcome.pages_ok:
        raise typer.Exit(code=1)


@app.command("store")
def store(
    path: Annotated[Path, typer.Argument(help="A data file to load into the database")],
    category: Annotated[str, typer.Option("--category", help="Category path, e.g. korean/book1")],
) -> None:
    """Load a ready-made data file into the collection."""
    datafile = read_datafile(path)
    with session_scope(_sessions()) as session:
        row = store_datafile(session, datafile, category_path=category, slug=path.stem)
        typer.echo(f"stored {len(datafile.notes)} notes as {row.id} under {category}")


@app.command("export")
def export(
    file_id: Annotated[str, typer.Argument(help="Data file id")],
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
) -> None:
    """Write a stored data file back out in the interchange format (PLAN 5)."""
    with session_scope(_sessions()) as session:
        datafile = export_datafile(session, file_id)
    if out is None:
        typer.echo(dump_json(datafile))
    else:
        write_datafile(out, datafile)
        typer.echo(f"wrote {out}")


@app.command("export-tree")
def export_tree_command(
    category: Annotated[str | None, typer.Option(help="Category path, e.g. korean/book1")] = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Default: MEMO_DATA_DIR")] = None,
    photos: Annotated[bool, typer.Option(help="Copy the pages an import read")] = True,
) -> None:
    """Write the collection out as data files, one directory per category (PLAN 6)."""
    settings = get_settings()
    with session_scope(_sessions()) as session:
        node = find_category(session, category) if category else None
        if category and node is None:
            typer.echo(f"no such category: {category}", err=True)
            raise typer.Exit(1)
        report = export_tree(
            session,
            out or settings.export_dir,
            category_id=node.id if node else None,
            raw_root=settings.raw_dir,
            copy_photos=photos,
        )
    for exported in report.files:
        typer.echo(f"{exported.path}  ({exported.notes} notes)")
    typer.echo(
        f"{len(report.files)} files, {report.notes} notes, {len(report.categories)} categories,"
        f" {len(report.photos)} photos → {report.root}"
    )
    for unknown in report.unknown:
        typer.echo(f"left alone (not part of the collection): {unknown}")


@app.command("schema")
def schema(
    out: Annotated[Path, typer.Option("--out", "-o", help="Directory to write into")] = Path("schema"),
) -> None:
    """Export both JSON Schemas — the lenient storage one and the strict LLM one (PLAN 3.6)."""
    from memo.models.extraction import strict_json_schema

    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, document in (
        ("memo.datafile.schema.json", DataFile.model_json_schema(mode="serialization")),
        ("memo.extraction.schema.json", strict_json_schema(ExtractionResult)),
    ):
        target = out / name
        target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(str(target))
    typer.echo("\n".join(written))


@app.command("openapi")
def openapi(
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("schema/openapi.json"),
) -> None:
    """Write the API description the frontend's types are generated from (PLAN 5)."""
    import tempfile

    from memo.api import create_app
    from memo.config import Settings

    with tempfile.TemporaryDirectory() as tmp:
        document = create_app(Settings(var_dir=Path(tmp))).openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    typer.echo(str(out))


@app.command("hash-password")
def hash_password_command(
    password: Annotated[str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)],
) -> None:
    """Print the argon2 hash to put in MEMO_AUTH_PASSWORD_HASH."""
    from memo.api.auth import hash_password

    typer.echo(hash_password(password))


@app.command("import-answers")
def import_answers(
    path: Annotated[Path, typer.Argument(help="A file saved by the phone's 'save my answers'")],
) -> None:
    """Take in answers earned with no network — the hand-carried half of syncing.

    The same file can be given twice without counting twice, and it goes through
    the same code as the upload, so the two paths cannot drift apart.
    """
    from memo.collection.profiles import get_or_create_profile
    from memo.practice import AnswerRow, ingest_answers
    from memo.practice.service import resolve_scheduler_name

    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        typer.echo(err("Expected a list of answers, or an object with a `rows` list.", fg="red"))
        raise typer.Exit(2)

    factory = _sessions()
    with session_scope(factory) as session:
        profile = get_or_create_profile(session)
        report = ingest_answers(
            session,
            profile,
            [
                AnswerRow(
                    client_id=str(row["client_id"]),
                    at=datetime.fromisoformat(row["at"]),
                    card_key=str(row["card_key"]),
                    mode=str(row["mode"]),
                    outcome=row.get("outcome"),
                    grade=row.get("grade"),
                    overridden=bool(row.get("overridden", False)),
                    raw_answer=row.get("raw_answer"),
                    duration_ms=row.get("duration_ms"),
                    scheduler=row.get("scheduler"),
                )
                for row in rows
            ],
            scheduler=resolve_scheduler_name(session, profile, None),
        )
    typer.echo(f"{report.accepted} taken in, {report.duplicates} already here, {report.rebuilt} rebuilt")
    for key in report.unknown:
        typer.echo(err(f"no such card any more, dropped: {key}", fg="yellow"))


@app.command("audit")
def audit_collection(
    category: Annotated[str | None, typer.Option(help="Narrow to one category path")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable instead of a table")] = False,
) -> None:
    """Look the collection over for the wonkiness an import leaves behind.

    Read-only. The one that matters is a gloss shared by two different words: a
    note's back is the answer going one way and the *prompt* going the other, so
    two notes glossed "that" ask the same question with two different right
    answers. Run it after taking a chapter in.
    """
    from memo.collection.audit import audit

    def where(entry) -> str:
        return (entry.file_title or entry.category_path or "").split(" · ")[0]

    factory = _sessions()
    with session_scope(factory) as session:
        category_id = find_category(session, category).id if category else None
        report = audit(session, category_id=category_id)

        if as_json:
            typer.echo(
                dump_json(
                    {
                        name: [
                            {"gloss": f.key, "notes": [vars(n) for n in f.notes]}
                            for f in getattr(report, name)
                        ]
                        for name in ("collisions", "near", "duplicates", "resolved")
                    }
                    | {"one_sided": [[vars(a), vars(b)] for a, b in report.one_sided]}
                )
            )
            return

        if report.collisions:
            typer.echo(err(f"same gloss, different word ({len(report.collisions)})", bold=True))
            for finding in report.collisions:
                words = " · ".join(f"{n.front} {where(n)}" for n in finding.notes)
                typer.echo(f'  "{finding.key}"  {words}')
        if report.duplicates:
            typer.echo(err(f"the same note twice ({len(report.duplicates)})", bold=True))
            for finding in report.duplicates:
                first = finding.notes[0]
                copies = " · ".join(f"{where(n)} ({n.answers} answers)" for n in finding.notes)
                typer.echo(f"  {first.front} = {first.back}  {copies}")
        if report.one_sided:
            typer.echo(err(f"cross-acceptance only one way ({len(report.one_sided)})", bold=True))
            for a, b in report.one_sided:
                typer.echo(f"  {a.front} accepts {b.front}, but {b.front} does not accept {a.front}")
        if report.near:
            typer.echo(err(f"nearly the same gloss ({len(report.near)})", bold=True))
            for finding in report.near:
                words = " · ".join(f'{n.front} "{n.back}"' for n in finding.notes)
                typer.echo(f'  "{finding.key}"  {words}')
        if report.resolved:
            typer.echo(f"shared on purpose, each accepting the others ({len(report.resolved)}):")
            for finding in report.resolved:
                typer.echo(f'  "{finding.key}"  {" · ".join(str(n.front) for n in finding.notes)}')
        if report.clean:
            typer.echo(err("nothing ambiguous and nothing doubled.", fg="green"))


@app.command("patch")
def patch_notes(
    path: Annotated[Path, typer.Argument(help="A memo.patch file")],
    apply: Annotated[bool, typer.Option("--apply", help="Actually write it; otherwise a dry run")] = False,
) -> None:
    """Change a batch of notes from a reviewed file — the only bulk edit there is.

    Re-importing an edited export would make *new* notes with no history, so a
    text fix to a collection that has been practised comes through here. It is a
    dry run until ``--apply``, it refuses the whole file if any note is missing
    or holds something other than what the patch expected, and it aborts if the
    write moved the card or review counts, which editing text cannot do.
    """
    from memo.collection.patch import apply_patch, load_patch

    try:
        patch = load_patch(path)
    except ValueError as problem:
        typer.echo(err(str(problem), fg="red"))
        raise typer.Exit(2) from problem

    if patch.why:
        typer.echo(err(patch.why, bold=True))

    factory = _sessions()
    with session_scope(factory) as session:
        try:
            report = apply_patch(session, patch, apply=apply)
        except (ValueError, RuntimeError) as problem:
            typer.echo(err(str(problem), fg="red"))
            raise typer.Exit(1) from problem

        last = None
        for change in report.changes:
            if change.note_id != last:
                typer.echo(f"  {change.front}")
                last = change.note_id
            typer.echo(f"    {change.key:<9} {change.before!r} → {change.after!r}")
        if report.settled:
            typer.echo(f"  {len(report.settled)} already as the patch wants them")
        fields = len(report.changes)
        if not apply:
            typer.echo(f"{report.notes} notes, {fields} fields. Nothing written — pass --apply.")
            return
        typer.echo(
            err(
                f"{report.notes} notes, {fields} fields written. "
                f"{report.cards} cards and {report.reviews} answers, unchanged.",
                fg="green",
            )
        )


@app.command("backup")
def backup(
    to: Annotated[Path | None, typer.Option("--to", help="Where the copies live")] = None,
    keep: Annotated[int, typer.Option(help="How many to keep; 0 keeps all")] = 14,
) -> None:
    """Copy the database somewhere safe. It is the only copy of every review.

    ``VACUUM INTO`` and not ``cp``: the write-ahead log means the file on disk is
    not the whole story, and a half-copied database is worse than none (PLAN 5).
    """
    import sqlite3
    from datetime import date

    settings = get_settings()
    if not settings.db_path.exists():
        typer.echo(err(f"nothing to back up at {settings.db_path}", fg="red"))
        raise typer.Exit(1)
    to = to or DEFAULT_BACKUP_DIR
    to.mkdir(parents=True, exist_ok=True)
    target = to / f"memo-{date.today().isoformat()}.db"
    target.unlink(missing_ok=True)  # run twice in a day and the second wins
    with sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True) as source:
        source.execute("VACUUM INTO ?", (str(target),))
    typer.echo(f"{target} ({target.stat().st_size / 1_048_576:.1f} MiB)")

    if keep > 0:
        stale = sorted(to.glob("memo-*.db"))[:-keep]
        for old in stale:
            old.unlink()
        if stale:
            typer.echo(f"dropped {len(stale)} older than the last {keep}")


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run the app: API plus the built frontend, on localhost by default (PLAN 5)."""
    import uvicorn

    uvicorn.run("memo.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":  # pragma: no cover
    app()
