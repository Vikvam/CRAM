"""From an outcome to a scheduler grade (PLAN 3.5).

The checker never produces a number, and neither does this: an outcome and a
mode become one of four grades by a small readable table, plus one rule —
recognising an answer is not the same as producing it, so recognition modes can
never push a card to a long interval.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from memo.scheduling.base import CardState, Grade, Scheduler

PRODUCTIVE_MODES = frozenset({"typed", "build"})
RECOGNITION_MODES = frozenset({"choice", "match"})
SELF_GRADED_MODES = frozenset({"flip"})

#: The longest interval a recognition-mode answer may earn a card (PLAN 3.5: "learning").
RECOGNITION_CAP = timedelta(days=1)

#: An answer with more than this still to run does not reschedule the card at all.
#: Below the floor the card is about to come round anyway, so freezing it would mean
#: practising ahead never advanced anything.
EARLY_FLOOR = timedelta(days=1)

_OUTCOME_GRADE = {
    "correct": Grade.GOOD,
    "almost": Grade.HARD,  # "needs practice", not a failure
    "wrong": Grade.AGAIN,
}


def grade_for(mode: str, outcome: str | None, override: Grade | int | None = None) -> Grade:
    """The grade the scheduler sees. An explicit choice by the user always wins."""
    if override is not None:
        return Grade(override)
    if mode in SELF_GRADED_MODES:
        raise ValueError("flip is self-graded: pass the grade the user picked as `override`")
    if outcome not in _OUTCOME_GRADE:
        raise ValueError(f"unknown outcome {outcome!r}")
    return _OUTCOME_GRADE[outcome]


def answered_early(before: CardState, now: datetime) -> bool:
    """True when the card would still not be due a day from now.

    A pure function of ``(before, now)``, for the same reason the rest of this
    module is: ``replay`` rebuilds state from the log alone and has to reach the
    same answer. Note the floor is only reachable from ``State.REVIEW`` with an
    interval over a day, so learning steps and new cards are excluded by it.
    """
    return before.due is not None and before.due - now > EARLY_FLOOR


def schedule_answer(
    scheduler: Scheduler,
    before: CardState,
    mode: str,
    grade: Grade,
    *,
    now: datetime | None = None,
    overridden: bool = False,
) -> CardState:
    """Run the scheduler, then apply the recognition cap.

    The cap never shortens what a card already had: a card at three weeks that
    is recognised in `choice` keeps its three weeks, it just doesn't gain more.
    An explicit override is the user's judgement, and is not capped.

    An answer given well ahead of the card's schedule is counted but does not
    reschedule it, so practising a lesson you feel like practising cannot cost
    you the interval you earned (PLAN 3.5). The freeze is needed because neither
    scheduler would move `due` *backwards* — the loss is elsewhere: SM-2 ignores
    elapsed time and so restarts the same interval from today, forfeiting the
    remainder, while FSRS reads it and damps the stability gain, which shortens
    the interval and is written into `data`. A miss is exempt: getting it wrong
    early is real information and the card has to come back.
    """
    now = now or datetime.now(UTC)
    if grade is not Grade.AGAIN and answered_early(before, now):
        # `data` is copied, not aliased: it is about to be stored three times
        # over (the cache, `state_before`, `state_after`).
        return replace(before, reps=before.reps + 1, last_review=now, data=dict(before.data))
    after = scheduler.review(before, grade, now=now)
    if mode not in RECOGNITION_MODES or overridden or after.due is None:
        return after

    ceiling = max(RECOGNITION_CAP, timedelta(days=before.interval_days))
    if after.due - now > ceiling:
        after.due = now + ceiling
        after.interval_days = ceiling.total_seconds() / 86400
        # The scheduler's own bag may carry a copy of the date (FSRS does), and a
        # row whose two halves disagree about when the card is next wanted is a
        # trap for whatever reads the bag next. Nothing re-derived changes: the
        # elapsed time FSRS actually schedules from is `last_review`, and
        # `replay` applies this same cap on the way through.
        if "due" in after.data:
            after.data = {**after.data, "due": after.due.isoformat()}
    return after
