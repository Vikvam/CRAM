"""Changing a batch of notes from a reviewed file (PLAN 6, phase 2).

The point of every test here is the same: a text fix to a collection that has
been practised must not cost a single card or a single answer.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memo.collection.categories import ensure_category
from memo.collection.editing import create_file, create_notes
from memo.collection.patch import Patch, apply_patch, load_patch
from memo.db.models import Card


@pytest.fixture
def file(session: Session):
    category = ensure_category(session, "korean/book1/02-introduction")
    return create_file(
        session, category, title="2-3", front_lang="ko", back_lang="en", default_type="bidirectional"
    )


@pytest.fixture
def notes(session, file):
    return create_notes(session, file, [{"front": "이게", "back": "this"}, {"front": "이건", "back": "this"}])


def _patch(*entries) -> Patch:
    return Patch.model_validate({"format": "memo.patch", "version": 1, "notes": list(entries)})


def _cards(session) -> int:
    return session.scalar(select(func.count()).select_from(Card)) or 0


def test_a_gloss_is_rewritten_and_no_card_moves(session, notes):
    before = _cards(session)
    keys = {card.key for note in notes for card in note.cards}

    patch = _patch(
        {
            "id": notes[0].id,
            "expect": {"front": "이게", "back": "this"},
            "set": {"back": "this + 이 (subject)", "accept": {"back": ["this"]}},
        }
    )
    report = apply_patch(session, patch, apply=True)

    assert notes[0].back == "this + 이 (subject)"
    assert notes[0].accept == {"back": ["this"]}
    assert report.notes == 1
    assert [c.key for c in report.changes] == ["back", "accept"]
    assert report.cards == before
    assert {card.key for note in notes for card in note.cards} == keys, "keyed on the id, not the text"


def test_a_dry_run_writes_nothing(session, notes):
    patch = _patch({"id": notes[0].id, "expect": {}, "set": {"back": "something else"}})
    report = apply_patch(session, patch)
    assert report.changes and report.notes == 1
    assert notes[0].back == "this", "read, not written"


def test_running_it_twice_is_not_a_conflict(session, notes):
    patch = _patch({"id": notes[0].id, "expect": {"back": "this"}, "set": {"back": "this + 이 (subject)"}})
    apply_patch(session, patch, apply=True)
    again = apply_patch(session, patch, apply=True)
    assert again.changes == []
    assert again.settled == [notes[0].id]


def test_a_note_that_is_not_there_refuses_the_whole_file(session, notes):
    patch = _patch(
        {"id": notes[0].id, "expect": {}, "set": {"back": "fine"}},
        {"id": "n_nope", "expect": {}, "set": {"back": "x"}},
    )
    with pytest.raises(ValueError, match="no such note"):
        apply_patch(session, patch, apply=True)
    assert notes[0].back == "this", "the good entry is not applied either"


def test_a_value_the_patch_did_not_expect_refuses_the_whole_file(session, notes):
    """What stops a file written weeks ago from quietly overwriting newer work."""
    patch = _patch({"id": notes[0].id, "expect": {"back": "that"}, "set": {"back": "this + 이 (subject)"}})
    with pytest.raises(ValueError, match="back is 'this', patch expected 'that'"):
        apply_patch(session, patch, apply=True)
    assert notes[0].back == "this"


def test_a_field_the_editor_does_not_own_is_refused(session, notes):
    patch = _patch({"id": notes[0].id, "expect": {}, "set": {"id": "n_forged"}})
    with pytest.raises(ValueError, match="cannot set id"):
        apply_patch(session, patch, apply=True)


def test_a_patch_that_would_cost_a_card_aborts(session, notes):
    """Text is safe; shape is not. A note losing a side loses a card and its schedule."""
    session.commit()  # the collection as it stood, so the rollback below means something
    before = _cards(session)
    assert before == 4, "two bidirectional notes"

    patch = _patch({"id": notes[0].id, "expect": {}, "set": {"type": "directional"}})
    with pytest.raises(RuntimeError, match="may not add or remove cards"):
        apply_patch(session, patch, apply=True)

    # The command's `session_scope` rolls back on the way out, and the card the
    # patch had already dropped comes back with it.
    session.rollback()
    assert _cards(session) == before


def test_the_file_must_say_what_it_is(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"notes": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="not a memo.patch file"):
        load_patch(path)

    path.write_text(json.dumps({"format": "memo.patch", "version": 99, "notes": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="newer than this build"):
        load_patch(path)


def test_the_shipped_patch_fits_a_collection_it_was_written_for(session, file):
    """The real file is checked in, so it is checked: ids and fields, not the data."""
    patch = load_patch(__import__("pathlib").Path("patches/2026-10-11-glosses.json"))
    assert patch.why and len(patch.notes) == 20
    for entry in patch.notes:
        assert entry.id.startswith("n_")
        assert set(entry.values) <= {"back", "accept", "note", "suspended"}
        assert entry.expect, "every entry says what it was written against"
