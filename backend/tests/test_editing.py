"""Making and changing the collection by hand (PLAN 6, phase 2)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from memo.collection.categories import (
    delete_category,
    ensure_category,
    move_category,
    rename_category,
)
from memo.collection.editing import (
    archive_file,
    archive_note,
    create_file,
    create_notes,
    find_duplicates,
    live_notes,
    normalise,
    reorder_notes,
    update_file,
    update_note,
)
from memo.collection.profiles import get_or_create_profile
from memo.collection.store import export_datafile, store_datafile
from memo.dataio import dump_json
from memo.practice.service import due_queue


@pytest.fixture
def file(session: Session):
    category = ensure_category(session, "korean/book1/02-introduction")
    return create_file(
        session,
        category,
        title="2-1 Vocabulary",
        front_lang="ko",
        back_lang="en",
        default_type="bidirectional",
    )


def test_create_notes_makes_cards_per_the_file_default(session, file):
    [note] = create_notes(session, file, [{"front": "나라", "back": "country"}])
    assert sorted(card.direction for card in note.cards) == ["fwd", "rev"]
    assert note.position == 1

    second = create_notes(session, file, [{"front": "한국", "back": "Korea", "type": "directional"}])
    assert [card.direction for card in second[0].cards] == ["fwd"]


def test_a_note_without_both_sides_is_kept_but_makes_no_cards(session, file):
    [note] = create_notes(session, file, [{"front": "나라", "back": ""}])
    assert note.cards == []
    assert live_notes(file) == [note]


def test_filling_in_the_missing_side_gives_the_note_its_cards(session, file):
    [note] = create_notes(session, file, [{"front": "나라"}])
    update_note(session, note, {"back": "country"})
    assert len(note.cards) == 2


def test_a_group_is_made_on_first_use_and_reused(session, file):
    notes = create_notes(
        session,
        file,
        [
            {"front": "나라", "back": "country", "group": "나라"},
            {"front": "한국", "back": "Korea", "group": "나라"},
        ],
    )
    assert len(file.groups) == 1
    assert {n.group_id for n in notes} == {file.groups[0].id}

    update_note(session, notes[1], {"group": None})
    assert notes[1].group_id is None


def test_changing_the_file_default_type_restates_its_cards(session, file):
    [note] = create_notes(session, file, [{"front": "나라", "back": "country"}])
    keys_before = {card.key for card in note.cards}

    update_file(session, file, {"default_type": "directional"})
    session.refresh(note)
    assert [card.direction for card in note.cards] == ["fwd"]
    # The surviving card keeps its key, so its history is still its own.
    assert {card.key for card in note.cards} <= keys_before


def test_the_editor_refuses_fields_it_does_not_own(session, file):
    with pytest.raises(ValueError, match="cannot set"):
        create_notes(session, file, [{"front": "나라", "id": "n_forged"}])


def test_archiving_keeps_the_cards_but_empties_practice(session, file):
    notes = create_notes(
        session, file, [{"front": "나라", "back": "country"}, {"front": "한국", "back": "Korea"}]
    )
    profile = get_or_create_profile(session)
    assert len(due_queue(session, profile).cards) == 4

    archive_note(session, notes[0])
    assert len(notes[0].cards) == 2  # the history still has something to point at
    assert live_notes(file) == [notes[1]]
    assert len(due_queue(session, profile).cards) == 2

    archive_note(session, notes[0], archived=False)
    assert len(due_queue(session, profile).cards) == 4


def test_the_queue_is_shuffled_but_reproducible_with_a_seed(session, file):
    """You should learn the cards, not the order the page printed them in."""
    import random

    create_notes(session, file, [{"front": str(i), "back": f"b{i}"} for i in range(30)])
    profile = get_or_create_profile(session)

    first = [c.key for c in due_queue(session, profile, rng=random.Random(1)).cards]
    again = [c.key for c in due_queue(session, profile, rng=random.Random(1)).cards]
    other = [c.key for c in due_queue(session, profile, rng=random.Random(2)).cards]

    assert first == again, "the same seed replays the same session"
    assert first != other, "a different session asks them in a different order"
    assert sorted(first) == sorted(other), "and always the same cards"


def test_the_two_directions_of_a_note_are_never_asked_back_to_back(session, file):
    import random

    create_notes(session, file, [{"front": str(i), "back": f"b{i}"} for i in range(10)])
    profile = get_or_create_profile(session)

    for seed in range(20):
        notes = [c.note_id for c in due_queue(session, profile, rng=random.Random(seed)).cards]
        assert all(a != b for a, b in zip(notes, notes[1:], strict=False)), f"seed {seed}"


def test_new_cards_are_still_taken_from_the_front_of_the_book(session, file):
    """Shuffling changes the order you meet them, not which ones you get."""
    import random

    create_notes(session, file, [{"front": str(i), "back": f"b{i}"} for i in range(30)])
    profile = get_or_create_profile(session)

    cards = due_queue(session, profile, new_limit=6, rng=random.Random(3)).cards
    assert {c.prompt for c in cards} == {"0", "b0", "1", "b1", "2", "b2"}


def test_a_mark_survives_the_round_trip_and_an_unmarked_word_writes_nothing(session, file):
    notes = create_notes(
        session, file, [{"front": "나라", "back": "country"}, {"front": "한국", "back": "Korea"}]
    )
    update_note(session, notes[0], {"priority": "high"})
    exported = export_datafile(session, file.id)
    assert [n.priority for n in exported.notes] == ["high", None]

    written = json.loads(dump_json(exported))["notes"]
    assert written[0]["priority"] == "high"
    assert "priority" not in written[1], "an unmarked word writes nothing, as it always did"

    exported.id = None  # a fresh copy, the way a file carried between collections arrives
    for note in exported.notes:
        note.id = None
    again = store_datafile(session, exported, category_path="korean/book1/again")
    assert [n.priority for n in again.notes] == ["high", None]


def test_archived_notes_leave_the_exported_file(session, file):
    notes = create_notes(
        session, file, [{"front": "나라", "back": "country"}, {"front": "한국", "back": "Korea"}]
    )
    archive_note(session, notes[1])
    exported = export_datafile(session, file.id)
    assert [n.front for n in exported.notes] == ["나라"]


def test_archiving_a_file_archives_its_notes(session, file):
    create_notes(session, file, [{"front": "나라", "back": "country"}])
    archive_file(session, file)
    assert live_notes(file) == []
    assert len(due_queue(session, get_or_create_profile(session)).cards) == 0

    archive_file(session, file, archived=False)
    assert len(live_notes(file)) == 1


def test_reorder_puts_the_named_notes_first(session, file):
    a, b, c = create_notes(
        session,
        file,
        [{"front": "1", "back": "one"}, {"front": "2", "back": "two"}, {"front": "3", "back": "three"}],
    )
    reorder_notes(session, file, [c.id, a.id])
    session.refresh(file)
    assert [n.front for n in file.notes] == ["3", "1", "2"]


# --- duplicates -------------------------------------------------------------


def test_normalise_ignores_case_and_spacing():
    assert normalise("  To   GO ") == normalise("to go")
    assert normalise(None) == ""


def test_normalise_folds_dashes_nobody_can_type():
    """The model transcribes the book's en dash; you type a hyphen (spec §1.2)."""
    assert normalise("–씨") == normalise("-씨") == "-씨"
    assert normalise("well‑known") == normalise("well-known")
    assert normalise("−5") == normalise("-5")
    assert normalise("co\u00adoperate") == "cooperate", "a soft hyphen is invisible: it goes"
    assert normalise("コーヒー") != normalise("コ-ヒ-"), "U+30FC is a letter, not a dash"


def test_duplicates_are_found_across_the_tree(session, file, vocab1):
    store_datafile(session, vocab1, category_path="korean/book1/02-introduction")
    other = create_file(session, ensure_category(session, "korean/book2/01-again"))
    create_notes(session, other, [{"front": "나라", "back": "country"}])

    found = find_duplicates(session, [("나라", "country"), ("완전히새로운", "brand new")])
    assert set(found) == {0}
    assert len(found[0]) == 2  # the imported file and the one typed by hand
    assert all(match.same_back for match in found[0])
    assert {m.category_path for m in found[0]} == {"korean/book1/02-introduction", "korean/book2/01-again"}


def test_the_same_meaning_on_another_word_is_found_too(session, file):
    """What the import review needed: 그게 glossed "that" when 그것 already is.

    The reverse direction shows the gloss and asks for the word, so two words
    with one gloss is a question with two right answers.
    """
    create_notes(session, file, [{"front": "그것", "back": "that"}])
    [match] = find_duplicates(session, [("그게", "that")])[0]
    assert (match.front, match.by, match.same_back) == ("그것", "back", True)

    assert find_duplicates(session, [("그게", "that thing")]) == {}, "a different gloss is no clash"


def test_a_deliberate_alternative_does_not_keep_warning(session, file):
    """Once 뭐 takes 무엇 as an answer, the shared gloss is a decision, not a defect."""
    [note] = create_notes(session, file, [{"front": "뭐", "back": "what"}])
    assert find_duplicates(session, [("무엇", "what")])[0]
    update_note(session, note, {"accept": {"front": ["무엇"]}})
    assert find_duplicates(session, [("무엇", "what")]) == {}


def test_the_front_wins_when_both_sides_match(session, file):
    """An exact copy is reported once, as the same note — not twice."""
    create_notes(session, file, [{"front": "나라", "back": "country"}])
    [match] = find_duplicates(session, [("나라", "country")])[0]
    assert (match.by, match.same_back) == ("front", True)


def test_a_different_back_is_a_clash_not_a_copy(session, file):
    create_notes(session, file, [{"front": "나라", "back": "country"}])
    [match] = find_duplicates(session, [("  나라 ", "nation")])[0]
    assert match.same_back is False


def test_duplicates_can_be_narrowed_to_a_category(session, file):
    create_notes(session, file, [{"front": "나라", "back": "country"}])
    elsewhere = ensure_category(session, "korean/book2")
    assert find_duplicates(session, [("나라", "country")], category_id=elsewhere.id) == {}
    assert find_duplicates(session, [("나라", "country")], category_id=file.category_id)


def test_archived_notes_are_not_duplicates(session, file):
    [note] = create_notes(session, file, [{"front": "나라", "back": "country"}])
    archive_note(session, note)
    assert find_duplicates(session, [("나라", "country")]) == {}


# --- the category tree ------------------------------------------------------


def test_renaming_a_category_moves_the_whole_branch(session):
    ensure_category(session, "korean/book1/02-introduction")
    book = ensure_category(session, "korean/book1")
    rename_category(session, book, slug="Active Korean 1", label={"en": "Active Korean 1"})

    assert book.path == "korean/active-korean-1"
    child = ensure_category(session, "korean/active-korean-1/02-introduction")
    assert child.path == "korean/active-korean-1/02-introduction"
    assert book.label == {"en": "Active Korean 1"}


def test_moving_a_category_keeps_its_notes_practisable(session):
    source = ensure_category(session, "inbox/vocab")
    file = create_file(session, source)
    create_notes(session, file, [{"front": "나라", "back": "country"}])
    korean = ensure_category(session, "korean")

    move_category(session, source, korean.id)
    assert source.path == "korean/vocab"
    profile = get_or_create_profile(session)
    assert len(due_queue(session, profile, category_id=korean.id).cards) == 1


def test_a_category_cannot_be_moved_into_itself(session):
    parent = ensure_category(session, "korean")
    child = ensure_category(session, "korean/book1")
    with pytest.raises(ValueError, match="inside itself"):
        move_category(session, parent, child.id)


def test_a_name_that_is_taken_is_refused(session):
    ensure_category(session, "korean/book1")
    second = ensure_category(session, "korean/book2")
    with pytest.raises(ValueError, match="already called"):
        rename_category(session, second, slug="book1")


def test_only_an_empty_category_can_be_deleted(session, file):
    category = session.get(type(file.category), file.category_id)
    with pytest.raises(ValueError, match="data files"):
        delete_category(session, category)

    parent = session.get(type(category), category.parent_id)
    with pytest.raises(ValueError, match="sub-categories"):
        delete_category(session, parent)

    empty = ensure_category(session, "korean/book1/03-daily-life")
    delete_category(session, empty)
    assert session.get(type(empty), empty.id) is None
