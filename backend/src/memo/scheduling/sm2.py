"""SM-2, with Anki-style learning steps.

The classic algorithm: an ease factor per card, intervals multiplied by it, a
lapse sending the card back to relearning. Kept because it is predictable and
easy to reason about when something looks wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime

from memo.scheduling.base import CardState, Grade, State, days

INITIAL_EASE = 2.5
MIN_EASE = 1.3
#: Minutes before a card in learning comes back. Two steps, like Anki's default.
LEARNING_STEPS = (1.0, 10.0)
RELEARNING_STEPS = (10.0,)
HARD_MULTIPLIER = 1.2
EASY_BONUS = 1.3
MAX_INTERVAL_DAYS = 365 * 10


class SM2Scheduler:
    name = "sm2"

    def __init__(
        self,
        *,
        learning_steps: tuple[float, ...] = LEARNING_STEPS,
        relearning_steps: tuple[float, ...] = RELEARNING_STEPS,
        max_interval_days: float = MAX_INTERVAL_DAYS,
    ):
        self.learning_steps = learning_steps
        self.relearning_steps = relearning_steps
        self.max_interval_days = max_interval_days

    def initial(self) -> CardState:
        return CardState(state=State.NEW, data={"ease": INITIAL_EASE, "step": 0})

    def review(self, state: CardState, grade: Grade, *, now: datetime | None = None) -> CardState:
        now = now or datetime.now(UTC)
        grade = Grade(grade)
        ease = float(state.data.get("ease", INITIAL_EASE))
        step = int(state.data.get("step", 0))
        interval = state.interval_days
        lapses = state.lapses
        phase = state.state

        if phase in (State.NEW, State.LEARNING, State.RELEARNING):
            steps = self.relearning_steps if phase is State.RELEARNING else self.learning_steps
            if grade is Grade.AGAIN:
                step = 0
            elif grade is Grade.EASY:
                step = len(steps)  # skip the rest of the steps
            elif grade is Grade.GOOD:
                step += 1
            # HARD repeats the current step.

            if step < len(steps):
                return _state(
                    now=now,
                    minutes=steps[step],
                    phase=State.RELEARNING if phase is State.RELEARNING else State.LEARNING,
                    reps=state.reps + 1,
                    lapses=lapses,
                    ease=ease,
                    step=step,
                    extra=_carry(state),
                )
            # Graduated.
            # A lapsed card comes back at half of what it used to hold, never below a day.
            if phase is State.RELEARNING:
                interval = max(1.0, float(state.data.get("lapsed_from", 0.0)) * 0.5)
            else:
                interval = 4.0 if grade is Grade.EASY else 1.0
            return _state(
                now=now,
                interval=min(interval, self.max_interval_days),
                phase=State.REVIEW,
                reps=state.reps + 1,
                lapses=lapses,
                ease=ease,
                step=0,
            )

        # A card in review.
        if grade is Grade.AGAIN:
            ease = max(MIN_EASE, ease - 0.20)
            lapses += 1
            return _state(
                now=now,
                minutes=self.relearning_steps[0],
                phase=State.RELEARNING,
                reps=state.reps + 1,
                lapses=lapses,
                ease=ease,
                step=0,
                extra={"lapsed_from": interval},
            )

        base = max(interval, 1.0)
        if grade is Grade.HARD:
            ease = max(MIN_EASE, ease - 0.15)
            interval = base * HARD_MULTIPLIER
        elif grade is Grade.GOOD:
            interval = base * ease
        else:  # EASY
            ease += 0.15
            interval = base * ease * EASY_BONUS

        return _state(
            now=now,
            interval=min(interval, self.max_interval_days),
            phase=State.REVIEW,
            reps=state.reps + 1,
            lapses=lapses,
            ease=ease,
            step=0,
        )


def _state(
    *,
    now: datetime,
    phase: State,
    reps: int,
    lapses: int,
    ease: float,
    step: int,
    interval: float | None = None,
    minutes: float | None = None,
    extra: dict[str, float] | None = None,
) -> CardState:
    if minutes is not None:
        # Sub-day steps: the card is due in minutes and holds no interval yet.
        due = now + days(minutes / (24 * 60))
        interval_days = 0.0
    else:
        interval_days = float(interval or 0.0)
        due = now + days(interval_days)
    return CardState(
        due=due,
        state=phase,
        interval_days=interval_days,
        reps=reps,
        lapses=lapses,
        last_review=now,
        data={"ease": round(ease, 4), "step": step, **(extra or {})},
    )


def _carry(state: CardState) -> dict[str, float]:
    """Keep the pre-lapse interval alive across the relearning steps."""
    lapsed_from = state.data.get("lapsed_from")
    return {"lapsed_from": float(lapsed_from)} if lapsed_from else {}
