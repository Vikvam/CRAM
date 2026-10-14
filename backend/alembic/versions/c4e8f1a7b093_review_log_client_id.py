"""a review row can be given an id by whoever recorded it

Answers earned on the phone with no network are kept there and handed back
later, and the same batch may travel twice — once over the wire when the laptop
comes back into reach, once as a file the user moves by hand. The unique index
is what makes that safe: a row offered a second time is recognised and dropped,
so neither path has to know what the other did.

Null for everything the server recorded itself, which is every row so far.

Revision ID: c4e8f1a7b093
Revises: b1c7a9d4e2f3
Create Date: 2026-10-10 11:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8f1a7b093"
down_revision: str | None = "b1c7a9d4e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("review_log", schema=None) as batch_op:
        batch_op.add_column(sa.Column("client_id", sa.String(length=32), nullable=True))
        # Nulls do not collide in SQLite, so the rows the server recorded are unaffected.
        batch_op.create_index("ix_review_log_client", ["profile_id", "client_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("review_log", schema=None) as batch_op:
        batch_op.drop_index("ix_review_log_client")
        batch_op.drop_column("client_id")
