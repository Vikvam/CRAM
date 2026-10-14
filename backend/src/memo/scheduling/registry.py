"""Which schedulers exist, and how a name becomes one."""

from __future__ import annotations

from collections.abc import Callable

from memo.scheduling.base import Scheduler
from memo.scheduling.fsrs_impl import FSRSAdapter
from memo.scheduling.sm2 import SM2Scheduler

DEFAULT_SCHEDULER = "fsrs"

SCHEDULERS: dict[str, Callable[[], Scheduler]] = {
    "sm2": SM2Scheduler,
    "fsrs": FSRSAdapter,
}


def get_scheduler(name: str | None = None) -> Scheduler:
    """Unknown names fall back to the default rather than stopping a session."""
    factory = SCHEDULERS.get(name or DEFAULT_SCHEDULER, SCHEDULERS[DEFAULT_SCHEDULER])
    return factory()
