"""The HTTP API (PLAN 5). One process: this app also serves the built frontend."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from memo.api import schemas as s
from memo.api.auth import Gate, client_id
from memo.collection.audit import Finding, audit
from memo.collection.categories import (
    UNSET,
    category_config,
    delete_category,
    ensure_category,
    move_category,
    rename_category,
    update_practice,
)
from memo.collection.editing import (
    Duplicate,
    archive_file,
    archive_note,
    create_file,
    create_notes,
    find_duplicates,
    live_notes,
    normalise,
    reorder_notes,
    update_file,
    update_note,
)
from memo.collection.lists import add_notes as add_list_notes
from memo.collection.lists import (
    all_lists,
    create_list,
    delete_list,
    get_list,
    members,
    remove_note,
    update_list,
)
from memo.collection.lists import view as list_view
from memo.collection.notes import add_accepted
from memo.collection.profiles import get_or_create_profile
from memo.collection.related import related
from memo.collection.search import by_ids, search
from memo.collection.store import export_datafile
from memo.config import FRONTEND_BUILD, Settings, get_settings
from memo.dataio.export_tree import export_tree
from memo.db import Base, make_engine, make_session_factory
from memo.db.models import Card, Category, DataFileRow, ImportJob, Profile, ReviewLog
from memo.db.models import CardState as CardStateRow
from memo.db.models import Note as NoteRow
from memo.importers import load_registry
from memo.importpipe.jobs import (
    JobStatus,
    Upload,
    commit_job,
    create_job,
    discard_job,
    move_job,
    run_job,
    save_draft,
    set_job_target,
)
from memo.llm.client import LLMClient
from memo.models.category import (
    CategoryConfig,
    effective_distractor_scope,
    effective_modes,
    inherit,
)
from memo.overview import (
    ACTIVITY_DAYS,
    KNOWN,
    KNOWN_POINTS,
    LEARNING,
    MASTERED,
    MASTERED_POINTS,
    MASTERY_SPREAD,
    MIN_REVIEWS,
    NEW,
    RATE,
    RATE_WINDOW,
    SET_ASIDE,
    WEAK_LIMIT,
    WEAK_WINDOW_DAYS,
    WRITING_POINTS,
    activity,
    file_mastery,
    group_mastery,
    mastery,
    note_buckets,
    pace,
    standings_since,
    weak_cards,
    words,
)
from memo.practice.service import (
    AnswerIn,
    AnswerRow,
    due_queue,
    ingest_answers,
    record_answer,
    resolve_practice,
    resolve_scheduler_name,
)
from memo.scheduling.registry import SCHEDULERS

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: Words shown in one strip on the Progress page: enough to be a glimpse of the
#: collection, few enough to read without scrolling. The whole list is one tap on.
STRIP = 6


def create_app(
    settings: Settings | None = None,
    *,
    client_factory: Callable[[], LLMClient] | None = None,
    create_tables: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    engine = make_engine(settings.db_path)
    if create_tables:
        # Tests and first runs; `alembic upgrade head` is the real path and is idempotent with this.
        Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    gate = Gate(settings)

    app = FastAPI(title="CRAM", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.sessions = factory
    app.state.gate = gate
    app.state.client_factory = client_factory

    app.include_router(_auth_router(gate))
    app.include_router(_api_router(settings, factory, gate, client_factory))
    _mount_frontend(app)
    return app


# --- dependencies -----------------------------------------------------------


def _db(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.sessions
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _signed_in(request: Request) -> None:
    request.app.state.gate.require(request)


DB = Annotated[Session, Depends(_db)]


def _profile(session: Session) -> Profile:
    return get_or_create_profile(session)


def _category_or_404(session: Session, category_id: str) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such category.")
    return category


def _practice_set(category: Category) -> s.PracticeSet:
    """What this category says itself — null where it defers to its parent."""
    config = CategoryConfig.model_validate(category.config) if category.config else CategoryConfig()
    practice = config.practice
    return s.PracticeSet(
        modes=practice.modes if practice else None,
        distractor_scope=practice.distractor_scope if practice else None,
    )


def _practice_resolved(config: CategoryConfig) -> s.PracticeResolved:
    return s.PracticeResolved(
        modes=effective_modes(config), distractor_scope=effective_distractor_scope(config)
    )


def _resolve_configs(rows: Sequence[Category]) -> dict[str, CategoryConfig]:
    """Inheritance for the whole tree in one pass.

    The rows come ordered by path, so a parent is always folded before its
    children and no ancestor has to be fetched again.
    """
    resolved: dict[str, CategoryConfig] = {}
    for row in rows:
        own = CategoryConfig.model_validate(row.config) if row.config else None
        parent = resolved.get(row.parent_id or "", CategoryConfig())
        resolved[row.id] = inherit(own, parent)
    return resolved


def _category_out(session: Session, category: Category) -> s.CategoryOut:
    return s.CategoryOut(
        id=category.id,
        parent_id=category.parent_id,
        path=category.path,
        slug=category.slug,
        label=category.label,
        practice=_practice_set(category),
        practice_resolved=_practice_resolved(category_config(session, category)),
    )


def _category_of_card(session: Session, card_key: str) -> str | None:
    """Which category a card belongs to, for resolving its scheduler.

    ``None`` when the card is unknown; the caller is about to raise its own 404
    for that, and a missing category simply falls back to the profile's setting.
    """
    return session.scalar(
        select(DataFileRow.category_id)
        .join(NoteRow, NoteRow.data_file_id == DataFileRow.id)
        .join(Card, Card.note_id == NoteRow.id)
        .where(Card.key == card_key)
    )


def _file_or_404(session: Session, file_id: str) -> DataFileRow:
    file = session.get(DataFileRow, file_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such data file.")
    return file


def _note_or_404(session: Session, note_id: str) -> NoteRow:
    note = session.get(NoteRow, note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such note.")
    return note


def _file_summary(file: DataFileRow, notes: int) -> s.DataFileSummary:
    return s.DataFileSummary(
        id=file.id,
        category_id=file.category_id,
        title=file.title,
        notes=notes,
        created_at=file.created_at,
        default_type=file.default_type,
        front_lang=file.front_lang,
        back_lang=file.back_lang,
        archived=file.archived_at is not None,
    )


def _reviewed(session: Session, notes: Sequence[NoteRow]) -> dict[str, int]:
    """How many answers each note has behind it — what makes archiving worth a warning."""
    owner = {card.key: note.id for note in notes for card in note.cards}
    if not owner:
        return {}
    counts: dict[str, int] = {}
    rows = session.execute(
        select(ReviewLog.card_key, func.count())
        .where(ReviewLog.card_key.in_(list(owner)))
        .group_by(ReviewLog.card_key)
    )
    for key, count in rows:
        counts[owner[key]] = counts.get(owner[key], 0) + count
    return counts


def _note_out(note: NoteRow, reviewed: dict[str, int], progress: dict[str, str]) -> s.NoteOut:
    return s.NoteOut(
        id=note.id,
        data_file_id=note.data_file_id,
        position=note.position,
        type=note.type,
        front=note.front,
        back=note.back,
        front_lang=note.front_lang,
        back_lang=note.back_lang,
        fields=note.fields,
        accept=note.accept,
        modes=note.modes,
        note=note.note,
        group=note.group.key if note.group else None,
        tags=note.tags,
        status=note.status,
        confidence=note.confidence,
        suspended=note.suspended,
        priority=note.priority,
        page=note.page,
        cards=len(note.cards),
        reviewed=reviewed.get(note.id, 0),
        archived=note.archived_at is not None,
        progress=progress.get(note.id, "new"),  # type: ignore[arg-type]
    )


def _one_note(session: Session, note: NoteRow) -> s.NoteOut:
    profile = _profile(session)
    return _note_out(note, _reviewed(session, [note]), note_buckets(session, profile, [note.id]))


def _notes_out(session: Session, file: DataFileRow, notes: Sequence[NoteRow]) -> s.NotesOut:
    """The grid and the sheet read the same endpoint — the sheet needs the markers."""
    reviewed = _reviewed(session, notes)
    profile = _profile(session)
    progress = note_buckets(session, profile, [note.id for note in notes])
    return s.NotesOut(
        file=_file_summary(file, len(live_notes(file))),
        groups=[s.GroupOut(key=g.key, label=g.label, note=g.note) for g in file.groups],
        notes=[_note_out(note, reviewed, progress) for note in notes],
    )


def _finding_out(finding: Finding) -> s.AuditFindingOut:
    return s.AuditFindingOut(
        key=finding.key,
        notes=[
            s.AuditNoteOut(
                note_id=note.note_id,
                front=note.front,
                back=note.back,
                file_title=note.file_title,
                data_file_id=note.data_file_id,
                category_path=note.category_path,
            )
            for note in finding.notes
        ],
    )


def _duplicate_rows(found: dict[int, list[Duplicate]]) -> list[s.DuplicateRow]:
    return [
        s.DuplicateRow(index=index, matches=[s.DuplicateOut(**asdict(m)) for m in matches])
        for index, matches in sorted(found.items())
    ]


def _job_out(job: ImportJob) -> s.ImportJobOut:
    return s.ImportJobOut(
        id=job.id,
        category_id=job.category_id,
        importer=job.importer,
        status=job.status,
        error=job.error,
        router_reason=(job.options or {}).get("router_reason"),
        pages=[
            s.ImportPageOut(
                id=p.id,
                position=p.position,
                path=p.path,
                page_number=p.page_number,
                status=p.status,
                error=p.error,
            )
            for p in job.pages
        ],
        draft=job.draft,
        target_data_file_id=job.target_data_file_id,
        created_at=job.created_at,
    )


# --- routers ----------------------------------------------------------------


def _auth_router(gate: Gate) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.get("/status", response_model=s.AuthStatus)
    def auth_status(request: Request, session: DB) -> s.AuthStatus:
        signed_in = gate.is_signed_in(request)
        return s.AuthStatus(
            signed_in=signed_in,
            gate_open=gate.open,
            profile=_profile(session).name if signed_in else None,
        )

    @router.post("/login", response_model=s.AuthStatus)
    def login(body: s.LoginIn, request: Request, response: Response, session: DB) -> s.AuthStatus:
        gate.login(client_id(request), body.password, response)
        return s.AuthStatus(signed_in=True, gate_open=gate.open, profile=_profile(session).name)

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(response: Response) -> Response:
        gate.logout(response)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    return router


def _api_router(
    settings: Settings,
    factory: sessionmaker[Session],
    gate: Gate,
    client_factory: Callable[[], LLMClient] | None,
) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(_signed_in)])

    # --- categories ---------------------------------------------------------

    @router.get("/categories", response_model=list[s.CategoryOut], tags=["collection"])
    def list_categories(session: DB) -> list[s.CategoryOut]:
        profile = _profile(session)
        scheduler = profile.scheduler or resolve_scheduler_name(session, profile, None)
        now = datetime.now(UTC)

        live = (NoteRow.archived_at.is_(None)) & (DataFileRow.archived_at.is_(None))
        notes = dict(
            session.execute(
                select(DataFileRow.category_id, func.count(NoteRow.id))
                .join(NoteRow, NoteRow.data_file_id == DataFileRow.id)
                .where(live)
                .group_by(DataFileRow.category_id)
            ).all()
        )
        card_base = (
            select(DataFileRow.category_id, func.count(Card.key))
            .join(NoteRow, NoteRow.data_file_id == DataFileRow.id)
            .join(Card, Card.note_id == NoteRow.id)
            .where(live)
            .group_by(DataFileRow.category_id)
        )
        cards = dict(session.execute(card_base).all())
        state_join = (
            (CardStateRow.card_key == Card.key)
            & (CardStateRow.profile_id == profile.id)
            & (CardStateRow.scheduler == scheduler)
        )
        seen = dict(session.execute(card_base.join(CardStateRow, state_join)).all())
        due = dict(
            session.execute(card_base.join(CardStateRow, state_join).where(CardStateRow.due <= now)).all()
        )

        rows = session.scalars(select(Category).order_by(Category.path)).all()
        resolved = _resolve_configs(rows)
        return [
            s.CategoryOut(
                id=c.id,
                parent_id=c.parent_id,
                path=c.path,
                slug=c.slug,
                label=c.label,
                practice=_practice_set(c),
                practice_resolved=_practice_resolved(resolved[c.id]),
                notes=notes.get(c.id, 0),
                cards=cards.get(c.id, 0),
                due=due.get(c.id, 0),
                new=cards.get(c.id, 0) - seen.get(c.id, 0),
            )
            for c in rows
        ]

    @router.post(
        "/categories", response_model=s.CategoryOut, status_code=status.HTTP_201_CREATED, tags=["collection"]
    )
    def create_category(body: s.CategoryIn, session: DB) -> s.CategoryOut:
        c = ensure_category(session, body.path, label=body.label)
        return _category_out(session, c)

    @router.get(
        "/categories/{category_id}/files", response_model=list[s.DataFileSummary], tags=["collection"]
    )
    def category_files(category_id: str, session: DB) -> list[s.DataFileSummary]:
        _category_or_404(session, category_id)
        rows = session.execute(
            select(DataFileRow, func.count(NoteRow.id))
            .outerjoin(
                NoteRow,
                (NoteRow.data_file_id == DataFileRow.id) & NoteRow.archived_at.is_(None),
            )
            .where(DataFileRow.category_id == category_id, DataFileRow.archived_at.is_(None))
            .group_by(DataFileRow.id)
            .order_by(DataFileRow.position, DataFileRow.created_at)
        ).all()
        return [_file_summary(f, count) for f, count in rows]

    @router.get("/files/{file_id}", tags=["collection"])
    def get_file(file_id: str, session: DB) -> dict:
        """The stored data file, in the interchange format (PLAN 3)."""
        try:
            return export_datafile(session, file_id).dumps()
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such data file.") from None

    # --- editing (PLAN 6, phase 2) ------------------------------------------

    @router.patch("/categories/{category_id}", response_model=s.CategoryOut, tags=["collection"])
    def patch_category(category_id: str, body: s.CategoryPatch, session: DB) -> s.CategoryOut:
        category = _category_or_404(session, category_id)
        fields = body.model_dump(exclude_unset=True)
        try:
            if "parent_id" in fields:
                move_category(session, category, fields["parent_id"])
            if "slug" in fields or "label" in fields:
                rename_category(session, category, slug=fields.get("slug"), label=fields.get("label"))
            if "practice" in fields:
                given = body.practice.model_dump(exclude_unset=True) if body.practice else None
                update_practice(
                    session,
                    category,
                    modes=given.get("modes", UNSET) if given is not None else None,
                    distractor_scope=given.get("distractor_scope", UNSET) if given is not None else None,
                )
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        return _category_out(session, category)

    @router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["collection"])
    def delete_category_route(category_id: str, session: DB) -> Response:
        category = _category_or_404(session, category_id)
        try:
            delete_category(session, category)
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/categories/{category_id}/files",
        response_model=s.DataFileSummary,
        status_code=status.HTTP_201_CREATED,
        tags=["collection"],
    )
    def new_file(category_id: str, body: s.DataFileIn, session: DB) -> s.DataFileSummary:
        category = _category_or_404(session, category_id)
        file = create_file(session, category, **body.model_dump(exclude_unset=True))
        return _file_summary(file, 0)

    @router.patch("/files/{file_id}", response_model=s.DataFileSummary, tags=["collection"])
    def patch_file(file_id: str, body: s.DataFilePatch, session: DB) -> s.DataFileSummary:
        file = _file_or_404(session, file_id)
        try:
            update_file(session, file, body.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        return _file_summary(file, len(live_notes(file)))

    @router.post("/files/{file_id}/archive", response_model=s.DataFileSummary, tags=["collection"])
    def archive_file_route(file_id: str, session: DB, restore: bool = False) -> s.DataFileSummary:
        file = archive_file(session, _file_or_404(session, file_id), archived=not restore)
        return _file_summary(file, len(live_notes(file)))

    @router.get("/files/{file_id}/notes", response_model=s.NotesOut, tags=["collection"])
    def file_notes(file_id: str, session: DB, archived: bool = False) -> s.NotesOut:
        """The grid editor's rows. ``archived=true`` adds the archived ones back."""
        file = _file_or_404(session, file_id)
        notes = file.notes if archived else live_notes(file)
        return _notes_out(session, file, notes)

    @router.post(
        "/files/{file_id}/notes",
        response_model=s.NotesCreatedOut,
        status_code=status.HTTP_201_CREATED,
        tags=["collection"],
    )
    def add_notes(file_id: str, body: s.NotesIn, session: DB) -> s.NotesCreatedOut:
        file = _file_or_404(session, file_id)
        items = [n.model_dump(exclude_unset=True) for n in body.notes]
        try:
            created = create_notes(session, file, items)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        found = find_duplicates(
            session,
            [(n.front, n.back) for n in body.notes],
            exclude_note_ids=[n.id for n in created],
        )
        return s.NotesCreatedOut(
            notes=[_note_out(n, {}, {}) for n in created],  # a new note is new
            duplicates=_duplicate_rows(found),
        )

    @router.post("/files/{file_id}/reorder", response_model=s.NotesOut, tags=["collection"])
    def reorder(file_id: str, body: s.ReorderIn, session: DB) -> s.NotesOut:
        file = _file_or_404(session, file_id)
        reorder_notes(session, file, body.note_ids)
        session.refresh(file)
        return _notes_out(session, file, live_notes(file))

    @router.get("/notes/search", response_model=s.SearchOut, tags=["collection"])
    def notes_search(
        session: DB,
        q: str,
        category_id: str | None = None,
        mark: str | None = None,
        standing: str | None = None,
        aside: bool | None = None,
        archived: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> s.SearchOut:
        """Find a word by any of the words it is written with.

        Searches both printed sides, the spellings it also accepts, its note, its
        heading and its lesson's title, and it finds suspended words on purpose —
        a word set aside is exactly the one you cannot otherwise get back to.
        """
        profile = _profile(session)
        try:
            hits, total = search(
                session,
                profile,
                q=q,
                category_id=category_id,
                mark=mark,
                standing=standing,
                aside=aside,
                archived=archived,
                limit=limit,
                offset=offset,
            )
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        return s.SearchOut(q=q, total=total, hits=[s.NoteHitOut(**asdict(hit)) for hit in hits])

    @router.patch("/notes/{note_id}", response_model=s.NoteOut, tags=["collection"])
    def patch_note(note_id: str, body: s.NoteIn, session: DB) -> s.NoteOut:
        note = _note_or_404(session, note_id)
        try:
            update_note(session, note, body.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        return _one_note(session, note)

    @router.post("/notes/{note_id}/archive", response_model=s.NoteOut, tags=["collection"])
    def archive_note_route(note_id: str, session: DB, restore: bool = False) -> s.NoteOut:
        """Archiving keeps the cards and the log — the note only leaves practice."""
        note = archive_note(session, _note_or_404(session, note_id), archived=not restore)
        return _one_note(session, note)

    @router.post("/notes/duplicates", response_model=s.DuplicateCheckOut, tags=["collection"])
    def duplicates(body: s.DuplicateCheckIn, session: DB) -> s.DuplicateCheckOut:
        try:
            found = find_duplicates(
                session,
                body.pairs,
                category_id=body.category_id,
                exclude_note_ids=body.exclude_note_ids,
            )
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such category.") from None
        return s.DuplicateCheckOut(rows=_duplicate_rows(found))

    @router.post("/notes/{note_id}/accept", response_model=s.AcceptOut, tags=["collection"])
    def accept_answer(note_id: str, body: s.AcceptIn, session: DB) -> s.AcceptOut:
        try:
            accepted = add_accepted(session, note_id, body.side, body.value)
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such note.") from None
        return s.AcceptOut(note_id=note_id, side=body.side, accepted=accepted)

    @router.get("/collection/audit", response_model=s.AuditOut, tags=["collection"])
    def audit_collection(session: DB, category_id: str | None = None) -> s.AuditOut:
        """What is wrong with the collection as practice would meet it (read-only).

        The same report ``memo audit`` prints, minus the hints: a screen that
        interrupts you should do it for something broken, not for something that
        might be. Two notes glossed the same way make an unanswerable prompt, and
        the extractor produces them honestly — so this has to be visible from the
        app rather than from a command nobody remembers to run.
        """
        try:
            report = audit(session, category_id=category_id)
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such category.") from None
        return s.AuditOut(
            clean=report.clean,
            collisions=[_finding_out(f) for f in report.collisions],
            duplicates=[_finding_out(f) for f in report.duplicates],
            one_sided=[
                _finding_out(Finding(key=normalise(a.back), notes=(a, b))) for a, b in report.one_sided
            ],
            near=[_finding_out(f) for f in report.near],
            resolved=[_finding_out(f) for f in report.resolved],
        )

    @router.get("/notes/{note_id}/related", response_model=s.RelatedListOut, tags=["collection"])
    def note_related(note_id: str, session: DB) -> s.RelatedListOut:
        """Other words in the collection with something to do with this one.

        Out of what is already written down, so it can offer words that mean the
        same or nearly the same thing, and whether the two already accept each
        other — not antonyms, which nothing in a note records.
        """
        try:
            found = related(session, note_id)
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such note.") from None
        return s.RelatedListOut(
            note_id=note_id,
            related=[
                s.RelatedOut(**{k: v for k, v in asdict(one).items() if k != "one_sided"}) for one in found
            ],
        )

    @router.post("/export", response_model=s.ExportOut, tags=["collection"])
    def export_to_tree(body: s.ExportIn, session: DB) -> s.ExportOut:
        """Write the readable copy of the collection (PLAN 5: manual, never automatic)."""
        try:
            report = export_tree(
                session,
                settings.export_dir,
                category_id=body.category_id,
                raw_root=settings.raw_dir,
            )
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such category.") from None
        return s.ExportOut(
            root=str(report.root),
            files=[
                s.ExportedFileOut(data_file_id=f.data_file_id, path=str(f.path), notes=f.notes)
                for f in report.files
            ],
            categories=len(report.categories),
            photos=len(report.photos),
            notes=report.notes,
            unknown=[str(p) for p in report.unknown],
        )

    # --- import -------------------------------------------------------------

    @router.get("/importers", response_model=list[s.ImporterOut], tags=["import"])
    def importers() -> list[s.ImporterOut]:
        registry = load_registry(settings.importers_dir)
        for error in registry.errors:
            log.warning("local importer skipped: %s", error)
        return [
            s.ImporterOut(name=i.name, description=i.description, origin=i.origin, kinds=list(i.kinds))
            for i in registry.all()
        ]

    @router.post(
        "/imports", response_model=s.ImportJobOut, status_code=status.HTTP_202_ACCEPTED, tags=["import"]
    )
    async def start_import(
        background: BackgroundTasks,
        request: Request,
        category_id: Annotated[str, Form()],
        files: Annotated[list[UploadFile], File()],
        importer: Annotated[str | None, Form()] = None,
        first_page: Annotated[int | None, Form()] = None,
        target_data_file_id: Annotated[str | None, Form()] = None,
        instructions: Annotated[str | None, Form()] = None,
        pdf_mode: Annotated[str | None, Form()] = None,
    ) -> s.ImportJobOut:
        uploads = []
        for f in files:
            content = await f.read()
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{f.filename} is too large.")
            uploads.append(Upload(filename=f.filename or "page.jpg", content=content))

        with factory() as session:
            category = _category_or_404(session, category_id)
            try:
                job = create_job(
                    session,
                    settings,
                    category,
                    uploads,
                    importer=importer or None,
                    first_page=first_page,
                    target_data_file_id=target_data_file_id or None,
                    instructions=instructions,
                    pdf_mode=pdf_mode or None,
                )
            except ValueError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
            session.commit()
            out = _job_out(job)

        background.add_task(
            run_job, factory, settings, out.id, client_factory=request.app.state.client_factory
        )
        return out

    @router.get("/imports", response_model=list[s.ImportJobOut], tags=["import"])
    def list_imports(session: DB, category_id: str | None = None) -> list[s.ImportJobOut]:
        query = select(ImportJob).order_by(ImportJob.created_at.desc()).limit(50)
        if category_id:
            query = query.where(ImportJob.category_id == category_id)
        return [_job_out(j) for j in session.scalars(query)]

    def _job(session: Session, job_id: str) -> ImportJob:
        job = session.get(ImportJob, job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such import.")
        return job

    @router.get("/imports/{job_id}", response_model=s.ImportJobOut, tags=["import"])
    def get_import(job_id: str, session: DB) -> s.ImportJobOut:
        return _job_out(_job(session, job_id))

    @router.patch("/imports/{job_id}", response_model=s.ImportJobOut, tags=["import"])
    def patch_import(job_id: str, body: s.ImportJobPatch, session: DB) -> s.ImportJobOut:
        """Change where a staged job will land, before it is committed."""
        job = _job(session, job_id)
        fields = body.model_dump(exclude_unset=True)
        try:
            if "category_id" in fields:
                move_job(session, job, _category_or_404(session, fields["category_id"]))
            if "target_data_file_id" in fields:
                set_job_target(session, job, fields["target_data_file_id"])
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        return _job_out(job)

    @router.delete("/imports/{job_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["import"])
    def delete_import(job_id: str, session: DB) -> None:
        """Throw a staged job away — the draft and the photos it was read from."""
        try:
            discard_job(session, settings, _job(session, job_id))
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None

    @router.put("/imports/{job_id}/draft", response_model=s.ImportJobOut, tags=["import"])
    def put_draft(job_id: str, draft: dict, session: DB) -> s.ImportJobOut:
        job = _job(session, job_id)
        try:
            save_draft(session, job, draft)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        if job.status == JobStatus.FAILED and job.draft:
            job.status = JobStatus.REVIEW  # a failed extraction can be rescued by hand
        return _job_out(job)

    @router.post("/imports/{job_id}/retry", response_model=s.ImportJobOut, tags=["import"])
    def retry_import(
        job_id: str, background: BackgroundTasks, request: Request, session: DB
    ) -> s.ImportJobOut:
        job = _job(session, job_id)
        if job.status in (JobStatus.RUNNING, JobStatus.COMMITTED):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Import is {job.status}.")
        job.status = JobStatus.PENDING
        # Commit now: the background task writes this row in its own session.
        session.commit()
        background.add_task(
            run_job, factory, settings, job.id, client_factory=request.app.state.client_factory
        )
        return _job_out(job)

    @router.post("/imports/{job_id}/commit", response_model=s.ImportJobOut, tags=["import"])
    def commit(job_id: str, session: DB) -> s.ImportJobOut:
        job = _job(session, job_id)
        try:
            commit_job(session, job)
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        return _job_out(job)

    @router.get("/raw/{path:path}", tags=["import"])
    def raw_file(path: str) -> FileResponse:
        """Uploaded photos, for the review screen. Never serves outside ``var/raw``."""
        root = settings.raw_dir.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such file.")
        return FileResponse(target)

    # --- practice -----------------------------------------------------------

    @router.get("/practice/queue", response_model=s.QueueOut, tags=["practice"])
    def queue(
        session: DB,
        category_id: str | None = None,
        file_id: str | None = None,
        group: str | None = None,
        list_id: str | None = None,
        drill: bool = False,
        direction: Annotated[Literal["fwd", "rev"] | None, Query()] = None,
        scheduler: str | None = None,
        new_limit: int | None = None,
        limit: Annotated[int | None, Query(ge=1)] = None,
        ahead: bool = True,
        distractor_scope: str | None = None,
        tz_offset: int = 0,
    ) -> s.QueueOut:
        """What to practise now, and how long a sitting of it will take.

        ``drill`` asks for everything in scope, due or not, instead of what the
        schedule wanted today — still capped by ``limit``. It is only half of a
        drill: how a missed word comes back is the client's own loop.

        ``direction`` asks a two-sided note only one way round — ``fwd`` for its
        front, ``rev`` for its back. A one-way note has no other side, so it is
        absent from the direction it does not have rather than asked backwards.

        ``list_id`` drills one list: every word on it, due or not. Without one,
        a list whose focus is still running leads the sitting instead, and the
        rest of it is filled exactly as it always was.

        ``tz_offset`` is the client's minutes ahead of UTC, for the same reason
        ``/progress`` takes it: the pace counts answers per day, and an evening
        sitting that crosses UTC midnight is one sitting, not two.
        """
        profile = _profile(session)
        # Started from a sheet: the settings are still the file's category's.
        if file_id is not None and category_id is None:
            category_id = _file_or_404(session, file_id).category_id
        try:
            found = due_queue(
                session,
                profile,
                category_id=category_id,
                file_id=file_id,
                group=group,
                list_id=list_id,
                drill=drill,
                direction=direction,
                scheduler=scheduler,
                new_limit=None if new_limit is None else max(0, new_limit),
                limit=limit,
                ahead=ahead,
                distractor_scope=distractor_scope,
            )
            allowed, scope = resolve_practice(session, category_id)
        except KeyError as exc:
            # A list and a category are both reachable by id here, so say which.
            missing = "list" if list_id is not None and list_id in str(exc) else "category"
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No such {missing}.") from None
        return s.QueueOut(
            scheduler=found.scheduler,
            modes=allowed,
            distractor_scope=distractor_scope or scope,
            cards=[s.QueueCardOut(**asdict(c)) for c in found.cards],
            due_count=found.due_count,
            new_count=found.new_count,
            ahead_count=found.ahead_count,
            total=found.total,
            next_due=found.next_due,
            ways=found.ways,
            seconds_per_card=pace(session, profile, tz_offset_minutes=max(-840, min(tz_offset, 840))),
        )

    @router.post("/practice/answer", response_model=s.AnswerOut, tags=["practice"])
    def answer(body: s.AnswerBody, session: DB) -> s.AnswerOut:
        profile = _profile(session)
        # Failing a scheduler named by the client, the card's own category decides
        # — the same resolution the queue made when it offered the card. Asking
        # without one used to land on the profile default, which writes to a
        # different `card_state` than the one the session was reading.
        name = body.scheduler or resolve_scheduler_name(
            session, profile, _category_of_card(session, body.card_key)
        )
        try:
            state = record_answer(
                session,
                profile,
                AnswerIn(
                    card_key=body.card_key,
                    mode=body.mode,
                    outcome=body.outcome,
                    grade=body.grade,
                    overridden=body.overridden,
                    raw_answer=body.raw_answer,
                    duration_ms=body.duration_ms,
                ),
                scheduler=name,
            )
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such card.") from None
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        return s.AnswerOut(card_key=body.card_key, scheduler=name, state=state.dump())

    @router.post("/practice/answers", response_model=s.AnswersOut, tags=["practice"])
    def answers(body: s.AnswersBody, session: DB) -> s.AnswersOut:
        """Answers earned with no server to tell — a phone out of reach (PLAN 5).

        The same batch may arrive twice, by wire and by file; ``client_id`` is what
        keeps that from counting twice.
        """
        profile = _profile(session)
        name = resolve_scheduler_name(session, profile, None)
        try:
            report = ingest_answers(
                session,
                profile,
                [
                    AnswerRow(
                        client_id=row.client_id,
                        at=row.at,
                        card_key=row.card_key,
                        mode=row.mode,
                        outcome=row.outcome,
                        grade=row.grade,
                        overridden=row.overridden,
                        raw_answer=row.raw_answer,
                        duration_ms=row.duration_ms,
                        scheduler=row.scheduler,
                    )
                    for row in body.rows
                ],
                scheduler=name,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        return s.AnswersOut(
            accepted=report.accepted,
            duplicates=report.duplicates,
            unknown=report.unknown,
            rebuilt=report.rebuilt,
            rejected=report.rejected,
        )

    # --- overview (PLAN 6, phase 4) -----------------------------------------

    @router.get("/progress", response_model=s.ProgressOut, tags=["overview"])
    def progress(
        session: DB,
        scheduler: str | None = None,
        window_days: int = WEAK_WINDOW_DAYS,
        limit: int = WEAK_LIMIT,
        days: int = ACTIVITY_DAYS,
        tz_offset: int = 0,
    ) -> s.ProgressOut:
        """What is known, what keeps going wrong, and what was answered when.

        ``tz_offset`` is the client's minutes ahead of UTC, so the activity grid
        is drawn in the days the person actually practised in.
        """
        profile = _profile(session)
        name = scheduler or resolve_scheduler_name(session, profile, None)
        if name not in SCHEDULERS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown scheduler {name}.")
        # One read of the log for both strips; `mastery` below makes its own.
        where = standings_since(session, profile)
        strong, _ = words(session, profile, MASTERED, limit=STRIP, where=where)
        unseen, _ = words(session, profile, NEW, limit=STRIP, where=where)
        _, set_aside = words(session, profile, SET_ASIDE, limit=0)
        return s.ProgressOut(
            scheduler=name,
            rule=s.MasteryRuleOut(
                known_points=KNOWN_POINTS,
                mastered_points=MASTERED_POINTS,
                writing_points=WRITING_POINTS,
                min_reviews=MIN_REVIEWS,
                rate_percent=round(RATE * 100),
                rate_window=RATE_WINDOW,
                spread_hours=round(MASTERY_SPREAD.total_seconds() / 3600),
            ),
            window_days=max(1, window_days),
            mastery=[s.MasteryOut(**asdict(row)) for row in mastery(session, profile)],
            files=[s.FileMasteryOut(**asdict(row)) for row in file_mastery(session, profile)],
            weak=[
                s.WeakCardOut(**asdict(row))
                for row in weak_cards(
                    session,
                    profile,
                    name,
                    window_days=max(1, window_days),
                    limit=max(1, min(limit, 200)),
                )
            ],
            activity=[
                s.DayOut(**asdict(row))
                for row in activity(
                    session,
                    profile,
                    days=max(1, min(days, 730)),
                    tz_offset_minutes=max(-840, min(tz_offset, 840)),
                )
            ],
            mastered=[s.WordOut(**asdict(word)) for word in strong],
            unseen=[s.WordOut(**asdict(word)) for word in unseen],
            set_aside=set_aside,
        )

    @router.get("/progress/words", response_model=s.WordsOut, tags=["overview"])
    def progress_words(
        session: DB,
        bucket: str = MASTERED,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
        file: str | None = None,
        category: str | None = None,
    ) -> s.WordsOut:
        """The whole of one of the lists the Progress page shows a glimpse of.

        ``bucket`` is a standing — ``new``, ``learning``, ``known``, ``mastered``
        — or ``set-aside``, which is not one: a word deliberately left out of
        practice, and until this existed the only way back to one was to remember
        which lesson it came from. ``file`` keeps one lesson, ``category`` one
        category and everything under it.
        """
        profile = _profile(session)
        path = _category_or_404(session, category).path if category else None
        try:
            found, total = words(
                session, profile, bucket, limit=limit, offset=offset, data_file_id=file, category_path=path
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        return s.WordsOut(
            bucket=bucket,
            total=total,
            words=[s.WordOut(**asdict(word)) for word in found],
        )

    @router.get("/progress/files/{file_id}", response_model=s.FileProgressOut, tags=["overview"])
    def progress_file(file_id: str, session: DB) -> s.FileProgressOut:
        """One lesson in full, for the screen Progress drills down to.

        Its counts, the same counts per heading, and every word in it under the
        bucket it is in — one read of the log for all of it.
        """
        file = _file_or_404(session, file_id)
        if file.archived_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such data file.")
        profile = _profile(session)
        counted = file_mastery(session, profile, data_file_id=file.id)
        summary = (
            s.FileMasteryOut(**asdict(counted[0]))
            if counted
            else s.FileMasteryOut(
                data_file_id=file.id,
                category_id=file.category_id,
                title=file.title,
                notes=0,
                new=0,
                learning=0,
                known=0,
                mastered=0,
                settled=0,
            )
        )
        where = standings_since(session, profile)
        return s.FileProgressOut(
            file=summary,
            groups=[s.GroupMasteryOut(**asdict(row)) for row in group_mastery(session, profile, file.id)],
            words={
                bucket: [
                    s.WordOut(**asdict(word))
                    for word in words(session, profile, bucket, where=where, data_file_id=file.id)[0]
                ]
                for bucket in (MASTERED, KNOWN, LEARNING, NEW)
            },
        )

    # --- lists ---------------------------------------------------------------

    @router.get("/lists", response_model=s.ListsOut, tags=["lists"])
    def get_lists(session: DB) -> s.ListsOut:
        """Every list, the focused ones first."""
        profile = _profile(session)
        return s.ListsOut(lists=[s.ListOut(**asdict(one)) for one in all_lists(session, profile)])

    @router.post("/lists", response_model=s.ListOut, status_code=status.HTTP_201_CREATED, tags=["lists"])
    def post_list(body: s.ListIn, session: DB) -> s.ListOut:
        profile = _profile(session)
        try:
            row = create_list(session, profile, name=body.name, note=body.note, focus_until=body.focus_until)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        return s.ListOut(**asdict(list_view(row)))

    @router.get("/lists/{list_id}", response_model=s.ListWordsOut, tags=["lists"])
    def get_one_list(list_id: str, session: DB) -> s.ListWordsOut:
        profile = _profile(session)
        try:
            row = get_list(session, profile, list_id)
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
        words = by_ids(session, profile, members(session, profile, list_id))
        return s.ListWordsOut(**asdict(list_view(row)), words=[s.NoteHitOut(**asdict(hit)) for hit in words])

    @router.patch("/lists/{list_id}", response_model=s.ListOut, tags=["lists"])
    def patch_list(list_id: str, body: s.ListPatchIn, session: DB) -> s.ListOut:
        """Rename a list, re-date its focus, or end it.

        A field left out of the body is left alone; a field sent as null is
        cleared, which is how a focus is ended rather than merely forgotten.
        """
        profile = _profile(session)
        sent = body.model_fields_set
        try:
            row = update_list(
                session,
                profile,
                list_id,
                name=body.name if "name" in sent else UNSET,
                note=body.note if "note" in sent else UNSET,
                focus_until=body.focus_until if "focus_until" in sent else UNSET,
            )
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        return s.ListOut(**asdict(list_view(row)))

    @router.delete("/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["lists"])
    def delete_one_list(list_id: str, session: DB) -> Response:
        """Forget the set. The words, their marks and their history stay as they are."""
        profile = _profile(session)
        try:
            delete_list(session, profile, list_id)
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/lists/{list_id}/notes", response_model=s.ListWordsOut, tags=["lists"])
    def post_list_notes(list_id: str, body: s.ListNotesIn, session: DB) -> s.ListWordsOut:
        """Add words: these ones, or a whole lesson, or one heading of one."""
        profile = _profile(session)
        try:
            row, _ = add_list_notes(
                session,
                profile,
                list_id,
                note_ids=body.note_ids,
                file_id=body.file_id,
                group=body.group,
            )
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        words = by_ids(session, profile, members(session, profile, list_id))
        return s.ListWordsOut(**asdict(list_view(row)), words=[s.NoteHitOut(**asdict(hit)) for hit in words])

    @router.delete("/lists/{list_id}/notes/{note_id}", response_model=s.ListOut, tags=["lists"])
    def delete_list_note(list_id: str, note_id: str, session: DB) -> s.ListOut:
        profile = _profile(session)
        try:
            row = remove_note(session, profile, list_id, note_id)
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
        return s.ListOut(**asdict(list_view(row)))

    # --- settings -----------------------------------------------------------

    @router.get("/settings", response_model=s.SettingsOut, tags=["settings"])
    def get_settings_route(session: DB) -> s.SettingsOut:
        profile = _profile(session)
        return _settings_out(settings, profile, session)

    @router.put("/settings", response_model=s.SettingsOut, tags=["settings"])
    def put_settings(body: s.SettingsIn, session: DB) -> s.SettingsOut:
        profile = _profile(session)
        if body.scheduler is not None:
            if body.scheduler not in SCHEDULERS:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown scheduler {body.scheduler}."
                )
            profile.scheduler = body.scheduler
        session.flush()
        return _settings_out(settings, profile, session)

    return router


def _settings_out(settings: Settings, profile: Profile, session: Session) -> s.SettingsOut:
    """Says whether an LLM key is configured — never what it is."""
    return s.SettingsOut(
        profile=profile.name,
        scheduler=resolve_scheduler_name(session, profile, None),
        schedulers=sorted(SCHEDULERS),
        llm_configured=settings.llm_api_key is not None,
        llm_model=settings.llm_model,
        structured_output=settings.llm_structured_output,
    )


def _mount_frontend(app: FastAPI) -> None:
    """Serve the static SvelteKit build, falling back to index.html for client routes."""
    build = Path(FRONTEND_BUILD)
    #: Hashed in their own names, so they can be kept for good.
    immutable = "public, max-age=31536000, immutable"
    #: The page itself is the one file that is rewritten in place, every build.
    fresh = "no-cache"

    #: Not in every interpreter's mime table, and an installable app depends on it.
    types = {".webmanifest": "application/manifest+json"}

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        if not build.is_dir():
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Frontend not built. Run `npm run build` in frontend/."
            )
        root = build.resolve()
        candidate = (root / path).resolve()
        if path and candidate.is_relative_to(root) and candidate.is_file():
            # The service worker's cache is per build, so it only ever asks for a
            # chunk it has not got; the browser's own cache can keep it for ever.
            cache = immutable if path.startswith("_app/immutable/") else fresh
            return FileResponse(
                candidate,
                headers={"cache-control": cache},
                media_type=types.get(candidate.suffix),
            )
        # A missing icon or chunk is a missing file, not the app: answering it with
        # the page and a 200 is what makes a broken asset look like it loaded.
        if PurePosixPath(path).suffix:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return FileResponse(root / "index.html", headers={"cache-control": fresh})
