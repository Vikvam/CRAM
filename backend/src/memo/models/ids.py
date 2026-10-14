"""Stable IDs. Assigned by the server, never taken from an LLM (PLAN 3, rule 4)."""

from __future__ import annotations

from ulid import ULID


def new_id(prefix: str) -> str:
    return f"{prefix}_{ULID()}"


def datafile_id() -> str:
    return new_id("df")


def note_id() -> str:
    return new_id("n")


def job_id() -> str:
    return new_id("job")
