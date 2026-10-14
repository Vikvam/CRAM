"""Migrations, not scripts over files — the price of storage option D (PLAN 5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from memo.db import Base, make_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    db_path = tmp_path / "memo.db"
    # env.py asks memo.config for the URL; keep it pointed at the throwaway file.
    from memo.config import Settings

    monkeypatch.setattr("memo.config.get_settings", lambda: Settings(var_dir=tmp_path))
    command.upgrade(_alembic_config(db_path), "head")
    return db_path


def test_migrating_from_scratch_matches_the_models(migrated):
    """If this fails, someone changed a model without an `alembic revision`."""
    from_migrations = inspect(make_engine(migrated))
    expected = Base.metadata.tables

    assert set(from_migrations.get_table_names()) - {"alembic_version"} == set(expected)
    for name, table in expected.items():
        columns = {c["name"] for c in from_migrations.get_columns(name)}
        assert columns == set(table.columns.keys()), f"{name} differs from the model"


def test_downgrade_returns_to_an_empty_database(migrated, tmp_path):
    command.downgrade(_alembic_config(migrated), "base")
    remaining = set(inspect(make_engine(migrated)).get_table_names())
    assert remaining <= {"alembic_version"}


def test_foreign_keys_are_enforced(migrated):
    """WAL and enforced foreign keys are set per connection, not per database."""
    from sqlalchemy import text

    engine = make_engine(migrated)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_a_title_written_as_a_label_map_becomes_one_line(tmp_path, monkeypatch):
    """The upgrade that made a data file title plain text has to carry the old ones."""
    from sqlalchemy import text

    from memo.config import Settings

    db_path = tmp_path / "memo.db"
    monkeypatch.setattr("memo.config.get_settings", lambda: Settings(var_dir=tmp_path))
    config = _alembic_config(db_path)
    command.upgrade(config, "e6765348b268")  # the last revision with a JSON title

    engine = make_engine(db_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO category (id, slug, path, position, created_at)"
                " VALUES ('cat_x', 'korean', 'korean', 1, '2026-10-01 00:00:00')"
            )
        )
        for file_id, title in [
            ("df_both", '{"ko": "\\uc5b4\\ud718\\uc640 \\ud45c\\ud604", "en": "Vocabulary"}'),
            ("df_one", '{"en": "Words"}'),
            ("df_none", None),
        ]:
            connection.execute(
                text(
                    "INSERT INTO data_file (id, category_id, title, version, position,"
                    " created_at, updated_at) VALUES (:id, 'cat_x', :title, 1, 1,"
                    " '2026-10-01 00:00:00', '2026-10-01 00:00:00')"
                ),
                {"id": file_id, "title": title},
            )

    command.upgrade(config, "head")

    with make_engine(db_path).connect() as connection:
        titles = dict(connection.execute(text("SELECT id, title FROM data_file")).all())
    assert titles == {"df_both": "어휘와 표현 · Vocabulary", "df_one": "Words", "df_none": None}
