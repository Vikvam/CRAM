"""Answers earned with no server to tell, handed back later (PLAN 5).

The phone grades with the same checker the laptop uses and keeps the rows; the
laptop is still the only thing that schedules. So these tests care about two
things: that a batch cannot be counted twice, and that rows arriving out of
order leave the same state as if they had been answered here all along.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from memo.collection.categories import ensure_category
from memo.collection.editing import archive_note, create_file, create_notes
from memo.collection.profiles import get_or_create_profile
from memo.db.models import CardState as CardStateRow
from memo.db.models import ReviewLog
from memo.overview import LEARNING, standing, standings
from memo.practice import AnswerIn, AnswerRow, ingest_answers, record_answer, replay
from memo.scheduling.registry import DEFAULT_SCHEDULER, SCHEDULERS

MONDAY = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@pytest.fixture
def lesson(session: Session):
    category = ensure_category(session, "korean/book1/03-family")
    file = create_file(
        session, category, title="3-1", front_lang="ko", back_lang="en", default_type="bidirectional"
    )
    notes = create_notes(
        session,
        file,
        [
            {"front": "아버지", "back": "father"},
            {"front": "어머니", "back": "mother"},
        ],
    )
    return file, notes


@pytest.fixture
def profile(session: Session):
    return get_or_create_profile(session)


def row(note, n, *, at=MONDAY, mode="typed", outcome="correct", direction="fwd", **extra):
    """One row as the phone would hand it over: its own id, its own clock."""
    return AnswerRow(
        client_id=f"c{n:04d}",
        at=at,
        card_key=f"{note.id}:{direction}",
        mode=mode,
        outcome=outcome,
        **extra,
    )


def took(session, profile, rows):
    return ingest_answers(session, profile, rows, scheduler=DEFAULT_SCHEDULER)


def logged(session, profile):
    return list(
        session.scalars(
            select(ReviewLog).where(ReviewLog.profile_id == profile.id).order_by(ReviewLog.ts, ReviewLog.id)
        )
    )


# --- taking a batch in ------------------------------------------------------


def test_answers_from_the_phone_become_ordinary_reviews(session, profile, lesson):
    _, notes = lesson
    report = took(session, profile, [row(notes[0], 1), row(notes[1], 2)])
    assert (report.accepted, report.duplicates, report.unknown) == (2, 0, [])
    assert len(logged(session, profile)) == 2


def test_the_phones_clock_is_kept_not_the_moment_it_arrived(session, profile, lesson):
    _, notes = lesson
    tuesday = MONDAY + timedelta(days=1, hours=3)
    took(session, profile, [row(notes[0], 1, at=tuesday)])
    assert logged(session, profile)[0].ts == tuesday, "when it was answered is what the log is for"


def test_the_direction_comes_from_the_card_not_the_client(session, profile, lesson):
    _, notes = lesson
    took(session, profile, [row(notes[0], 1, direction="rev")])
    assert logged(session, profile)[0].direction == "rev"


def test_a_row_that_was_never_scheduled_here_says_so(session, profile, lesson):
    _, notes = lesson
    took(session, profile, [row(notes[0], 1)])
    entry = logged(session, profile)[0]
    assert entry.state_before is None and entry.state_after is None, (
        "inventing the state it passed through would be writing a history that did not happen"
    )


def test_what_was_mastered_still_reads_off_these_rows(session, profile, lesson):
    """The mastery rule reads mode, direction and grade — all of which survive."""
    _, notes = lesson
    took(session, profile, [row(notes[0], 1)])
    assert standings(session, profile)[f"{notes[0].id}:fwd"] == LEARNING
    assert standing([("typed", "fwd", 3, datetime.now(UTC))]) == LEARNING


# --- it cannot be counted twice ---------------------------------------------


def test_the_same_batch_handed_back_twice_lands_once(session, profile, lesson):
    """Both halves of syncing are in play: the upload, and the file carried by hand."""
    _, notes = lesson
    batch = [row(notes[0], 1), row(notes[1], 2)]
    took(session, profile, batch)
    again = took(session, profile, batch)
    assert (again.accepted, again.duplicates) == (0, 2)
    assert len(logged(session, profile)) == 2


def test_a_batch_that_repeats_itself_is_caught_before_the_database(session, profile, lesson):
    _, notes = lesson
    twice = row(notes[0], 1)
    report = took(session, profile, [twice, twice])
    assert (report.accepted, report.duplicates) == (1, 1)


def test_answering_here_is_untouched_by_all_of_this(session, profile, lesson):
    """A row the server recorded itself has no client id, so it constrains nothing."""
    _, notes = lesson
    for direction in ("fwd", "rev"):
        record_answer(
            session,
            profile,
            AnswerIn(card_key=f"{notes[0].id}:{direction}", mode="typed", outcome="correct", at=MONDAY),
            scheduler=DEFAULT_SCHEDULER,
        )
    assert [entry.client_id for entry in logged(session, profile)] == [None, None]


# --- the state is rebuilt, not nudged ---------------------------------------


@pytest.mark.parametrize("scheduler", sorted(SCHEDULERS))
def test_a_week_of_phone_answers_leaves_what_answering_here_would_have(session, lesson, scheduler):
    """The point of replaying: arriving late must not mean arriving differently."""
    _, notes = lesson
    here, phone = get_or_create_profile(session, "here"), get_or_create_profile(session, "phone")
    days = [MONDAY + timedelta(days=n) for n in range(4)]
    key = f"{notes[0].id}:fwd"

    for at in days:
        record_answer(
            session,
            profile=here,
            answer=AnswerIn(card_key=key, mode="typed", outcome="correct", at=at),
            scheduler=scheduler,
        )
    # The same four answers, all handed over at once, newest first.
    ingest_answers(
        session,
        phone,
        [row(notes[0], n, at=at) for n, at in enumerate(reversed(days))],
        scheduler=scheduler,
    )

    def state(profile):
        cached = session.get(CardStateRow, (profile.id, key, scheduler))
        return (cached.state, round(cached.interval_days, 6), cached.reps, cached.last_review)

    assert state(phone) == state(here)


def test_an_answer_older_than_what_is_here_still_counts(session, profile, lesson):
    """Rows do not have to arrive in order; the cache is rebuilt from the log."""
    _, notes = lesson
    key = f"{notes[0].id}:fwd"
    record_answer(
        session,
        profile,
        AnswerIn(card_key=key, mode="typed", outcome="correct", at=MONDAY + timedelta(days=2)),
        scheduler=DEFAULT_SCHEDULER,
    )
    report = took(session, profile, [row(notes[0], 1, at=MONDAY, outcome="wrong")])
    cached = session.get(CardStateRow, (profile.id, key, DEFAULT_SCHEDULER))
    assert report.rebuilt == 1
    assert cached.reps == 2, "both answers are in the history the state is rebuilt from"


def test_every_cache_a_card_has_is_rebuilt(session, profile, lesson):
    """One log, one cache per scheduler, and none of them left stale.

    Replaying puts the card's whole history through the one scheduler being
    rebuilt, whoever recorded each row — which is what PLAN 5 means by the state
    being recomputable. Three rows in the log, so three reps in either cache.
    """
    _, notes = lesson
    key = f"{notes[0].id}:fwd"
    for scheduler in sorted(SCHEDULERS):
        record_answer(
            session,
            profile,
            AnswerIn(card_key=key, mode="typed", outcome="correct", at=MONDAY),
            scheduler=scheduler,
        )
    took(session, profile, [row(notes[0], 1, at=MONDAY + timedelta(days=1))])
    for scheduler in sorted(SCHEDULERS):
        cached = session.get(CardStateRow, (profile.id, key, scheduler))
        assert cached.reps == 3, f"{scheduler} was left behind"


# --- what can go wrong ------------------------------------------------------


def test_a_card_that_has_since_been_deleted_does_not_lose_the_batch(session, profile, lesson):
    _, notes = lesson
    archive_note(session, notes[1])
    session.delete(session.get(type(notes[1]), notes[1].id))
    session.flush()
    report = took(session, profile, [row(notes[0], 1), row(notes[1], 2)])
    assert report.accepted == 1
    assert report.unknown == [f"{notes[1].id}:fwd"], "named, so it can be explained rather than vanish"


def test_a_flip_without_a_grade_is_named_not_raised(session, profile, lesson):
    """flip is self-graded, so a row with no grade is incoherent, not merely odd.

    It is still not worth refusing the batch over: the phone that sent it cannot
    mend the row and has no way to put it down, so refusing would leave it
    offering the same bad row for ever.
    """
    _, notes = lesson
    report = took(session, profile, [row(notes[0], 1, mode="flip", outcome=None)])
    assert (report.accepted, report.rejected) == (0, ["c0001"])


def test_one_bad_row_does_not_cost_the_good_ones(session, profile, lesson):
    _, notes = lesson
    report = took(
        session,
        profile,
        [row(notes[0], 1, mode="flip", outcome=None), row(notes[1], 2, outcome="correct")],
    )
    assert (report.accepted, report.rejected) == (1, ["c0001"])


def test_nothing_in_means_nothing_done(session, profile):
    report = took(session, profile, [])
    assert (report.accepted, report.duplicates, report.rebuilt) == (0, 0, 0)


@pytest.mark.parametrize("scheduler", sorted(SCHEDULERS))
def test_an_answer_given_ahead_of_schedule_replays_the_same(session, profile, lesson, scheduler):
    """The freeze has to be reproducible, or the cache and the log disagree.

    It is a pure function of the state and the clock, so replaying the log must
    reach it again — including for a row that arrives days later from a phone.
    """
    _, notes = lesson
    key = f"{notes[0].id}:fwd"
    for day in range(4):
        record_answer(
            session,
            profile,
            AnswerIn(card_key=key, mode="typed", outcome="correct", at=MONDAY + timedelta(days=day * 3)),
            scheduler=scheduler,
        )
    cached = session.get(CardStateRow, (profile.id, key, scheduler))
    scheduled_for = cached.due

    # Practised the next morning, long before it was due.
    record_answer(
        session,
        profile,
        AnswerIn(card_key=key, mode="typed", outcome="correct", at=MONDAY + timedelta(days=10)),
        scheduler=scheduler,
    )
    session.flush()
    cached = session.get(CardStateRow, (profile.id, key, scheduler))
    assert cached.due == scheduled_for, "practising ahead cost the card nothing"

    def memory(data: dict) -> dict:
        # `card_id` is py-fsrs's own identity, minted from the clock when a card
        # is first built, so it differs between a live answer and a replay. It is
        # not scheduling state: stability and difficulty are.
        return {k: v for k, v in data.items() if k != "card_id"}

    rebuilt = replay(session, profile, key, scheduler)
    assert (rebuilt.due, round(rebuilt.interval_days, 6), rebuilt.reps, memory(rebuilt.data)) == (
        cached.due,
        round(cached.interval_days, 6),
        cached.reps,
        memory(cached.data),
    )
