"""The format's promises (PLAN 3): null tolerant, lossless, versioned."""

from __future__ import annotations

import pytest

from memo.dataio import dump_json, load_json, round_trip, write_datafile
from memo.models.datafile import (
    CURRENT_VERSION,
    DataFile,
    NoteType,
    load_datafile,
)


def test_the_golden_fixture_round_trips_byte_for_byte(vocab1_text):
    assert dump_json(load_json(vocab1_text)) == vocab1_text


def test_an_almost_empty_file_loads(tmp_path):
    datafile = load_datafile({"format": "memo.datafile", "version": 1})
    assert datafile.notes == []
    assert datafile.groups == []
    # and survives a write/read cycle
    path = write_datafile(tmp_path / "empty.json", datafile)
    assert load_json(path.read_text(encoding="utf-8")).version == CURRENT_VERSION


def test_every_note_field_may_be_missing():
    note = load_datafile({"format": "memo.datafile", "version": 1, "notes": [{}]}).notes[0]
    assert note.front is None and note.back is None
    assert not note.is_practisable
    assert note.directions() == []


def test_a_note_missing_a_side_is_kept_and_flagged():
    datafile = load_datafile(
        {"format": "memo.datafile", "version": 1, "notes": [{"front": "러시아"}, {"front": "a", "back": "b"}]}
    )
    assert len(datafile.notes) == 2, "a broken note is flagged, never dropped"
    assert len(datafile.flagged()) == 1


def test_unknown_keys_survive_a_round_trip():
    raw = {
        "format": "memo.datafile",
        "version": 1,
        "invented_later": {"deep": [1, 2]},
        "notes": [{"front": "a", "back": "b", "audio": "x.mp3"}],
    }
    out = dump_json(load_datafile(raw))
    assert '"invented_later"' in out and '"audio"' in out


def test_nulls_inside_fields_are_preserved():
    datafile = load_datafile(
        {
            "format": "memo.datafile",
            "version": 1,
            "notes": [{"front": "a", "back": "b", "fields": {"romanization": None}}],
        }
    )
    assert round_trip(datafile).notes[0].fields == {"romanization": None}


def test_an_unknown_note_type_degrades_instead_of_failing():
    note = load_datafile(
        {"format": "memo.datafile", "version": 1, "notes": [{"type": "cloze", "front": "a", "back": "b"}]}
    ).notes[0]
    assert note.type is NoteType.DIRECTIONAL


def test_bidirectional_makes_two_cards_and_directional_one():
    datafile = load_datafile(
        {
            "format": "memo.datafile",
            "version": 1,
            "notes": [
                {"type": "bidirectional", "front": "러시아", "back": "Russia"},
                {"type": "directional", "front": "2+2", "back": "4"},
            ],
        }
    )
    assert [len(n.directions()) for n in datafile.notes] == [2, 1]


def test_type_falls_back_to_the_file_default():
    datafile = load_datafile(
        {
            "format": "memo.datafile",
            "version": 1,
            "default_type": "bidirectional",
            "notes": [{"front": "a", "back": "b"}],
        }
    )
    note = datafile.notes[0]
    assert note.resolved_type(datafile.note_default_type()) is NoteType.BIDIRECTIONAL


def test_a_future_version_is_refused_rather_than_misread():
    with pytest.raises(ValueError, match="version"):
        load_datafile({"format": "memo.datafile", "version": CURRENT_VERSION + 1})


def test_a_foreign_format_is_refused():
    with pytest.raises(ValueError, match="format"):
        load_datafile({"format": "anki.deck", "version": 1})


def test_a_title_written_as_a_language_map_is_read_as_one_line():
    """Files exported before the title became plain text still load, native side first."""
    loaded = load_datafile(
        {
            "format": "memo.datafile",
            "version": 1,
            "title": {"en": "Vocabulary & Expressions", "ko": "어휘와 표현"},
        }
    )
    assert loaded.title == "어휘와 표현 · Vocabulary & Expressions"


def test_a_plain_title_is_kept_exactly_as_written():
    """The bug this replaced: a title went through a language slot and came back doubled."""
    name = "2-2 · 이것이 무엇이에요? · What is this?"
    once = load_datafile({"format": "memo.datafile", "version": 1, "title": name})
    assert once.title == name
    assert round_trip(once).title == name


def test_every_version_below_current_has_a_migration():
    from memo.models.datafile import MIGRATIONS

    missing = [v for v in range(1, CURRENT_VERSION) if v not in MIGRATIONS]
    assert missing == [], f"no migration from version(s) {missing}"


def test_writing_is_atomic(tmp_path):
    target = tmp_path / "out.json"
    write_datafile(target, DataFile())
    assert target.exists()
    assert list(tmp_path.iterdir()) == [target], "no temp files left behind"
