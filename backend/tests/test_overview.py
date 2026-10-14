"""Reading what the log says (PLAN 6, phase 4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from memo.collection.categories import ensure_category
from memo.collection.editing import archive_note, create_file, create_notes, update_note
from memo.collection.profiles import get_or_create_profile
from memo.db.models import CardState as CardStateRow
from memo.overview import (
    KNOWN,
    LEARNING,
    MASTERED,
    NEW,
    SET_ASIDE,
    activity,
    file_mastery,
    group_mastery,
    mastery,
    note_buckets,
    pace,
    standing,
    standing_since,
    weak_cards,
    weakest,
    words,
)
from memo.overview.progress import _count
from memo.practice.service import AnswerIn, record_answer
from memo.scheduling.registry import DEFAULT_SCHEDULER

NOW = datetime(2026, 10, 8, 3, 0, tzinfo=UTC)  # noon in Seoul
SEOUL = 9 * 60


@pytest.fixture
def lesson(session: Session):
    category = ensure_category(session, "korean/book1/02-introduction")
    file = create_file(
        session, category, title="2-1", front_lang="ko", back_lang="en", default_type="bidirectional"
    )
    notes = create_notes(
        session,
        file,
        [
            {"front": "나라", "back": "country", "group": "countries"},
            {"front": "한국", "back": "Korea", "group": "countries"},
            {"front": "의사", "back": "doctor", "group": "jobs"},
        ],
    )
    return file, notes


@pytest.fixture
def profile(session: Session):
    return get_or_create_profile(session)


def answer(session, profile, note, direction="fwd", *, outcome="correct", at=NOW, mode="typed", ms=None):
    return record_answer(
        session,
        profile,
        AnswerIn(card_key=f"{note.id}:{direction}", mode=mode, outcome=outcome, at=at, duration_ms=ms),
        scheduler=DEFAULT_SCHEDULER,
    )


# --- buckets ----------------------------------------------------------------

#: Grades, by their names on the four buttons.
AGAIN, HARD, GOOD = 1, 2, 3
#: Close enough together to be one sitting.
FIVE = timedelta(minutes=5)


def log(mode, direction, times, grade=GOOD, *, apart=timedelta(days=1), start=NOW):
    """``times`` review rows of one shape, oldest first.

    Spaced a day apart, because the mastery rule reads the timestamps too and
    these tests are about the ladder rather than about cramming: the ones that
    are about cramming pass their own ``apart``.
    """
    return [(mode, direction, grade, start + apart * i) for i in range(times)]


def then(rows, mode, direction, grade=GOOD, *, apart=timedelta(days=1)):
    """One more review on top of ``rows``, a day after the last of them."""
    return [*rows, (mode, direction, grade, rows[-1][3] + apart)]


def test_a_card_nobody_has_answered_is_new():
    assert standing([]) == NEW
    assert standing(log("choice", "rev", 1)) == LEARNING, "answered once is not new any more"


def test_a_rate_needs_enough_reviews_to_be_a_measurement():
    """Three out of three is not 100%, it is three."""
    assert standing(log("choice", "rev", 3)) == LEARNING, "6 points already, but too few reviews"
    assert standing(log("choice", "rev", 4)) == KNOWN


def test_picking_the_word_counts_for_twice_what_picking_its_meaning_does():
    """Laufer & Goldstein's ladder: active recognition over passive."""
    assert standing(log("choice", "fwd", 4)) == LEARNING, "4 points, and known wants 6"
    assert standing(log("choice", "rev", 4)) == KNOWN


def test_recognising_a_word_is_never_writing_it():
    """Twenty points of multiple choice, and still not mastered."""
    assert standing(log("choice", "rev", 10)) == KNOWN


def test_one_written_answer_is_what_tips_a_known_card_over():
    recognised = log("choice", "rev", 4)
    assert standing(recognised) == KNOWN
    assert standing(then(recognised, "typed", "rev")) == MASTERED


def test_writing_the_meaning_is_writing_too_but_carries_less_of_the_load():
    """It is the only typing a ko→en card can be asked for, so it has to count."""
    assert standing(then(log("choice", "fwd", 6), "typed", "fwd")) == KNOWN, "9 points"
    assert standing(then(log("choice", "fwd", 7), "typed", "fwd")) == MASTERED


def test_pieces_handed_to_you_are_not_writing():
    """`build` is production with the answer already cut up, so it only ever counts
    towards the total — ten points of it is known, and nothing more."""
    assert standing(log("build", "rev", 4)) == KNOWN, "12 points, none of it typed"


def test_an_almost_is_neither_credited_nor_held_against():
    slips = log("typed", "rev", 3, HARD)
    assert standing([*log("choice", "rev", 4), *slips]) == KNOWN, "the slips changed nothing"
    assert standing([*log("choice", "rev", 3), *slips]) == LEARNING, (
        "and they do not fill the floor of four real reviews either"
    )


def test_a_word_you_have_started_missing_drops_back_however_much_it_earned():
    mastered = then(log("choice", "rev", 4), "typed", "rev")
    assert standing(mastered) == MASTERED
    assert standing([*mastered, *log("choice", "rev", 2, AGAIN)]) == LEARNING, "5 of 7 is 71%"


def test_only_the_last_eight_reviews_decide():
    """Fumbling a word while it was new must not block it for good."""
    bad_start = log("choice", "rev", 4, AGAIN)
    assert standing([*bad_start, *log("choice", "rev", 8)]) == KNOWN


def test_a_word_cannot_be_mastered_in_one_sitting():
    """Everything else here can be cleared in an hour; mastery cannot.

    Ten points and a written answer are reachable in one evening on one lesson,
    and a word you can still produce an hour later is not a word you have kept.
    """
    crammed = then(log("choice", "rev", 4, apart=timedelta(minutes=5)), "typed", "rev", apart=FIVE)
    assert standing(crammed) == KNOWN, "every point it needs, all of it inside half an hour"
    spread = then(log("choice", "rev", 4, apart=FIVE), "typed", "rev", apart=timedelta(hours=9))
    assert standing(spread) == MASTERED, "the same answers, with a night in between"


def test_the_spread_is_measured_over_the_answers_that_earned_something():
    """An "almost" eight hours ago is not evidence of anything being kept."""
    slips = log("typed", "rev", 2, HARD, apart=FIVE)
    late = then(
        log("choice", "rev", 4, apart=FIVE, start=NOW + timedelta(hours=9)), "typed", "rev", apart=FIVE
    )
    assert standing([*slips, *late]) == KNOWN


def test_a_note_is_only_as_known_as_its_weaker_direction():
    assert weakest([MASTERED, NEW]) == NEW
    assert weakest([MASTERED, KNOWN]) == KNOWN
    assert weakest([KNOWN, LEARNING]) == LEARNING
    assert weakest([]) == NEW, "a note without cards has nothing known about it"


# --- mastery ----------------------------------------------------------------


def test_a_note_counts_for_every_category_above_it(session, profile, lesson):
    """A subject's row is the subject, not the files loose at its top."""
    rows = {row.path: row for row in mastery(session, profile)}

    assert set(rows) == {"korean", "korean/book1", "korean/book1/02-introduction"}
    for path, row in rows.items():
        assert (row.notes, row.new) == (3, 3), f"{path}: three notes, each counted once"
    assert rows["korean"].depth == 0
    assert rows["korean/book1/02-introduction"].depth == 2


def test_a_note_leaves_new_once_both_directions_have_been_asked(session, profile, lesson):
    """A word asked both ways is one word, and it stands where its weaker side does."""
    _, notes = lesson
    answer(session, profile, notes[0])

    row = next(r for r in mastery(session, profile) if r.path == "korean")
    assert (row.new, row.learning) == (3, 0), "the reverse has never been asked"

    answer(session, profile, notes[0], "rev")
    row = next(r for r in mastery(session, profile) if r.path == "korean")
    assert (row.new, row.learning, row.known) == (2, 1, 0)


def test_mastery_leaves_out_what_is_not_being_learnt(session, profile, lesson):
    """Archived and suspended notes are in the collection, not in the learning."""
    _, notes = lesson
    archive_note(session, notes[0], archived=True)
    update_note(session, notes[1], {"suspended": True})

    row = next(r for r in mastery(session, profile) if r.path == "korean")
    assert row.notes == 1, "one note left"


def test_what_you_know_does_not_depend_on_which_scheduler_ran(session, profile, lesson):
    """The bars read the log, not the intervals, so switching algorithm keeps them."""
    _, notes = lesson
    record_answer(
        session,
        profile,
        AnswerIn(card_key=f"{notes[0].id}:fwd", mode="typed", outcome="correct", at=NOW),
        scheduler="sm2",
    )
    answer(session, profile, notes[0], "rev")

    row = next(r for r in mastery(session, profile) if r.path == "korean")
    assert (row.new, row.learning) == (2, 1), "the answer counts whoever scheduled it"


def test_every_lesson_gets_its_own_bars(session, profile, lesson):
    """One category and six lessons is one useful bar and six — so both are sent."""
    file, notes = lesson
    second = create_file(session, file.category, title="2-2", default_type="bidirectional")
    create_notes(session, second, [{"front": "책", "back": "book"}])
    create_file(session, file.category, title="empty")
    answer(session, profile, notes[0])
    answer(session, profile, notes[0], "rev")

    rows = file_mastery(session, profile)
    assert [(r.title, r.notes, r.learning) for r in rows] == [("2-1", 3, 1), ("2-2", 1, 0)], (
        "a file with nothing in it is not a lesson yet"
    )
    assert rows[0].category_id == file.category_id


def test_a_known_low_word_counts_as_done_while_anything_else_is_not_mastered():
    assert _count([(KNOWN, True), (KNOWN, False)]) == (
        {NEW: 0, LEARNING: 0, KNOWN: 1, MASTERED: 1},
        1,
    )
    assert _count([(KNOWN, True), (MASTERED, False)]) == (
        {NEW: 0, LEARNING: 0, KNOWN: 1, MASTERED: 1},
        0,
    ), "once nothing else is left, a low word has to be mastered like the rest"
    assert _count([(LEARNING, True), (NEW, False)])[1] == 0, "known is the floor, not anything at all"
    assert _count([(KNOWN, True)])[1] == 0, "nothing else to wait for"


def test_the_bars_judge_each_scope_on_its_own(session, profile, lesson, monkeypatch):
    """A file is judged on the file, a category on everything under it."""
    file, notes = lesson
    second = create_file(session, file.category, title="2-2", default_type="bidirectional")
    (book,) = create_notes(session, second, [{"front": "책", "back": "book"}])
    update_note(session, notes[0], {"priority": "low"})
    buckets = {f"{notes[0].id}:{d}": KNOWN for d in ("fwd", "rev")}
    buckets |= {f"{n.id}:{d}": MASTERED for n in notes[1:] for d in ("fwd", "rev")}
    monkeypatch.setattr("memo.overview.progress.standings", lambda *_: buckets)

    lesson_row, book_row = file_mastery(session, profile)
    assert (lesson_row.known, lesson_row.mastered, lesson_row.settled) == (1, 2, 0), (
        "everything else in 2-1 is mastered, so its low word has to be too"
    )
    assert book_row.settled == 0
    korean = next(r for r in mastery(session, profile) if r.path == "korean")
    assert (korean.known, korean.mastered, korean.settled) == (0, 3, 1), (
        "the category still has 책 to learn, so the low word counts as done there"
    )


def test_each_heading_gets_its_own_bars(session, profile, lesson):
    file, notes = lesson
    (loose,) = create_notes(session, file, [{"front": "네", "back": "yes"}])
    answer(session, profile, notes[2])
    answer(session, profile, notes[2], "rev")

    rows = group_mastery(session, profile, file.id)
    assert [(r.key, r.notes, r.new, r.learning) for r in rows] == [
        (None, 1, 1, 0),
        ("countries", 2, 2, 0),
        ("jobs", 1, 0, 1),
    ], "notes under no heading first, then the lesson's own order"


# --- the sheet's markers ----------------------------------------------------


def test_the_sheet_marks_the_weaker_direction_of_each_note(session, profile, lesson):
    _, notes = lesson
    answer(session, profile, notes[0], "fwd")

    marks = note_buckets(session, profile, [n.id for n in notes])
    assert marks[notes[0].id] == NEW, "the reverse card has still never been asked"

    answer(session, profile, notes[0], "rev")
    marks = note_buckets(session, profile, [n.id for n in notes])
    assert marks[notes[0].id] == LEARNING
    assert marks[notes[1].id] == NEW


def test_a_suspended_note_still_has_a_marker(session, profile, lesson):
    """Unlike the bars: a sheet shows the lesson as it is written."""
    _, notes = lesson
    update_note(session, notes[0], {"suspended": True})
    answer(session, profile, notes[0], "fwd")
    answer(session, profile, notes[0], "rev")

    marks = note_buckets(session, profile, [n.id for n in notes])
    assert marks[notes[0].id] == LEARNING


def test_asking_for_no_notes_asks_the_database_nothing(session, profile):
    assert note_buckets(session, profile, []) == {}


# --- the weak list ----------------------------------------------------------


def test_a_card_you_have_never_missed_is_not_on_the_list(session, profile, lesson):
    _, notes = lesson
    answer(session, profile, notes[0])
    assert weak_cards(session, profile, DEFAULT_SCHEDULER, now=NOW) == []


def test_the_card_missed_most_often_comes_first(session, profile, lesson):
    _, notes = lesson
    answer(session, profile, notes[0], outcome="wrong", at=NOW - timedelta(days=2))
    answer(session, profile, notes[1], outcome="wrong", at=NOW - timedelta(days=5))
    answer(session, profile, notes[1], outcome="wrong", at=NOW - timedelta(days=1))

    weak = weak_cards(session, profile, DEFAULT_SCHEDULER, now=NOW)
    assert [w.prompt for w in weak] == ["한국", "나라"]
    assert (weak[0].wrong, weak[0].answers) == (2, 2)
    assert weak[0].last_wrong == NOW - timedelta(days=1)


def test_an_old_lapse_does_not_keep_a_card_on_the_list(session, profile, lesson):
    """The list is for what is going wrong now, and nothing else keeps a card on it.

    A word forgotten last season and right ever since has nothing to say to
    today's practice; it used to sit here for good, because the lapse count it
    was ranked by is the card's whole life and never falls.
    """
    _, notes = lesson
    answer(session, profile, notes[0], outcome="wrong", at=NOW - timedelta(days=90))
    state = session.get(CardStateRow, (profile.id, f"{notes[0].id}:fwd", DEFAULT_SCHEDULER))
    state.lapses = 2
    session.flush()

    assert weak_cards(session, profile, DEFAULT_SCHEDULER, now=NOW) == []


def test_a_card_going_wrong_now_carries_its_lapses_as_a_fact(session, profile, lesson):
    """Reported, but no longer what puts it here or where it sits."""
    _, notes = lesson
    answer(session, profile, notes[0], outcome="wrong", at=NOW - timedelta(days=1))
    state = session.get(CardStateRow, (profile.id, f"{notes[0].id}:fwd", DEFAULT_SCHEDULER))
    state.lapses = 2
    session.flush()

    weak = weak_cards(session, profile, DEFAULT_SCHEDULER, now=NOW)
    assert [(w.prompt, w.wrong, w.lapses) for w in weak] == [("나라", 1, 2)]


def test_judging_yourself_wrong_on_a_flip_counts(session, profile, lesson):
    """The checker never saw an answer; the scheduler still heard "again"."""
    _, notes = lesson
    record_answer(
        session,
        profile,
        AnswerIn(card_key=f"{notes[0].id}:fwd", mode="flip", grade=1, at=NOW),
        scheduler=DEFAULT_SCHEDULER,
    )
    weak = weak_cards(session, profile, DEFAULT_SCHEDULER, now=NOW)
    assert [(w.prompt, w.wrong) for w in weak] == [("나라", 1)]


def test_the_weak_list_says_where_the_card_lives(session, profile, lesson):
    _, notes = lesson
    answer(session, profile, notes[2], "rev", outcome="wrong")

    weak = weak_cards(session, profile, DEFAULT_SCHEDULER, now=NOW)[0]
    assert (weak.prompt, weak.answer, weak.direction) == ("doctor", "의사", "rev")
    assert weak.category_path == "korean/book1/02-introduction"
    assert weak.file_title == "2-1"
    assert (weak.group, weak.group_key) == (None, "jobs"), "no label of its own; the key is the heading"


def test_the_list_is_as_long_as_you_asked_for(session, profile, lesson):
    _, notes = lesson
    for note in notes:
        answer(session, profile, note, outcome="wrong")
    assert len(weak_cards(session, profile, DEFAULT_SCHEDULER, limit=2, now=NOW)) == 2


def test_an_archived_note_leaves_the_weak_list(session, profile, lesson):
    _, notes = lesson
    answer(session, profile, notes[0], outcome="wrong")
    archive_note(session, notes[0], archived=True)
    assert weak_cards(session, profile, DEFAULT_SCHEDULER, now=NOW) == []


# --- activity ---------------------------------------------------------------


def test_answers_are_counted_per_day(session, profile, lesson):
    _, notes = lesson
    answer(session, profile, notes[0], outcome="correct", at=NOW - timedelta(days=1))
    answer(session, profile, notes[1], outcome="correct", at=NOW)
    answer(session, profile, notes[2], outcome="wrong", at=NOW)

    days = activity(session, profile, tz_offset_minutes=SEOUL, now=NOW)
    assert [(d.day.isoformat(), d.reviews, d.correct) for d in days] == [
        ("2026-10-07", 1, 1),
        ("2026-10-08", 2, 1),
    ], "an 'almost' or a miss is an answer, not a correct one"


def test_a_day_is_the_day_you_were_in(session, profile, lesson):
    """A session at five in the morning in Seoul is that morning, not last night."""
    _, notes = lesson
    answer(session, profile, notes[0], at=datetime(2026, 10, 7, 20, 0, tzinfo=UTC))

    utc = activity(session, profile, tz_offset_minutes=0, now=NOW)
    seoul = activity(session, profile, tz_offset_minutes=SEOUL, now=NOW)
    assert [d.day.isoformat() for d in utc if d.reviews] == ["2026-10-07"]
    assert [d.day.isoformat() for d in seoul if d.reviews] == ["2026-10-08"]


def test_the_grid_reaches_today_even_on_a_day_you_did_nothing(session, profile, lesson):
    _, notes = lesson
    answer(session, profile, notes[0], at=NOW - timedelta(days=3))

    days = activity(session, profile, tz_offset_minutes=SEOUL, now=NOW)
    assert days[-1].day == (NOW + timedelta(minutes=SEOUL)).date()
    assert days[-1].reviews == 0


def test_nothing_answered_at_all_is_one_empty_day(session, profile, lesson):
    days = activity(session, profile, now=NOW)
    assert [(d.reviews, d.correct) for d in days] == [(0, 0)]


def test_old_answers_fall_out_of_the_window(session, profile, lesson):
    _, notes = lesson
    answer(session, profile, notes[0], at=NOW - timedelta(days=400))
    days = activity(session, profile, days=182, tz_offset_minutes=SEOUL, now=NOW)
    assert sum(d.reviews for d in days) == 0


# --- how long a sitting will take -------------------------------------------
#
# The start screen says "about ten minutes" against a size, and a figure that is
# wrong by half would be worse than no figure, so both halves are measured: how
# long an answer takes, and how many answers one card takes (PLAN 3.5).


def _many(session, count: int):
    category = ensure_category(session, "korean")
    file = create_file(session, category, title="lesson", default_type="directional")
    return create_notes(session, file, [{"front": f"w{i}", "back": f"b{i}"} for i in range(count)])


def test_a_pace_is_the_median_answer_times_how_often_one_card_is_asked(session, profile):
    notes = _many(session, 15)
    for note in notes:  # each card answered twice in the one day: two answers a card
        answer(session, profile, note, ms=10_000)
        answer(session, profile, note, ms=10_000)

    assert pace(session, profile, now=NOW) == pytest.approx(20.0)


def test_an_untimed_answer_still_counts_towards_how_often_a_card_is_asked(session, profile):
    """A `match` pair used to log no duration at all, and 36% of the real log is
    matching — it must not read as a card that was never asked."""
    notes = _many(session, 15)
    for note in notes:
        answer(session, profile, note, ms=10_000)
        answer(session, profile, note, mode="match", ms=None)
        answer(session, profile, note, ms=10_000)

    assert pace(session, profile, now=NOW) == pytest.approx(30.0), "three answers, median 10s"


def test_the_ratio_is_clamped_so_a_short_sitting_cannot_claim_one(session, profile):
    notes = _many(session, 4)
    for note in notes:
        for _ in range(8):  # eight answers to four cards is not a real ratio
            answer(session, profile, note, ms=5_000)

    assert pace(session, profile, now=NOW) == pytest.approx(15.0), "5s times the ceiling of 3"


def test_with_too_little_history_there_is_no_pace_to_report(session, profile, lesson):
    _, notes = lesson
    for note in notes:
        answer(session, profile, note, ms=9_000)

    assert pace(session, profile, now=NOW) is None, "three answers is a guess, not a median"


def test_an_answer_with_no_duration_anywhere_leaves_the_pace_unknown(session, profile):
    for note in _many(session, 25):
        answer(session, profile, note)

    assert pace(session, profile, now=NOW) is None


# --- when a card got where it is --------------------------------------------


def test_a_card_nobody_has_answered_got_nowhere_at_no_time():
    assert standing_since([]) == (NEW, None)


def test_a_card_dates_from_the_review_that_moved_it():
    """The ladder is climbed on a particular day, and the page wants to say which."""
    rows = log("choice", "rev", 4)
    where, since = standing_since(rows)
    assert where == KNOWN
    assert since == rows[3][3], "the fourth answer is the one that made it known"


def test_a_card_that_slipped_and_climbed_again_dates_from_the_climb():
    """Not from the first time it got there — that run is over."""
    climbed = log("choice", "rev", 4)
    slipped = then(then(climbed, "typed", "rev", AGAIN), "choice", "rev", AGAIN)
    assert standing_since(slipped)[0] == LEARNING

    # Enough clean answers to push both misses out of the accuracy window.
    back = slipped + [("choice", "rev", GOOD, slipped[-1][3] + timedelta(days=i + 1)) for i in range(7)]
    where, since = standing_since(back)
    assert where == KNOWN
    assert since == back[-1][3], "the answer that brought the rate back up"


def test_the_bucket_is_the_same_whether_or_not_you_ask_when():
    """`standing` is the half of `standing_since` most callers want, and no more."""
    for rows in ([], log("choice", "rev", 1), log("choice", "rev", 4), log("typed", "rev", 6)):
        assert standing(rows) == standing_since(rows)[0]


# --- the lists of words -----------------------------------------------------


def test_a_word_asked_both_ways_is_one_row(session, profile, lesson):
    """The list is as long as the count beside it, so a note is one row, front first."""
    _, notes = lesson
    found, total = words(session, profile, NEW)
    assert total == 3, "three notes"
    assert [(w.prompt, w.answer) for w in found[:1]] == [("나라", "country")]


def test_a_word_stands_where_its_weaker_side_does(session, profile, lesson):
    _, notes = lesson
    for day in range(4):
        answer(session, profile, notes[0], mode="choice", direction="rev", at=NOW + timedelta(days=day))

    assert words(session, profile, KNOWN)[1] == 0, "the forward card was never asked"
    (found,), _ = words(session, profile, NEW, limit=1)
    assert (found.prompt, found.direction) == ("나라", "fwd"), "named by the side holding it back"


def test_words_come_back_in_the_order_of_the_collection(session, profile, lesson):
    _, notes = lesson
    found, _ = words(session, profile, NEW)
    assert [w.prompt for w in found] == ["나라", "한국", "의사"]


def test_the_ones_you_know_come_back_most_recently_learnt_first(session, profile, lesson):
    """ "What have I just got the hang of" is the question the list answers."""
    _, notes = lesson
    for at, note in ((NOW - timedelta(days=10), notes[0]), (NOW, notes[1])):
        for day in range(6):
            for direction in ("fwd", "rev"):
                when = at + timedelta(days=day)
                answer(session, profile, note, mode="choice", direction=direction, at=when)

    found, total = words(session, profile, KNOWN)
    assert total == 2
    assert [w.prompt for w in found] == ["한국", "나라"], "the newer one leads"
    assert found[0].since is not None and found[0].since > found[1].since


def test_a_word_set_aside_is_in_no_bucket_and_in_its_own_list(session, profile, lesson):
    """The one list nothing in the app could reach: `_practisable` exists to hide it."""
    _, notes = lesson
    update_note(session, notes[0], {"suspended": True})

    assert [w.prompt for w in words(session, profile, NEW)[0]] == ["한국", "의사"]
    found, total = words(session, profile, SET_ASIDE)
    assert total == 1
    assert [(w.prompt, w.answer) for w in found] == [("나라", "country")]


def test_a_page_of_words_still_knows_how_many_there_are(session, profile, lesson):
    found, total = words(session, profile, NEW, limit=1, offset=1)
    assert (total, [w.prompt for w in found]) == (3, ["한국"])


def test_a_list_can_be_one_lesson_or_one_category(session, profile, lesson):
    file, _ = lesson
    other = create_file(
        session, ensure_category(session, "korean/book2"), title="b2", default_type="bidirectional"
    )
    create_notes(session, other, [{"front": "책", "back": "book"}])
    elsewhere = create_file(session, ensure_category(session, "korean/book10"), title="b10")
    create_notes(session, elsewhere, [{"front": "물", "back": "water"}])

    assert words(session, profile, NEW, data_file_id=file.id)[1] == 3
    assert [w.prompt for w in words(session, profile, NEW, category_path="korean/book2")[0]] == ["책"], (
        "a sibling whose name starts the same is not under it"
    )
    assert words(session, profile, NEW, category_path="korean")[1] == 5


def test_there_is_no_such_bucket_as_nonsense(session, profile, lesson):
    with pytest.raises(ValueError):
        words(session, profile, "nonsense")


def test_a_word_carries_where_it_came_from(session, profile, lesson):
    file, _ = lesson
    found, _ = words(session, profile, NEW)
    assert (found[0].data_file_id, found[0].file_title) == (file.id, "2-1")
    assert found[0].group_key == "countries"


# --- the pace counts the client's days --------------------------------------


def test_one_evening_across_utc_midnight_is_one_sitting(session, profile):
    """In Seoul it is one evening; in UTC it is two afternoons, and the ratio halves."""
    notes = _many(session, 10)
    evening = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)  # 23:30 in Seoul
    for n, note in enumerate(notes):
        at = evening + timedelta(minutes=n * 10)  # straddles midnight UTC
        answer(session, profile, note, ms=10_000, at=at)
        answer(session, profile, note, ms=10_000, at=at + timedelta(seconds=30))

    assert pace(session, profile, tz_offset_minutes=SEOUL, now=NOW) == pytest.approx(20.0)
    assert pace(session, profile, now=NOW) == pytest.approx(20.0), "both halves still two a card"
