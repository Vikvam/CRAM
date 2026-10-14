"""File → database → file (PLAN 5): storage option D must not become a one-way door."""

from __future__ import annotations

from memo.collection import export_datafile, store_datafile
from memo.collection.categories import category_config, ensure_category, slugify
from memo.collection.store import card_key, sync_cards
from memo.dataio import dump_json
from memo.db.models import Card, Category
from memo.db.models import Note as NoteRow
from memo.models.datafile import DataFile, Note, NoteType


def test_the_fixture_survives_a_trip_through_the_database(session, vocab1, vocab1_text):
    store_datafile(session, vocab1, category_path="korean/book1/02-introduction")
    session.flush()
    assert dump_json(export_datafile(session, vocab1.id)) == vocab1_text


def test_storing_creates_the_whole_category_path(session, vocab1):
    store_datafile(session, vocab1, category_path="korean/book1/02-introduction")
    paths = sorted(c.path for c in session.query(Category).all())
    assert paths == ["korean", "korean/book1", "korean/book1/02-introduction"]


def test_a_second_file_reuses_the_existing_categories(session, vocab1):
    store_datafile(session, vocab1, category_path="korean/book1")
    store_datafile(session, DataFile(), category_path="korean/book1")
    assert session.query(Category).count() == 2


def test_each_bidirectional_note_gets_two_cards(session, vocab1):
    store_datafile(session, vocab1, category_path="korean")
    assert session.query(Card).count() == 2 * len(vocab1.notes)


def test_card_keys_are_note_id_plus_direction(session, vocab1):
    store_datafile(session, vocab1, category_path="korean")
    note = vocab1.notes[0]
    keys = {c.key for c in session.query(Card).filter(Card.note_id == note.id)}
    assert keys == {f"{note.id}:fwd", f"{note.id}:rev"}


def test_a_note_missing_a_side_gets_no_cards(session):
    datafile = DataFile(
        default_type=NoteType.BIDIRECTIONAL,
        notes=[Note(id="n_broken", front="러시아"), Note(id="n_ok", front="중국", back="China")],
    )
    store_datafile(session, datafile, category_path="korean")
    assert {c.note_id for c in session.query(Card).all()} == {"n_ok"}


def test_turning_a_note_directional_drops_the_reverse_card_only(session, vocab1):
    store_datafile(session, vocab1, category_path="korean")
    session.flush()
    note_id = vocab1.notes[0].id
    row = session.get(NoteRow, note_id)
    row.type = NoteType.DIRECTIONAL.value
    sync_cards(session, row, NoteType.BIDIRECTIONAL)
    session.flush()
    assert {c.key for c in session.query(Card).filter(Card.note_id == note_id)} == {f"{note_id}:fwd"}


def test_syncing_an_unchanged_note_keeps_the_same_cards(session, vocab1):
    """Card keys carry the review history, so they must not churn."""
    store_datafile(session, vocab1, category_path="korean")
    session.flush()
    row = session.get(NoteRow, vocab1.notes[0].id)
    before = {c.key for c in row.cards}
    sync_cards(session, row, NoteType.BIDIRECTIONAL)
    session.flush()
    assert {c.key for c in session.get(NoteRow, row.id).cards} == before


def test_card_key_is_stable_for_a_string_direction():
    assert card_key("n_1", "rev") == "n_1:rev"


def test_settings_are_inherited_down_the_tree(session):
    korean = ensure_category(session, "korean")
    korean.config = {
        "format": "memo.category",
        "version": 1,
        "front_lang": "ko",
        "practice": {"modes": ["flip", "typed"], "adaptive": True},
    }
    lesson = ensure_category(session, "korean/book1/02-introduction")
    lesson.config = {"format": "memo.category", "version": 1, "practice": {"distractor_scope": "group"}}
    session.flush()

    resolved = category_config(session, lesson)
    assert resolved.front_lang == "ko"
    assert resolved.practice.modes == ["flip", "typed"], "not restated, so inherited"
    assert resolved.practice.distractor_scope == "group", "restated, so overridden"


def test_paths_are_slugified_but_stay_unicode():
    assert slugify("02 Introduction") == "02-introduction"
    assert slugify("한국어") == "한국어"
