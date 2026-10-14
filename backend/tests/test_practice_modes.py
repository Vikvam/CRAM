"""Mode selection and distractors (PLAN 3.5, phase 3)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from memo.collection.categories import ensure_category
from memo.collection.editing import create_file, create_notes, update_file, update_note
from memo.collection.profiles import get_or_create_profile
from memo.db.models import CardState as CardStateRow
from memo.db.models import Note as NoteRow
from memo.models.datafile import NORMAL
from memo.overview.progress import KNOWN, LEARNING, MASTERED, NEW, standings
from memo.practice.modes import (
    Candidate,
    build_tiles,
    buildable,
    distractors_for,
    suggest_mode,
)
from memo.practice.priority import effective, push
from memo.practice.service import AnswerIn, due_queue, record_answer, resolve_scheduler_name

ALL = ["flip", "typed", "choice", "match", "build"]


def _candidate(
    answer: str, *, group: str | None = "countries", file: str = "df_1", note: str = "", prompt: str = ""
) -> Candidate:
    return Candidate(
        answer=answer,
        prompt=prompt or f"q_{answer}",
        direction="fwd",
        note_id=note or f"n_{answer}",
        group_id=group,
        data_file_id=file,
    )


# --- distractors ------------------------------------------------------------


def test_the_right_answer_is_never_offered_as_a_wrong_one():
    card = _candidate("Russia")
    pool = [card, _candidate("Korea"), _candidate("russia  ", note="n_dup"), _candidate("China")]
    assert set(distractors_for(card, pool)) == {"Korea", "China"}, "both are equally good"


def test_an_accepted_alternative_is_not_a_wrong_answer():
    """``what, which``: offering "which" as wrong would be teaching a lie."""
    card = _candidate("what")
    pool = [card, _candidate("which"), _candidate("Korea"), _candidate("China")]
    assert set(distractors_for(card, pool, excluded=["which"])) == {"Korea", "China"}


def test_candidates_of_the_same_script_and_length_come_first():
    card = _candidate("나라")
    pool = [
        card,
        _candidate("a very long english gloss indeed"),
        _candidate("한국"),
        _candidate("cat"),
        _candidate("중국"),
    ]
    assert set(distractors_for(card, pool, count=2)) == {"한국", "중국"}, "not the long gloss"


def test_auto_widens_from_the_group_to_the_file_to_the_subtree():
    card = _candidate("Russia", group="countries", file="df_1")
    pool = [
        card,
        _candidate("Korea", group="countries", file="df_1"),
        _candidate("doctor", group="jobs", file="df_1"),
        _candidate("Monday", group=None, file="df_2"),
    ]
    assert distractors_for(card, pool, scope="auto", count=3) == ["Korea", "doctor", "Monday"]


def test_a_fixed_scope_is_a_fence_not_a_preference():
    card = _candidate("Russia", group="countries", file="df_1")
    pool = [
        card,
        _candidate("Korea", group="countries", file="df_1"),
        _candidate("doctor", group="jobs", file="df_1"),
    ]
    assert distractors_for(card, pool, scope="group", count=3) == ["Korea"], "no widening"
    assert set(distractors_for(card, pool, scope="file", count=3)) == {"Korea", "doctor"}


def test_the_other_direction_is_never_a_distractor():
    """``Russia`` must not be offered among Korean words."""
    card = _candidate("나라")
    reverse = Candidate(
        answer="country",
        prompt="나라",
        direction="rev",
        note_id="n_2",
        group_id="countries",
        data_file_id="df_1",
    )
    assert distractors_for(card, [card, reverse]) == []


def test_a_word_that_answers_the_same_question_is_not_a_wrong_answer():
    """Two notes glossed "that": offering one as a distractor for the other makes
    a four-option question with two right answers, one of them marked wrong."""
    card = _candidate("그것", prompt="that")
    sibling = _candidate("그게", prompt="that")
    other = _candidate("이것", prompt="this")
    assert distractors_for(card, [card, sibling, other], count=3) == ["이것"]


# --- which mode a card asks for --------------------------------------------


@pytest.mark.parametrize(
    ("interval", "expected"),
    [(None, "choice"), (0.0, "choice"), (0.5, "choice"), (1.0, "typed"), (6.9, "typed"), (7.0, "build")],
)
def test_the_cards_own_state_picks_the_mode(interval, expected):
    assert suggest_mode(interval_days=interval, answer="나라", allowed=ALL, has_distractors=True) == expected


def test_a_long_answer_is_typed_rather_than_built():
    long = "저는 한국에서 공부하는 학생이에요 그리고 또 무엇인가"
    assert suggest_mode(interval_days=30, answer=long, allowed=ALL, has_distractors=True) == "typed"


def test_without_enough_distractors_a_new_card_is_typed():
    assert suggest_mode(interval_days=None, answer="나라", allowed=ALL, has_distractors=False) == "typed"


def test_a_mode_the_category_turned_off_is_never_suggested():
    allowed = ["flip", "typed"]
    assert suggest_mode(interval_days=None, answer="나라", allowed=allowed, has_distractors=True) == "typed"
    assert suggest_mode(interval_days=99, answer="나라", allowed=["flip"], has_distractors=True) == "flip"
    assert suggest_mode(interval_days=99, answer="나라", allowed=[], has_distractors=True) == "flip"


def test_turning_adaptive_off_leaves_the_first_allowed_mode():
    assert (
        suggest_mode(
            interval_days=None, answer="나라", allowed=["typed", "flip"], has_distractors=True, adaptive=False
        )
        == "typed"
    )


def test_tiles_are_words_or_else_graphemes():
    assert build_tiles("저는 첸이에요") == (2, "words")
    assert build_tiles("나라") == (2, "graphemes")
    assert build_tiles("Russia") == (6, "graphemes")
    assert not buildable("가")  # one tile is not a puzzle
    assert not buildable("a" * 20)  # twenty is a chore
    assert buildable("나라")


# --- through the queue ------------------------------------------------------


@pytest.fixture
def file(session: Session):
    category = ensure_category(session, "korean/book1/02-introduction")
    return create_file(
        session, category, title="2-1", front_lang="ko", back_lang="en", default_type="bidirectional"
    )


def test_every_queued_card_arrives_with_options_and_a_mode(session, file):
    create_notes(
        session,
        file,
        [
            {"front": "나라", "back": "country", "group": "countries"},
            {"front": "한국", "back": "Korea", "group": "countries"},
            {"front": "중국", "back": "China", "group": "countries"},
            {"front": "일본", "back": "Japan", "group": "countries"},
        ],
    )
    cards = due_queue(session, get_or_create_profile(session), rng=random.Random(4)).cards

    for card in cards:
        assert len(card.distractors) == 3, card.prompt
        assert card.answer not in card.distractors
        assert len(set(card.distractors)) == 3
        assert card.suggest == "choice", "they are all new"


def test_the_session_can_narrow_where_distractors_come_from(session, file):
    create_notes(
        session,
        file,
        [
            {"front": "나라", "back": "country", "group": "countries"},
            {"front": "한국", "back": "Korea", "group": "countries"},
            {"front": "의사", "back": "doctor", "group": "jobs"},
            {"front": "교사", "back": "teacher", "group": "jobs"},
        ],
    )
    profile = get_or_create_profile(session)

    wide = due_queue(session, profile, rng=random.Random(1)).cards
    narrow = due_queue(session, profile, distractor_scope="group", rng=random.Random(1)).cards

    assert max(len(c.distractors) for c in wide) == 3
    assert all(len(c.distractors) == 1 for c in narrow), "one other note per group"


def test_a_card_with_too_few_neighbours_is_typed_not_asked_to_choose(session, file):
    create_notes(session, file, [{"front": "나라", "back": "country"}])
    cards = due_queue(session, get_or_create_profile(session)).cards
    assert [c.suggest for c in cards] == ["typed", "typed"]


def test_a_notes_own_mode_list_still_wins(session, file):
    """``modes`` on the note is the narrowest fence (PLAN 3.2)."""
    create_notes(
        session,
        file,
        [
            {"front": "나라", "back": "country", "modes": ["flip"]},
            {"front": "한국", "back": "Korea"},
            {"front": "중국", "back": "China"},
            {"front": "일본", "back": "Japan"},
        ],
    )
    cards = due_queue(session, get_or_create_profile(session)).cards
    by_prompt = {c.prompt: c.suggest for c in cards}
    assert by_prompt["나라"] == "flip"
    assert by_prompt["한국"] == "choice"


def test_a_category_that_only_allows_typing_gets_typing(session, file):
    create_notes(
        session,
        file,
        [
            {"front": "나라", "back": "country"},
            {"front": "한국", "back": "Korea"},
            {"front": "중국", "back": "China"},
            {"front": "일본", "back": "Japan"},
        ],
    )
    category = file.category
    category.config = {"practice": {"modes": ["typed", "flip"]}}
    session.flush()

    cards = due_queue(session, get_or_create_profile(session), category_id=category.id).cards
    assert {c.suggest for c in cards} == {"typed"}


def test_the_file_default_type_does_not_change_which_modes_are_offered(session, file):
    """A sanity check that card type (data) and mode (interaction) stay orthogonal."""
    create_notes(
        session,
        file,
        [
            {"front": "나라", "back": "country"},
            {"front": "한국", "back": "Korea"},
            {"front": "중국", "back": "China"},
            {"front": "일본", "back": "Japan"},
        ],
    )
    update_file(session, file, {"default_type": "directional"})
    cards = due_queue(session, get_or_create_profile(session)).cards
    assert len(cards) == 4
    assert {c.suggest for c in cards} == {"choice"}


def test_a_session_works_through_one_lesson_before_the_next(session):
    """Imported files used to land at position 0, so six lessons interleaved."""
    category = ensure_category(session, "korean/book1")
    from memo.collection.store import store_datafile
    from memo.models.datafile import DataFile, Note

    for lesson in ("2-1", "2-2"):
        store_datafile(
            session,
            DataFile(
                title=lesson,
                notes=[Note(front=f"{lesson}-{i}", back=f"b{i}") for i in range(4)],
            ),
            category_path=category.path,
        )

    # One card per note here: these notes have no type, so they are front → back.
    cards = due_queue(session, get_or_create_profile(session), new_limit=4, rng=random.Random(7)).cards
    lessons = [c.prompt.split("-")[0] + "-" + c.prompt.split("-")[1] for c in cards]
    assert set(lessons) == {"2-1"}, "the first lesson fills the session before the second"


# --- a scope you chose is never a dead end ----------------------------------
#
# "I want to be able to practise any file I want." A file whose cards are all
# scheduled for later used to answer "nothing to practise right now", which is
# the app telling the user to come back tomorrow (PLAN 3.5).


def _file_of(session: Session, titles: list[str], *, path: str = "korean") -> tuple[str, list[str]]:
    category = ensure_category(session, path)
    file = create_file(session, category, title="lesson", default_type="directional")
    notes = create_notes(session, file, [{"front": t, "back": f"{t}-back"} for t in titles])
    return file.id, [f"{n.id}:fwd" for n in notes]


def _answer_all(session: Session, keys: list[str], *, outcome: str = "correct", at=None) -> None:
    profile = get_or_create_profile(session)
    name = resolve_scheduler_name(session, profile, None, None)
    for key in keys:
        record_answer(
            session,
            profile,
            AnswerIn(card_key=key, mode="typed", outcome=outcome, at=at),
            scheduler=name,
        )
    session.flush()


def test_a_file_with_everything_scheduled_is_still_practisable(session):
    file_id, keys = _file_of(session, ["하나", "둘", "셋"])
    _answer_all(session, keys)

    found = due_queue(session, get_or_create_profile(session), file_id=file_id)
    assert [c.key for c in found.cards] != [], "the file I asked for is never a dead end"
    assert all(c.early for c in found.cards), "and it says so: these are brought forward"
    assert (found.due_count, found.new_count) == (0, 0)
    assert found.later_count == found.ahead_count == len(keys)
    assert found.next_due is not None and found.total == len(keys)


def test_nothing_is_brought_forward_when_it_is_not_wanted(session):
    file_id, keys = _file_of(session, ["하나", "둘"])
    _answer_all(session, keys)

    found = due_queue(session, get_or_create_profile(session), file_id=file_id, ahead=False)
    assert found.cards == []
    assert found.total == 2, "caught up is not the same as empty, and the counts say which"


def test_an_empty_scope_is_the_one_real_dead_end(session):
    file_id, _ = _file_of(session, [])

    found = due_queue(session, get_or_create_profile(session), file_id=file_id)
    assert found.cards == [] and found.total == 0


def test_a_short_session_is_topped_up_from_what_is_coming(session):
    file_id, keys = _file_of(session, [f"w{i}" for i in range(30)])
    _answer_all(session, keys[:28])  # the rest are still new

    found = due_queue(session, get_or_create_profile(session), file_id=file_id, ahead_to=10)
    assert found.new_count == 2
    assert len(found.cards) == 10, "two new ones, and eight brought forward to fill the session"
    assert found.ahead_count == 8


def test_new_cards_are_not_capped_unless_a_cap_is_asked_for(session):
    file_id, keys = _file_of(session, [f"w{i}" for i in range(42)])

    profile = get_or_create_profile(session)
    assert len(due_queue(session, profile, file_id=file_id).cards) == 42, "my pace is my own"
    assert len(due_queue(session, profile, file_id=file_id, new_limit=5).cards) == 5


# --- a word can be marked for how often it comes up -------------------------
#
# "Test items with high probability to appear." The mark is half of it; how well
# the card is already known is what damps it (PLAN 3.2, 3.5).

BUCKETS_WEAKEST_FIRST = (NEW, LEARNING, KNOWN, MASTERED)


def _mark(session: Session, keys: list[str], level: str) -> None:
    """Mark the words those cards belong to, the way the editor does."""
    for key in keys:
        note = session.get(NoteRow, key.split(":")[0])
        assert note is not None
        update_note(session, note, {"priority": level})
    session.flush()


def _overdue(session: Session, keys: list[str]) -> None:
    """Spread the cards over a backlog, the one marked last of all least overdue."""
    profile = get_or_create_profile(session)
    name = resolve_scheduler_name(session, profile, None, None)
    now = datetime.now(UTC)
    for days, key in enumerate(reversed(keys), start=1):
        state = session.scalars(
            select(CardStateRow).where(
                CardStateRow.profile_id == profile.id,
                CardStateRow.card_key == key,
                CardStateRow.scheduler == name,
            )
        ).one()
        state.due = now - timedelta(days=days)
    session.flush()


def test_what_a_mark_is_worth_is_damped_by_knowing_the_word():
    assert [push("high", b) for b in BUCKETS_WEAKEST_FIRST] == [2, 2, 1, 0], (
        "the second ask goes at known, the rest at mastered"
    )
    assert [push("crucial", b) for b in BUCKETS_WEAKEST_FIRST] == [3, 3, 2, 1], (
        "crucial damps a step later than high, and never all the way"
    )
    assert [push("low", b) for b in BUCKETS_WEAKEST_FIRST] == [-1] * 4, (
        "low says something about me, not about the word, so knowing it changes nothing"
    )
    assert [push(None, b) for b in BUCKETS_WEAKEST_FIRST] == [0] * 4
    assert effective("high", MASTERED) == NORMAL, (
        "a badge claiming a push the card has lost would be describing the setting, not the session"
    )
    assert effective("crucial", MASTERED) == "crucial"


def test_a_marked_word_goes_ahead_of_a_backlog(session):
    file_id, keys = _file_of(session, [f"w{i}" for i in range(6)])
    _answer_all(session, keys)
    _overdue(session, keys)
    _mark(session, keys[-1:], "high")

    found = due_queue(session, get_or_create_profile(session), file_id=file_id, rng=random.Random(3))
    asked = found.cards[0]
    assert asked.key == keys[-1], "first is not much of a promise if it only means first of today"
    assert (asked.priority, asked.twice) == ("high", True)
    assert [c.priority for c in found.cards[1:]] == ["normal"] * 5


def test_a_crucial_word_goes_ahead_of_a_high_one(session):
    file_id, keys = _file_of(session, [f"w{i}" for i in range(6)])
    _answer_all(session, keys)
    _overdue(session, keys)
    _mark(session, keys[:3], "high")
    _mark(session, keys[-1:], "crucial")

    found = due_queue(session, get_or_create_profile(session), file_id=file_id, rng=random.Random(3))
    asked = found.cards[0]
    assert asked.key == keys[-1]
    assert (asked.priority, asked.twice) == ("crucial", True)
    assert [c.priority for c in found.cards[1:4]] == ["high"] * 3


def test_a_cap_is_spent_on_the_words_that_were_asked_for(session):
    file_id, keys = _file_of(session, [f"w{i}" for i in range(20)])
    _mark(session, keys[15:], "high")

    found = due_queue(
        session, get_or_create_profile(session), file_id=file_id, new_limit=5, rng=random.Random(1)
    )
    assert {c.key for c in found.cards} == set(keys[15:]), "page order would have taken the first five"


def test_a_low_word_is_asked_last(session):
    file_id, keys = _file_of(session, [f"w{i}" for i in range(8)])
    _mark(session, keys[:1], "low")

    found = due_queue(session, get_or_create_profile(session), file_id=file_id, rng=random.Random(5))
    assert found.cards[-1].key == keys[0]
    assert found.cards[-1].priority == "low"


def test_a_mark_fades_as_the_word_is_learned_and_comes_back_when_it_slips(session):
    """The whole point of damping, and the half of it that is hardest to believe.

    Nothing is stored and nothing expires: the bucket is re-read from the log
    every time, so the push leaves when the word is mastered and returns the
    moment the accuracy window says it is going wrong again.
    """
    file_id, keys = _file_of(session, ["하나", "둘", "셋"])
    marked = keys[:1]
    _mark(session, marked, "high")
    profile = get_or_create_profile(session)

    def asked():
        found = due_queue(session, profile, file_id=file_id, rng=random.Random(2))
        return next(c for c in found.cards if c.key == marked[0])

    assert (asked().priority, asked().twice) == ("high", True)

    # Four typed answers, nine hours apart: enough points, and spread over more
    # than one sitting, which is what mastery now asks for.
    start = datetime.now(UTC) - timedelta(days=2)
    for step in range(4):
        _answer_all(session, marked, at=start + step * timedelta(hours=9))
    assert standings(session, profile)[marked[0]] == MASTERED
    assert (asked().priority, asked().twice) == ("normal", False), "it stopped crowding the session"

    _answer_all(session, marked, outcome="wrong")
    _answer_all(session, marked, outcome="wrong")
    assert standings(session, profile)[marked[0]] == LEARNING, "4 of 6 is 67%"
    assert (asked().priority, asked().twice) == ("high", True), "and the mark is back, unasked"


# --- how much is one sitting ------------------------------------------------
#
# "Sometimes I wish to just press Practice but I do not want to do all 190 cards
# that are... I guess due?" Without a size a Start means the whole pile, which on
# a real collection is an hour nobody asked for (PLAN 3.5).


def _due_and_new(session: Session, *, due: int, new: int) -> None:
    """``due`` cards answered three days ago, and ``new`` never seen at all."""
    category = ensure_category(session, "korean")
    old = create_file(session, category, title="done", default_type="directional")
    notes = create_notes(session, old, [{"front": f"o{i}", "back": f"ob{i}"} for i in range(due)])
    _answer_all(session, [f"{n.id}:fwd" for n in notes], at=datetime.now(UTC) - timedelta(days=3))
    fresh = create_file(session, category, title="fresh", default_type="directional")
    create_notes(session, fresh, [{"front": f"n{i}", "back": f"nb{i}"} for i in range(new)])


def test_a_size_caps_the_whole_sitting_and_not_only_the_new_cards(session):
    _due_and_new(session, due=30, new=0)
    profile = get_or_create_profile(session)

    assert len(due_queue(session, profile).cards) == 30, "all of them, as it always was"
    found = due_queue(session, profile, limit=8)
    assert len(found.cards) == 8
    assert found.due_count == 30, "and the count still says what is waiting"


def test_a_capped_sitting_keeps_a_share_for_new_cards(session):
    """Otherwise a backlog owns every sitting and the lesson it came from never
    moves on — which is how the backlog got that big."""
    _due_and_new(session, due=30, new=30)

    found = due_queue(session, get_or_create_profile(session), limit=20)
    assert len(found.cards) == 20
    assert sum(c.is_new for c in found.cards) == 5, "a quarter of twenty"


def test_the_new_cards_fill_the_room_the_due_ones_left(session):
    _due_and_new(session, due=2, new=30)

    cards = due_queue(session, get_or_create_profile(session), limit=12).cards
    assert (sum(not c.is_new for c in cards), sum(c.is_new for c in cards)) == (2, 10)


def test_and_the_due_cards_fill_the_room_the_new_ones_left(session):
    _due_and_new(session, due=30, new=1)

    cards = due_queue(session, get_or_create_profile(session), limit=12).cards
    assert (sum(not c.is_new for c in cards), sum(c.is_new for c in cards)) == (11, 1)


def test_a_new_card_ceiling_still_holds_inside_the_share(session):
    _due_and_new(session, due=30, new=30)

    found = due_queue(session, get_or_create_profile(session), limit=20, new_limit=2)
    assert sum(c.is_new for c in found.cards) == 2
    assert len(found.cards) == 20, "and the due cards take the room it gave up"


def test_without_a_size_a_sitting_is_everything_there_is(session):
    _due_and_new(session, due=30, new=30)

    assert len(due_queue(session, get_or_create_profile(session)).cards) == 60


def test_bringing_cards_forward_never_fills_past_the_size(session):
    """`ahead` is there to rescue a scope with nothing due, not to overrule how
    much was asked for."""
    file_id, keys = _file_of(session, [f"w{i}" for i in range(30)])
    _answer_all(session, keys)  # every one of them scheduled for later

    found = due_queue(session, get_or_create_profile(session), file_id=file_id, limit=5)
    assert len(found.cards) == 5 and found.ahead_count == 5
    assert all(c.early for c in found.cards)
