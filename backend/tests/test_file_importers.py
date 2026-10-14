"""Files that read themselves: JSON, CSV, text, Anki (PLAN 6, phase 2)."""

from __future__ import annotations

import json
import sqlite3
import zipfile

import pytest

from memo.dataio.datafile_io import dump_json
from memo.importers.files import (
    UnreadableFile,
    merge_datafiles,
    read_structured_file,
    reader_for,
    strip_markup,
)


def test_what_each_extension_is_read_as():
    assert reader_for("words.CSV") == "csv"
    assert reader_for("deck.apkg") == "anki"
    assert reader_for("notes.md") == "text"
    assert reader_for("page.jpg") is None, "a photo still needs the model"


def test_a_data_file_this_app_wrote_comes_back(tmp_path, vocab1, vocab1_text):
    path = tmp_path / "2-1-vocabulary.json"
    path.write_text(vocab1_text, encoding="utf-8")

    name, datafile = read_structured_file(path)
    assert name == "json"
    assert [n.front for n in datafile.notes] == [n.front for n in vocab1.notes]
    assert [g.id for g in datafile.groups] == [g.id for g in vocab1.groups]
    assert datafile.title == vocab1.title
    assert datafile.id is None, "the ids belong to the collection it came from"
    assert all(n.id is None for n in datafile.notes)
    assert {n.status for n in datafile.notes} == {"unverified"}, "everything is reviewed again"


def test_a_plain_list_of_objects_is_read_too(tmp_path):
    path = tmp_path / "words.json"
    path.write_text(
        json.dumps(
            [
                {"term": "나라", "meaning": "country", "section": "Countries"},
                {"front": "한국", "back": "Korea", "note": "the country"},
                {"front": "", "back": "nothing"},
            ]
        ),
        encoding="utf-8",
    )
    _, datafile = read_structured_file(path)
    assert [(n.front, n.back) for n in datafile.notes] == [("나라", "country"), ("한국", "Korea")]
    assert datafile.notes[0].group == "Countries"
    assert datafile.notes[1].note == "the country"


def test_a_spreadsheet_with_a_header_uses_its_column_names(tmp_path):
    path = tmp_path / "vocab.csv"
    path.write_text(
        "Front,Back,Group,Note,Tags\n나라,country,Countries,,\n한국,Korea,Countries,a place,place korea\n",
        encoding="utf-8",
    )
    name, datafile = read_structured_file(path)
    assert name == "csv"
    assert [(n.front, n.back) for n in datafile.notes] == [("나라", "country"), ("한국", "Korea")]
    assert [g.id for g in datafile.groups] == ["Countries"]
    assert datafile.notes[1].tags == ["place", "korea"]


def test_a_spreadsheet_without_a_header_is_taken_in_order(tmp_path):
    path = tmp_path / "vocab.tsv"
    path.write_text("나라\tcountry\n한국\tKorea\n", encoding="utf-8")
    _, datafile = read_structured_file(path)
    assert [(n.front, n.back) for n in datafile.notes] == [("나라", "country"), ("한국", "Korea")]


def test_html_in_a_cell_does_not_reach_the_note(tmp_path):
    path = tmp_path / "vocab.csv"
    path.write_text("front,back\n<b>나라</b>,a&nbsp;country<br>\n", encoding="utf-8")
    _, datafile = read_structured_file(path)
    assert (datafile.notes[0].front, datafile.notes[0].back) == ("나라", "a country")


def test_text_pairs_and_the_headings_above_them(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text(
        "# my list\nCountries\n나라 = country\n한국 = Korea\nJobs\n학생 = student\n", encoding="utf-8"
    )
    name, datafile = read_structured_file(path)
    assert name == "text"
    assert [(n.front, n.back) for n in datafile.notes] == [
        ("나라", "country"),
        ("한국", "Korea"),
        ("학생", "student"),
    ]
    assert [n.group for n in datafile.notes] == ["Countries", "Countries", "Jobs"]


def test_a_text_file_with_no_pairs_says_so(tmp_path):
    path = tmp_path / "prose.txt"
    path.write_text("Just some prose about Korean.\nAnother sentence.\n", encoding="utf-8")
    with pytest.raises(UnreadableFile, match="no separator"):
        read_structured_file(path)


def _anki_deck(path, rows: list[tuple[str, str]]) -> None:
    """The part of an .apkg this reader needs: a zip with an SQLite collection."""
    db = path.parent / "collection.anki21"
    connection = sqlite3.connect(db)
    connection.execute("create table notes (id integer primary key, flds text, tags text)")
    for index, (front, back) in enumerate(rows):
        connection.execute(
            "insert into notes values (?, ?, ?)", (index, f"{front}\x1f{back}", " marked " if index else "")
        )
    connection.commit()
    connection.close()
    with zipfile.ZipFile(path, "w") as archive:
        archive.write(db, "collection.anki21")
    db.unlink()


def test_an_anki_deck_becomes_notes(tmp_path):
    path = tmp_path / "korean.apkg"
    _anki_deck(path, [("나라", "<div>country</div>"), ("한국", "Korea")])

    name, datafile = read_structured_file(path)
    assert name == "anki"
    assert [(n.front, n.back) for n in datafile.notes] == [("나라", "country"), ("한국", "Korea")]
    assert datafile.notes[1].tags == ["marked"]
    assert datafile.source is not None and datafile.source.kind == "anki"


def test_a_zip_that_is_not_a_deck_says_so(tmp_path):
    path = tmp_path / "not-a-deck.apkg"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "nothing here")
    with pytest.raises(UnreadableFile, match="no Anki collection"):
        read_structured_file(path)


def test_several_files_become_one_draft(tmp_path):
    (tmp_path / "a.csv").write_text("front,back,group\n나라,country,Countries\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("front,back,group\n학생,student,Jobs\n", encoding="utf-8")
    merged = merge_datafiles(
        [read_structured_file(tmp_path / "a.csv")[1], read_structured_file(tmp_path / "b.csv")[1]]
    )
    assert [n.front for n in merged.notes] == ["나라", "학생"]
    assert [g.id for g in merged.groups] == ["Countries", "Jobs"]
    assert merged.source is not None and merged.source.files == ["a.csv", "b.csv"]


def test_markup_stripping_keeps_the_text_only():
    assert strip_markup("<b>나라</b>&nbsp;<i>country</i>") == "나라 country"
    assert strip_markup("a &amp; b") == "a & b"


def test_an_exported_file_can_be_imported_again(session, tmp_path, vocab1):
    """PLAN 6, phase 2: export → import reproduces the notes."""
    from memo.collection.store import store_datafile
    from memo.dataio.export_tree import export_tree

    store_datafile(session, vocab1, category_path="korean/book1/02-introduction")
    export_tree(session, tmp_path)
    [path] = list((tmp_path / "korean/book1/02-introduction").glob("2-1-*.json"))

    _, again = read_structured_file(path)
    assert [(n.front, n.back) for n in again.notes] == [(n.front, n.back) for n in vocab1.notes]
    assert [n.accept.dumps() if n.accept else None for n in again.notes] == [
        n.accept.dumps() if n.accept else None for n in vocab1.notes
    ]
    assert dump_json(again) != dump_json(vocab1), "only the ids and statuses differ"
