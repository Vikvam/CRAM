"""Pydantic models.

Two distinct schemas, deliberately not shared (PLAN 3.6):

* :mod:`memo.models.datafile` — the lenient storage/interchange format.
* :mod:`memo.models.extraction` — the strict, flat shape an LLM must answer with.

:mod:`memo.models.adapter` turns the second into the first.
"""

from memo.models.datafile import (
    CURRENT_VERSION,
    DataFile,
    Group,
    Label,
    Note,
    NoteType,
    load_datafile,
)

__all__ = [
    "CURRENT_VERSION",
    "DataFile",
    "Group",
    "Label",
    "Note",
    "NoteType",
    "load_datafile",
]
