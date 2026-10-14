"""a named set of words, and a dated focus on it

A test's words want to dominate a few sessions and then stop. The mark on a note
cannot do that: it is permanent and global, so each test leaves sediment behind
it. These two tables hold the set instead — a selection, not a place, so nothing
moves out of the lesson it came from — and ``focus_until`` is what expires.

Nothing here touches ``note``, ``card_state`` or ``review_log``: a list reorders
a queue and is never written into a card's history.

Revision ID: f1a4d8e62c37
Revises: e3b9c27d4f15
Create Date: 2026-10-11 19:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import memo.db.types

revision: str = "f1a4d8e62c37"
down_revision: str | None = "e3b9c27d4f15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "word_list",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("focus_until", memo.db.types.UTCDateTime(), nullable=True),
        sa.Column("created_at", memo.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", memo.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "name", name="uq_word_list_name_per_profile"),
    )
    with op.batch_alter_table("word_list", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_word_list_profile_id"), ["profile_id"], unique=False)

    op.create_table(
        "word_list_note",
        sa.Column("list_id", sa.String(length=32), nullable=False),
        sa.Column("note_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("added_at", memo.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["list_id"], ["word_list.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["note_id"], ["note.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("list_id", "note_id"),
    )


def downgrade() -> None:
    op.drop_table("word_list_note")
    with op.batch_alter_table("word_list", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_word_list_profile_id"))
    op.drop_table("word_list")
