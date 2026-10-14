"""Tables (PLAN 5).

They mirror the data file field for field — ``fields``/``extra`` stay JSON bags
so null tolerance and lossless round-trips survive the move into a database.
Progress is keyed on note IDs and directions, never on paths, so renaming or
moving a category keeps every review.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from memo.db.base import Base
from memo.db.types import UTCDateTime, utcnow

JSONDict = dict[str, Any]


class Profile(Base):
    """A person using the collection. No password of its own — see PLAN 5, auth."""

    __tablename__ = "profile"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    scheduler: Mapped[str | None] = mapped_column(String(16))
    settings: Mapped[JSONDict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Category(Base):
    """A node of the tree. ``path`` is materialised so subtree queries are one LIKE."""

    __tablename__ = "category"
    __table_args__ = (UniqueConstraint("parent_id", "slug", name="uq_category_sibling_slug"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("category.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(128))
    path: Mapped[str] = mapped_column(String(1024), index=True)
    label: Mapped[JSONDict | None] = mapped_column(JSON)
    config: Mapped[JSONDict | None] = mapped_column(JSON)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    parent: Mapped[Category | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Category]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    data_files: Mapped[list[DataFileRow]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class DataFileRow(Base):
    """One raw upload's worth of notes — the DB side of ``memo.datafile``."""

    __tablename__ = "data_file"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("category.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str | None] = mapped_column(String(128))
    #: One plain line — a file has a single name (PLAN 3.1), unlike a group's label.
    title: Mapped[str | None] = mapped_column(Text)
    default_type: Mapped[str | None] = mapped_column(String(16))
    front_lang: Mapped[str | None] = mapped_column(String(16))
    back_lang: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[JSONDict | None] = mapped_column(JSON)
    tags: Mapped[list[str] | None] = mapped_column(JSON)
    extra: Mapped[JSONDict | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    #: Set instead of deleting, so review history keeps its note (PLAN 6, phase 2).
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    category: Mapped[Category] = relationship(back_populates="data_files")
    groups: Mapped[list[NoteGroup]] = relationship(
        back_populates="data_file", cascade="all, delete-orphan", order_by="NoteGroup.position"
    )
    notes: Mapped[list[Note]] = relationship(
        back_populates="data_file", cascade="all, delete-orphan", order_by="Note.position"
    )


class NoteGroup(Base):
    """A heading inside a data file. ``key`` is the id notes refer to."""

    __tablename__ = "note_group"
    __table_args__ = (UniqueConstraint("data_file_id", "key", name="uq_group_key_per_file"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    data_file_id: Mapped[str] = mapped_column(ForeignKey("data_file.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(128))
    label: Mapped[JSONDict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[JSONDict | None] = mapped_column(JSON)

    data_file: Mapped[DataFileRow] = relationship(back_populates="groups")
    notes: Mapped[list[Note]] = relationship(back_populates="group")


class Note(Base):
    """PLAN 3.2. Everything but the id may be missing; a note lacking a side is
    kept and flagged rather than dropped."""

    __tablename__ = "note"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    data_file_id: Mapped[str] = mapped_column(ForeignKey("data_file.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[str | None] = mapped_column(ForeignKey("note_group.id", ondelete="SET NULL"))
    type: Mapped[str | None] = mapped_column(String(16))
    front: Mapped[str | None] = mapped_column(Text)
    back: Mapped[str | None] = mapped_column(Text)
    front_lang: Mapped[str | None] = mapped_column(String(16))
    back_lang: Mapped[str | None] = mapped_column(String(16))
    fields: Mapped[JSONDict | None] = mapped_column(JSON)
    accept: Mapped[JSONDict | None] = mapped_column(JSON)
    modes: Mapped[list[str] | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(JSON)
    status: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float)
    suspended: Mapped[bool | None] = mapped_column(Boolean)
    #: How often this word should come up (PLAN 3.2): ``low``, ``high`` or ``crucial``, and
    #: null for the ordinary middle, so nothing had to be backfilled.
    priority: Mapped[str | None] = mapped_column(String(8))
    page: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[JSONDict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    #: Archived notes keep their cards and log but leave practice, counts and exports.
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    data_file: Mapped[DataFileRow] = relationship(back_populates="notes")
    group: Mapped[NoteGroup | None] = relationship(back_populates="notes")
    cards: Mapped[list[Card]] = relationship(back_populates="note", cascade="all, delete-orphan")


class Card(Base):
    """One direction of one note. ``key`` is ``note_id:fwd|rev`` (PLAN 3.4)."""

    __tablename__ = "card"
    __table_args__ = (UniqueConstraint("note_id", "direction", name="uq_card_note_direction"),)

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    note_id: Mapped[str] = mapped_column(ForeignKey("note.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    note: Mapped[Note] = relationship(back_populates="cards")


class WordList(Base):
    """A named set of words — a test's worth of them — that is not a *place*.

    A note belongs to exactly one data file and a file to one category, so a
    "test sub-collection" built out of the tree would mean moving words out of
    the lesson they came from, which no API can do and nobody should want. A list
    is a selection instead: the notes stay where they are and keep their marks,
    their cards and their history.

    ``focus_until`` is what makes it worth having. The mark on a note is
    permanent and global, so using it for a test leaves sediment — which is how a
    collection ends up with more than half its words marked and the mark meaning
    nothing. A focus is dated: it pushes its words up the queue until the date
    passes and then stops, with nothing to remember to undo. The list itself
    outlives the focus, because what was on a test is worth keeping and worth
    being able to drill again.
    """

    __tablename__ = "word_list"
    __table_args__ = (UniqueConstraint("profile_id", "name", name="uq_word_list_name_per_profile"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profile.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)
    #: While this is in the future the list's words are pushed up the queue.
    #: Null is a list that simply exists; a past date is one whose test has been.
    focus_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    notes: Mapped[list[WordListNote]] = relationship(
        back_populates="word_list", cascade="all, delete-orphan", order_by="WordListNote.position"
    )


class WordListNote(Base):
    """One word's membership of one list. Deleting the list deletes only this."""

    __tablename__ = "word_list_note"

    list_id: Mapped[str] = mapped_column(ForeignKey("word_list.id", ondelete="CASCADE"), primary_key=True)
    note_id: Mapped[str] = mapped_column(ForeignKey("note.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    word_list: Mapped[WordList] = relationship(back_populates="notes")
    note: Mapped[Note] = relationship()


class CardState(Base):
    """Scheduler state — a cache, recomputable from :class:`ReviewLog`.

    Keyed by scheduler as well as profile, so SM-2 and FSRS can be compared on
    the same history without either overwriting the other.
    """

    __tablename__ = "card_state"

    profile_id: Mapped[str] = mapped_column(ForeignKey("profile.id", ondelete="CASCADE"), primary_key=True)
    card_key: Mapped[str] = mapped_column(ForeignKey("card.key", ondelete="CASCADE"), primary_key=True)
    scheduler: Mapped[str] = mapped_column(String(16), primary_key=True)
    due: Mapped[datetime | None] = mapped_column(UTCDateTime)
    state: Mapped[str | None] = mapped_column(String(16))
    interval_days: Mapped[float | None] = mapped_column(Float)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    last_review: Mapped[datetime | None] = mapped_column(UTCDateTime)
    data: Mapped[JSONDict | None] = mapped_column(JSON)


Index("ix_card_state_due", CardState.profile_id, CardState.scheduler, CardState.due)


class ReviewLog(Base):
    """Append-only evidence (PLAN 5). Never updated, never deleted: any scheduler,
    present or future, can be recomputed from it."""

    __tablename__ = "review_log"
    # Nulls never collide, so this constrains only the rows handed in from a client.
    __table_args__ = (Index("ix_review_log_client", "profile_id", "client_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profile.id", ondelete="CASCADE"), index=True)
    card_key: Mapped[str] = mapped_column(String(40), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    #: Set by whoever recorded the answer offline; unique per profile, so a batch
    #: handed back twice lands once. Null for every row the server recorded itself.
    client_id: Mapped[str | None] = mapped_column(String(32))
    mode: Mapped[str | None] = mapped_column(String(16))
    direction: Mapped[str | None] = mapped_column(String(3))
    raw_answer: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(16))
    overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    final_grade: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    scheduler: Mapped[str | None] = mapped_column(String(16))
    state_before: Mapped[JSONDict | None] = mapped_column(JSON)
    state_after: Mapped[JSONDict | None] = mapped_column(JSON)


class ImportJob(Base):
    """One upload of one or more raw files → one data file (PLAN 4)."""

    __tablename__ = "import_job"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("category.id", ondelete="SET NULL"))
    target_data_file_id: Mapped[str | None] = mapped_column(ForeignKey("data_file.id", ondelete="SET NULL"))
    importer: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    draft: Mapped[JSONDict | None] = mapped_column(JSON)
    options: Mapped[JSONDict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    pages: Mapped[list[ImportPage]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="ImportPage.position"
    )


class ImportPage(Base):
    """One raw file in a job. The file itself lives under ``var/raw`` (PLAN 5)."""

    __tablename__ = "import_page"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("import_job.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str | None] = mapped_column(String(1024))
    page_number: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    extraction: Mapped[JSONDict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    job: Mapped[ImportJob] = relationship(back_populates="pages")
