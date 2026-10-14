"""What an importer is (PLAN 4).

Data, not code: a prompt, what it answers with, and a few defaults. So a new
known format is a spec file in ``importers.local/`` (see ``local.py``), not a
change to the app.

There are two kinds, by what the model is asked to answer with:

- :class:`Importer` — the strict *extraction* shape, turned into a data file by
  the adapter (PLAN 3.6). Narrow and reliable even on a weak provider.
- :class:`DatafileImporter` — a complete ``memo.datafile`` straight away, in
  ```json blocks. What the general reader does, with the prompt from
  ``docs/llm-prompt.md``, because one prompt that works for any material is
  worth more than a strict shape that only fits pairs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from memo.models.datafile import NoteType
from memo.models.extraction import PROMPT_VERSION, ExtractionResult

#: Built into the app, or loaded from the local importer folder.
BUILTIN = "builtin"
LOCAL = "local"


@dataclass(slots=True, frozen=True)
class Importer:
    name: str
    #: Shown in the UI and given to the router, which picks from these sentences.
    description: str
    system_prompt: str
    extraction_model: type[BaseModel] = ExtractionResult
    example: dict[str, Any] | None = None
    default_type: NoteType = NoteType.BIDIRECTIONAL
    front_lang: str | None = None
    back_lang: str | None = None
    prompt_version: int = PROMPT_VERSION
    #: Source kinds this importer can read; the router only sees matching ones.
    kinds: tuple[str, ...] = field(default=("image", "pdf"))
    origin: str = BUILTIN

    def page_instruction(self, page_number: int | None, total: int | None) -> str:
        if page_number is None:
            return "Extract everything from this page."
        if total and total > 1:
            return f"This is page {page_number} of {total}. Extract everything from this page only."
        return f"This is page {page_number}. Extract everything from it."


@dataclass(slots=True, frozen=True)
class DatafileImporter:
    name: str
    description: str
    #: Sent as it is, then the lines that fill its "My instructions" slot, then the page.
    prompt: str
    prompt_version: int = 1
    #: Used only where the model's answer leaves them out.
    default_type: NoteType | None = None
    front_lang: str | None = None
    back_lang: str | None = None
    kinds: tuple[str, ...] = field(default=("image", "pdf"))
    origin: str = BUILTIN


AnyImporter = Importer | DatafileImporter
