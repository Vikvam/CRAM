"""a word can be marked for how often it should come up

Twenty words are on a test; they should dominate the next few sessions and then
stop dominating, without anyone having to go back and unmark them. The mark is
what the user sets, and how well the card is already known is what damps it.

Null for the ordinary middle, which is every word so far — so there is nothing
to backfill, and an export of a collection nobody has marked is byte for byte
what it was.

Revision ID: d7a2f3c91b64
Revises: c4e8f1a7b093
Create Date: 2026-10-11 10:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7a2f3c91b64"
down_revision: str | None = "c4e8f1a7b093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("note", schema=None) as batch_op:
        batch_op.add_column(sa.Column("priority", sa.String(length=8), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("note", schema=None) as batch_op:
        batch_op.drop_column("priority")
