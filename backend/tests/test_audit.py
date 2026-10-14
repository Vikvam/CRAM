"""Looking the collection over for what an import leaves behind (PLAN 6, phase 2)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from memo.collection.audit import audit, bare
from memo.collection.categories import ensure_category
from memo.collection.editing import create_file, create_notes, update_note


@pytest.fixture
def file(session: Session):
    category = ensure_category(session, "korean/book1/02-introduction")
    return create_file(session, category, title="2-2", front_lang="ko", back_lang="en")


def test_bare_drops_only_a_trailing_aside():
    assert bare("that (over there)") == "that"
    assert bare("0 (zero)") == "0"
    assert bare("I/me (honorific)") == "i/me"
    assert bare("f(x) = 2x") == "f(x) = 2x", "a bracket in the middle is part of the answer"
    assert bare(None) == ""


def test_two_words_with_one_gloss_are_a_collision(session, file):
    """The reported bug: asked "that", there is no way to know which one is wanted."""
    create_notes(
        session,
        file,
        [
            {"front": "그것", "back": "that"},
            {"front": "그게", "back": "that"},
            {"front": "이것", "back": "this"},
        ],
    )
    [finding] = audit(session).collisions
    assert finding.key == "that"
    assert [n.front for n in finding.notes] == ["그것", "그게"]
    assert audit(session).clean is False


def test_a_collision_that_accepts_itself_is_not_a_finding(session, file):
    """Two words for one thing is fine once either answer is taken for the other."""
    both = create_notes(session, file, [{"front": "뭐", "back": "what"}, {"front": "무엇", "back": "what"}])
    update_note(session, both[0], {"accept": {"front": ["무엇"]}})
    assert audit(session).collisions, "one-sided is still a collision"
    assert [(a.front, b.front) for a, b in audit(session).one_sided] == [("뭐", "무엇")]

    update_note(session, both[1], {"accept": {"front": ["뭐"]}})
    report = audit(session)
    assert report.collisions == ()
    assert report.one_sided == ()
    assert [f.key for f in report.resolved] == ["what"]
    assert report.clean is True


def test_the_same_note_twice_is_a_duplicate_not_a_collision(session, file):
    """Both copies answer the same; what they split is the history, not the question."""
    create_notes(session, file, [{"front": "학교", "back": "school"}, {"front": "학교", "back": "school"}])
    report = audit(session)
    assert report.collisions == (), "one word, so nothing is ambiguous"
    assert [f.key.split("\x00") for f in report.duplicates] == [["학교", "school"]]


def test_a_suspended_note_cannot_be_ambiguous(session, file):
    """Practice never asks it, so it is not in the question space."""
    notes = create_notes(session, file, [{"front": "누구", "back": "who"}, {"front": "누가", "back": "who"}])
    assert audit(session).collisions
    update_note(session, notes[1], {"suspended": True})
    assert audit(session).clean


def test_a_gloss_that_differs_only_inside_a_bracket_is_a_hint(session, file):
    create_notes(
        session,
        file,
        [{"front": "그것", "back": "that"}, {"front": "저것", "back": "that (over there)"}],
    )
    report = audit(session)
    assert report.collisions == (), "the two prompts are different, so they are answerable"
    assert [f.key for f in report.near] == ["that"]
    assert report.clean is True, "a hint is not a finding"
