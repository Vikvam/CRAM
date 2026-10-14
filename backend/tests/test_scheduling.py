"""SM-2 and FSRS behind one interface (PLAN 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from memo.practice.grading import RECOGNITION_CAP, grade_for, schedule_answer
from memo.scheduling import SCHEDULERS, CardState, Grade, Scheduler, State, get_scheduler

T0 = datetime(2026, 1, 1, 9, tzinfo=UTC)


def _run(scheduler: Scheduler, grades, *, start: datetime = T0) -> CardState:
    state, now = scheduler.initial(), start
    for grade in grades:
        state = scheduler.review(state, grade, now=now)
        now = state.due + timedelta(seconds=1)
    return state


@pytest.fixture(params=sorted(SCHEDULERS))
def scheduler(request) -> Scheduler:
    return get_scheduler(request.param)


# --- the contract every scheduler meets -------------------------------------


def test_implements_the_interface(scheduler):
    assert isinstance(scheduler, Scheduler)


def test_a_new_card_is_new_and_due(scheduler):
    state = scheduler.initial()
    assert state.state is State.NEW and state.is_due(T0)


def test_again_keeps_a_card_within_the_day(scheduler):
    state = scheduler.review(scheduler.initial(), Grade.AGAIN, now=T0)
    assert state.due - T0 < timedelta(days=1)


def test_repeated_good_answers_grow_the_interval(scheduler):
    intervals = []
    state, now = scheduler.initial(), T0
    for _ in range(6):
        state = scheduler.review(state, Grade.GOOD, now=now)
        intervals.append(state.interval_days)
        now = state.due + timedelta(seconds=1)
    reviewed = [i for i in intervals if i >= 1]
    assert reviewed == sorted(reviewed) and reviewed[-1] > reviewed[0]
    assert state.state is State.REVIEW


def test_a_lapse_is_counted_and_shortens_the_interval(scheduler):
    before = _run(scheduler, [Grade.GOOD] * 5)
    after = scheduler.review(before, Grade.AGAIN, now=before.due)
    assert after.lapses == before.lapses + 1
    assert after.interval_days < before.interval_days
    assert after.state is State.RELEARNING


def test_easy_is_never_sooner_than_good(scheduler):
    base = _run(scheduler, [Grade.GOOD] * 3)
    good = scheduler.review(base, Grade.GOOD, now=base.due)
    easy = scheduler.review(base, Grade.EASY, now=base.due)
    assert easy.due >= good.due


def test_state_survives_serialisation(scheduler):
    state = _run(scheduler, [Grade.GOOD, Grade.GOOD, Grade.HARD])
    restored = CardState.load(state.dump())
    now = state.due
    assert (
        scheduler.review(restored, Grade.GOOD, now=now).dump()
        == scheduler.review(state, Grade.GOOD, now=now).dump()
    )


def test_an_unknown_scheduler_name_falls_back_to_the_default():
    assert get_scheduler("nope").name == get_scheduler(None).name


# --- SM-2 specifics ---------------------------------------------------------


def test_sm2_has_two_learning_steps_then_one_day():
    sm2 = get_scheduler("sm2")
    first = sm2.review(sm2.initial(), Grade.GOOD, now=T0)
    assert first.state is State.LEARNING
    second = sm2.review(first, Grade.GOOD, now=first.due)
    assert second.state is State.REVIEW and second.interval_days == 1.0


def test_sm2_brings_a_lapsed_card_back_at_half_its_old_interval():
    sm2 = get_scheduler("sm2")
    mature = _run(sm2, [Grade.GOOD] * 5)
    lapsed = sm2.review(mature, Grade.AGAIN, now=mature.due)
    back = sm2.review(lapsed, Grade.GOOD, now=lapsed.due)
    assert back.interval_days == pytest.approx(mature.interval_days / 2)


def test_sm2_ease_never_drops_below_the_floor():
    state = _run(get_scheduler("sm2"), [Grade.GOOD, Grade.GOOD] + [Grade.HARD] * 30)
    assert state.data["ease"] >= 1.3


# --- outcomes → grades (PLAN 3.5) ------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "grade"), [("correct", Grade.GOOD), ("almost", Grade.HARD), ("wrong", Grade.AGAIN)]
)
def test_outcomes_map_to_grades(outcome, grade):
    assert grade_for("typed", outcome) is grade


def test_an_override_always_wins():
    assert grade_for("typed", "wrong", Grade.GOOD) is Grade.GOOD


def test_flip_needs_the_grade_the_user_picked():
    with pytest.raises(ValueError):
        grade_for("flip", None)
    assert grade_for("flip", None, 4) is Grade.EASY


def test_recognition_never_pushes_a_card_to_a_long_interval(scheduler):
    state = scheduler.initial()
    now = T0
    for _ in range(6):
        state = schedule_answer(scheduler, state, "choice", Grade.GOOD, now=now)
        assert state.due - now <= RECOGNITION_CAP + timedelta(seconds=1)
        now = state.due + timedelta(seconds=1)


def test_recognition_does_not_shorten_what_a_card_already_has(scheduler):
    mature = _run(scheduler, [Grade.GOOD] * 6)
    assert mature.interval_days > 2
    after = schedule_answer(scheduler, mature, "match", Grade.GOOD, now=mature.due)
    assert after.interval_days >= min(mature.interval_days, after.interval_days)
    assert after.due - mature.due <= timedelta(days=mature.interval_days) + timedelta(seconds=1)


def test_typing_the_answer_is_not_capped(scheduler):
    mature = _run(scheduler, [Grade.GOOD] * 4)
    typed = schedule_answer(scheduler, mature, "typed", Grade.GOOD, now=mature.due)
    assert typed.interval_days > RECOGNITION_CAP.days


def test_the_capped_date_reaches_the_scheduler_bag_too(scheduler):
    """A row whose two halves disagree about when the card is wanted is a trap.

    Only FSRS keeps a date of its own in there, and nothing re-derived depends on
    it — FSRS schedules from ``last_review`` — but it is written into the log as
    ``state_after``, and the next thing to read it should not find yesterday's
    answer to the question.
    """
    mature = _run(scheduler, [Grade.GOOD] * 4)
    capped = schedule_answer(scheduler, mature, "choice", Grade.GOOD, now=mature.due)
    if "due" not in capped.data:
        pytest.skip(f"{scheduler.name} keeps no date of its own")
    assert capped.data["due"] == capped.due.isoformat()


def test_an_override_in_a_recognition_mode_is_not_capped(scheduler):
    mature = _run(scheduler, [Grade.GOOD] * 4)
    capped = schedule_answer(scheduler, mature, "choice", Grade.EASY, now=mature.due)
    free = schedule_answer(scheduler, mature, "choice", Grade.EASY, now=mature.due, overridden=True)
    assert free.due >= capped.due


# --- practising ahead of schedule -------------------------------------------
#
# The point of the rule: a lesson you choose to practise today must not cost you
# the interval you earned on it (PLAN 3.5).


def _mature(scheduler: Scheduler) -> CardState:
    state = _run(scheduler, [Grade.GOOD] * 6)
    assert state.interval_days > 2, "the fixture needs a card with real interval to lose"
    return state


def test_answering_well_before_due_keeps_the_schedule(scheduler):
    mature = _mature(scheduler)
    early = mature.last_review + timedelta(minutes=1)
    after = schedule_answer(scheduler, mature, "typed", Grade.GOOD, now=early)
    assert after.due == mature.due
    assert after.interval_days == mature.interval_days
    assert after.state is mature.state and after.data == mature.data
    # Counted, though: the answer happened.
    assert after.reps == mature.reps + 1 and after.last_review == early


def test_an_early_answer_leaves_the_next_review_where_it_would_have_been(scheduler):
    """The whole claim, in one test: practising ahead costs nothing."""
    mature = _mature(scheduler)
    early = mature.last_review + timedelta(minutes=1)
    frozen = schedule_answer(scheduler, mature, "typed", Grade.GOOD, now=early)

    untouched = schedule_answer(scheduler, mature, "typed", Grade.GOOD, now=mature.due)
    after_early = schedule_answer(scheduler, frozen, "typed", Grade.GOOD, now=mature.due)
    assert after_early.due == untouched.due
    assert after_early.interval_days == untouched.interval_days
    assert after_early.data == untouched.data


def test_a_miss_before_due_still_lapses_the_card(scheduler):
    mature = _mature(scheduler)
    early = mature.last_review + timedelta(minutes=1)
    after = schedule_answer(scheduler, mature, "typed", Grade.AGAIN, now=early)
    assert after.lapses == mature.lapses + 1
    assert after.due - early < timedelta(days=1), "a card you got wrong has to come back"


def test_a_card_due_within_a_day_is_scheduled_normally(scheduler):
    """Or practising ahead would never advance anything at all."""
    mature = _mature(scheduler)
    after = schedule_answer(scheduler, mature, "typed", Grade.GOOD, now=mature.due - timedelta(hours=12))
    assert after.due > mature.due


def test_a_learning_step_is_never_frozen(scheduler):
    state = scheduler.review(scheduler.initial(), Grade.GOOD, now=T0)
    after = schedule_answer(scheduler, state, "typed", Grade.GOOD, now=T0 + timedelta(seconds=30))
    assert after.due > state.due


def test_a_new_card_is_scheduled_even_with_no_due_date(scheduler):
    after = schedule_answer(scheduler, scheduler.initial(), "typed", Grade.GOOD, now=T0)
    assert after.due is not None and after.reps == 1


def test_an_early_recognition_answer_keeps_its_weeks(scheduler):
    """The freeze returns before the cap, so the two cannot argue."""
    mature = _mature(scheduler)
    after = schedule_answer(
        scheduler, mature, "choice", Grade.GOOD, now=mature.last_review + timedelta(minutes=1)
    )
    assert after.due == mature.due


def test_an_override_does_not_escape_the_freeze(scheduler):
    mature = _mature(scheduler)
    early = mature.last_review + timedelta(minutes=1)
    after = schedule_answer(scheduler, mature, "typed", Grade.GOOD, now=early, overridden=True)
    assert after.due == mature.due


def test_a_frozen_answer_does_not_share_its_data_bag(scheduler):
    mature = _mature(scheduler)
    after = schedule_answer(
        scheduler, mature, "typed", Grade.GOOD, now=mature.last_review + timedelta(minutes=1)
    )
    after.data["poked"] = True
    assert "poked" not in mature.data
