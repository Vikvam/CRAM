"""a fourth level of mark, and the quietest one renamed

The levels are now low · normal · high · crucial. ``crucial`` is new and needs
nothing here; ``quiet`` is the same level under its new name, so the rows that
carry it are renamed in place. Normal stays null.

Revision ID: e3b9c27d4f15
Revises: d7a2f3c91b64
Create Date: 2026-10-11 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e3b9c27d4f15"
down_revision: str | None = "d7a2f3c91b64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE note SET priority = 'low' WHERE priority = 'quiet'")


def downgrade() -> None:
    # There was no level above high, so crucial goes back to the nearest one.
    op.execute("UPDATE note SET priority = 'high' WHERE priority = 'crucial'")
    op.execute("UPDATE note SET priority = 'quiet' WHERE priority = 'low'")
