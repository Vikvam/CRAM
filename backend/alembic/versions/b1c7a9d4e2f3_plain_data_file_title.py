"""a data file title is one plain line, not a language map

Version 1 files wrote ``{"ko": "어휘와 표현", "en": "Vocabulary & Expressions"}``
and the UI showed both sides joined — which meant the title box round-tripped a
rendered string back into the English slot, prepending the native title again on
every rename. A title is now a single line, joined the way it used to be shown.

Revision ID: b1c7a9d4e2f3
Revises: e6765348b268
Create Date: 2026-10-01 10:40:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c7a9d4e2f3"
down_revision: str | None = "e6765348b268"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _joined(raw: str | None) -> str | None:
    """``{"ko": "가", "en": "A"}`` → ``"가 · A"``, English last, repeats dropped."""
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return raw or None  # already plain text
    if isinstance(value, dict):
        entries = sorted(value.items(), key=lambda kv: kv[0] == "en")
        parts = [str(v).strip() for _, v in entries if str(v).strip()]
        return " · ".join(dict.fromkeys(parts)) or None
    if isinstance(value, str):
        return value.strip() or None
    return None


def upgrade() -> None:
    bind = op.get_bind()
    # Read the JSON before the column stops being JSON; SQLite keeps the same text either way.
    titles = {row[0]: _joined(row[1]) for row in bind.execute(sa.text("SELECT id, title FROM data_file"))}
    with op.batch_alter_table("data_file", schema=None) as batch_op:
        batch_op.alter_column("title", existing_type=sa.JSON(), type_=sa.Text(), existing_nullable=True)
    update = sa.text("UPDATE data_file SET title = :title WHERE id = :id")
    for file_id, title in titles.items():
        bind.execute(update, {"title": title, "id": file_id})


def downgrade() -> None:
    bind = op.get_bind()
    titles = {row[0]: row[1] for row in bind.execute(sa.text("SELECT id, title FROM data_file"))}
    with op.batch_alter_table("data_file", schema=None) as batch_op:
        batch_op.alter_column("title", existing_type=sa.Text(), type_=sa.JSON(), existing_nullable=True)
    # The split is gone for good; what is left goes back under one key.
    update = sa.text("UPDATE data_file SET title = :title WHERE id = :id")
    for file_id, title in titles.items():
        value = json.dumps({"en": title}, ensure_ascii=False) if title else None
        bind.execute(update, {"title": value, "id": file_id})
