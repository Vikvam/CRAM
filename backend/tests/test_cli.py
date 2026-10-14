"""The phase-0 command line (PLAN 6)."""

from __future__ import annotations

import json
import sqlite3

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from memo import cli
from memo.config import Settings
from tests.fakes import FakeLLM, as_json

runner = CliRunner()


@pytest.fixture
def var_dir(tmp_path, monkeypatch):
    """Point the whole app at a throwaway var/ (PLAN 5 layout)."""
    settings = Settings(var_dir=tmp_path / "var", llm_model="fake-model")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr("memo.config.get_settings", lambda: settings)
    return settings


@pytest.fixture
def fake_provider(monkeypatch, fixture_dir):
    """Every LLM call in the CLI answers with the golden extraction."""
    extraction = (fixture_dir / "vocab1.extraction.json").read_text(encoding="utf-8")
    created: list[FakeLLM] = []

    def factory(*_args, **_kwargs):
        client = FakeLLM(lambda messages: extraction)
        created.append(client)
        return client

    monkeypatch.setattr(cli, "LLMClient", factory)
    return created


def test_import_writes_a_draft_data_file(tmp_path, var_dir, fake_provider, sample_image, vocab1_raw):
    out = tmp_path / "draft.json"
    result = runner.invoke(
        cli.app,
        [
            "import",
            str(sample_image),
            "--importer",
            "korean-textbook-vocab",
            "--tier",
            "json_schema",
            "--first-page",
            "6",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    draft = json.loads(out.read_text(encoding="utf-8"))
    assert [n["front"] for n in draft["notes"]] == [n["front"] for n in vocab1_raw["notes"]]
    assert "32 notes, 3 groups, 0 flagged" in result.output


def test_import_can_store_straight_into_the_collection(tmp_path, var_dir, fake_provider, sample_image):
    result = runner.invoke(
        cli.app,
        [
            "import",
            str(sample_image),
            "--importer",
            "korean-textbook-vocab",
            "--tier",
            "text",
            "-o",
            str(tmp_path / "draft.json"),
            "--category",
            "korean/book1/02-introduction",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "stored as df_" in result.output
    assert var_dir.db_path.exists()


def test_store_then_export_reproduces_the_file(tmp_path, var_dir, fixture_dir, vocab1_text):
    source = fixture_dir / "vocab1.datafile.json"
    stored = runner.invoke(cli.app, ["store", str(source), "--category", "korean/book1"])
    assert stored.exit_code == 0, stored.output

    file_id = json.loads(vocab1_text)["id"]
    out = tmp_path / "exported.json"
    exported = runner.invoke(cli.app, ["export", file_id, "-o", str(out)])
    assert exported.exit_code == 0, exported.output
    assert out.read_text(encoding="utf-8") == vocab1_text


def test_import_refuses_a_missing_file(tmp_path, var_dir, fake_provider):
    result = runner.invoke(cli.app, ["import", str(tmp_path / "nope.jpg")])
    assert result.exit_code != 0
    assert "no such file" in result.output


def test_the_router_runs_when_no_importer_is_named(var_dir, monkeypatch, fixture_dir, sample_image):
    extraction = (fixture_dir / "vocab1.extraction.json").read_text(encoding="utf-8")
    answers = iter([as_json({"choice": 2, "why": "a Korean vocabulary table"}), extraction])
    monkeypatch.setattr(cli, "LLMClient", lambda *a, **k: FakeLLM(lambda m: next(answers)))
    result = runner.invoke(cli.app, ["import", str(sample_image), "--tier", "json_schema"])
    assert result.exit_code == 0, result.output
    assert "importer: korean-textbook-vocab — a Korean vocabulary table" in result.output


def test_schema_exports_both_schemas(tmp_path, var_dir):
    result = runner.invoke(cli.app, ["schema", "-o", str(tmp_path / "schema")])
    assert result.exit_code == 0, result.output
    storage = json.loads((tmp_path / "schema" / "memo.datafile.schema.json").read_text())
    strict = json.loads((tmp_path / "schema" / "memo.extraction.schema.json").read_text())
    assert storage["title"] == "DataFile"
    assert strict["additionalProperties"] is False, "the LLM-facing one is the strict variant"
    assert storage["additionalProperties"] is True, "the storage one keeps unknown keys"


def test_importers_are_listed_with_their_descriptions(var_dir):
    result = runner.invoke(cli.app, ["importers"])
    assert result.exit_code == 0
    assert "general" in result.output and "builtin" in result.output
    assert "korean-textbook-vocab" in result.output and "local" in result.output


def test_a_local_importer_that_fails_to_load_is_reported(tmp_path, monkeypatch):
    (tmp_path / "broken.toml").write_text('name = "broken"\n', encoding="utf-8")
    settings = Settings(var_dir=tmp_path / "var", importers_dir=tmp_path)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    result = runner.invoke(cli.app, ["importers"])
    assert result.exit_code == 0
    assert "skipped broken.toml: needs a description" in result.output


def test_import_refuses_an_importer_that_is_not_here(var_dir, fake_provider, sample_image):
    result = runner.invoke(cli.app, ["import", str(sample_image), "--importer", "nope"])
    assert result.exit_code != 0
    assert "no importer called 'nope'" in result.output


def test_import_fails_loudly_when_no_page_could_be_read(tmp_path, var_dir, monkeypatch, sample_image):
    from memo.llm.client import LLMError

    monkeypatch.setattr(cli, "LLMClient", lambda *a, **k: FakeLLM([LLMError("provider is down")]))
    result = runner.invoke(
        cli.app,
        [
            "import",
            str(sample_image),
            "--importer",
            "generic",
            "--tier",
            "text",
            "-o",
            str(tmp_path / "draft.json"),
        ],
    )
    assert result.exit_code == 1, "a draft with nothing in it is not a success"
    assert "provider is down" in result.output


# --- syncing and backups (PLAN 5) -------------------------------------------


def _one_card(var_dir, fixture_dir):
    """Store the sample lesson and give back one card key to answer."""
    runner.invoke(cli.app, ["store", str(fixture_dir / "vocab1.datafile.json"), "--category", "korean"])
    from memo.db.models import Card

    factory = cli._sessions()
    with factory() as session:
        return session.scalars(select(Card)).first().key


def test_import_answers_takes_in_a_file_from_the_phone(tmp_path, var_dir, fixture_dir):
    key = _one_card(var_dir, fixture_dir)
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "client_id": "01M4-phone-1",
                        "at": "2026-10-09T08:00:00+00:00",
                        "card_key": key,
                        "mode": "typed",
                        "outcome": "correct",
                        "raw_answer": "country",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(cli.app, ["import-answers", str(answers)])
    assert result.exit_code == 0, result.output
    assert "1 taken in" in result.output

    # The same file again — the hand-carried path after the upload already ran.
    again = runner.invoke(cli.app, ["import-answers", str(answers)])
    assert "0 taken in, 1 already here" in again.output


def test_import_answers_refuses_something_that_is_not_a_batch(tmp_path, var_dir):
    bad = tmp_path / "bad.json"
    bad.write_text('{"rows": "nope"}', encoding="utf-8")
    result = runner.invoke(cli.app, ["import-answers", str(bad)])
    assert result.exit_code == 2
    assert "Expected a list of answers" in result.output


def test_backup_writes_a_whole_database(tmp_path, var_dir, fixture_dir):
    _one_card(var_dir, fixture_dir)
    into = tmp_path / "backups"
    result = runner.invoke(cli.app, ["backup", "--to", str(into)])
    assert result.exit_code == 0, result.output

    copies = list(into.glob("memo-*.db"))
    assert len(copies) == 1
    with sqlite3.connect(copies[0]) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert copy.execute("SELECT count(*) FROM note").fetchone()[0] > 0


def test_backup_keeps_only_what_it_was_asked_to(tmp_path, var_dir, fixture_dir):
    _one_card(var_dir, fixture_dir)
    into = tmp_path / "backups"
    into.mkdir()
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        (into / f"memo-{day}.db").write_bytes(b"older")
    result = runner.invoke(cli.app, ["backup", "--to", str(into), "--keep", "2"])
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in into.glob("memo-*.db"))[:1] == ["memo-2026-10-03.db"], (
        "the oldest go first, today's is always kept"
    )


def test_backup_says_so_when_there_is_nothing_there(tmp_path, var_dir):
    result = runner.invoke(cli.app, ["backup", "--to", str(tmp_path / "backups")])
    assert result.exit_code == 1
    assert "nothing to back up" in result.output
