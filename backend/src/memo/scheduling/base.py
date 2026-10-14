"""The interface both schedulers implement.

Deliberately narrow: a scheduler turns (state, grade, when) into a new state and
nothing else. It never reads the database, never decides what to show, and never
sees a practice mode — that keeps the two implementations comparable and lets a
third be added without touching practice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any, Protocol, runtime_checkable


class Grade(IntEnum):
    """Anki's four buttons. Outcomes map onto these in :mod:`memo.practice`."""

    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class State(StrEnum):
    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


@dataclass(slots=True)
class CardState:
    """Everything a scheduler knows about one card, and nothing more.

    ``data`` is the scheduler's own bag (FSRS stability/difficulty, SM-2 ease),
    stored as JSON so neither implementation needs a column of its own.
    """

    due: datetime | None = None
    state: State = State.NEW
    interval_days: float = 0.0
    reps: int = 0
    lapses: int = 0
    last_review: datetime | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def is_due(self, now: datetime | None = None) -> bool:
        return self.due is None or self.due <= (now or datetime.now(UTC))

    def dump(self) -> dict[str, Any]:
        return {
            "due": self.due.isoformat() if self.due else None,
            "state": str(self.state),
            "interval_days": self.interval_days,
            "reps": self.reps,
            "lapses": self.lapses,
            "last_review": self.last_review.isoformat() if self.last_review else None,
            "data": self.data,
        }

    @classmethod
    def load(cls, raw: dict[str, Any] | None) -> CardState:
        if not raw:
            return cls()
        return cls(
            due=_parse(raw.get("due")),
            state=State(raw.get("state", State.NEW)),
            interval_days=float(raw.get("interval_days") or 0.0),
            reps=int(raw.get("reps") or 0),
            lapses=int(raw.get("lapses") or 0),
            last_review=_parse(raw.get("last_review")),
            data=dict(raw.get("data") or {}),
        )


def _parse(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@runtime_checkable
class Scheduler(Protocol):
    name: str

    def initial(self) -> CardState:
        """The state of a card that has never been seen."""

    def review(self, state: CardState, grade: Grade, *, now: datetime | None = None) -> CardState:
        """The state after answering ``grade`` at ``now``."""


def days(value: float) -> timedelta:
    return timedelta(days=value)
