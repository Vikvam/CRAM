"""FSRS, via py-fsrs.

Wrapped rather than reimplemented: the point of having two schedulers is to
compare a modern one against SM-2 on the same review log, which only works if
this really is FSRS.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fsrs import Card as FSRSCard
from fsrs import Rating
from fsrs import Scheduler as FSRSScheduler
from fsrs import State as FSRSState

from memo.scheduling.base import CardState, Grade, State

_RATING = {
    Grade.AGAIN: Rating.Again,
    Grade.HARD: Rating.Hard,
    Grade.GOOD: Rating.Good,
    Grade.EASY: Rating.Easy,
}

_STATE = {
    FSRSState.Learning: State.LEARNING,
    FSRSState.Review: State.REVIEW,
    FSRSState.Relearning: State.RELEARNING,
}


class FSRSAdapter:
    name = "fsrs"

    def __init__(self, *, desired_retention: float = 0.9, parameters: list[float] | None = None):
        # No fuzzing: card state is a cache that must be recomputable from the
        # review log (PLAN 5), and random jitter would make every replay differ.
        kwargs: dict[str, Any] = {"desired_retention": desired_retention, "enable_fuzzing": False}
        if parameters:
            kwargs["parameters"] = parameters
        self._scheduler = FSRSScheduler(**kwargs)

    def initial(self) -> CardState:
        return CardState(state=State.NEW, data={})

    def review(self, state: CardState, grade: Grade, *, now: datetime | None = None) -> CardState:
        now = now or datetime.now(UTC)
        card = self._to_fsrs(state)
        reviewed, _log = self._scheduler.review_card(card, _RATING[Grade(grade)], review_datetime=now)

        due = reviewed.due if reviewed.due.tzinfo else reviewed.due.replace(tzinfo=UTC)
        lapses = state.lapses + (1 if Grade(grade) is Grade.AGAIN and state.state is State.REVIEW else 0)
        return CardState(
            due=due,
            state=_STATE.get(reviewed.state, State.LEARNING),
            interval_days=max(0.0, (due - now).total_seconds() / 86400),
            reps=state.reps + 1,
            lapses=lapses,
            last_review=now,
            data=_serialisable(reviewed.to_dict()),
        )

    def _to_fsrs(self, state: CardState) -> FSRSCard:
        """A card we have never scheduled with FSRS starts fresh, even if SM-2 knows it.

        Switching scheduler mid-collection therefore restarts FSRS's own memory
        model but keeps the review log, which is what can rebuild it later.
        """
        if not state.data or "state" not in state.data:
            return FSRSCard()
        return FSRSCard.from_dict(state.data)


def _serialisable(data: dict[str, Any]) -> dict[str, Any]:
    return {key: (value.isoformat() if isinstance(value, datetime) else value) for key, value in data.items()}
