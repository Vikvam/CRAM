"""The reader every install has: the prompt from ``docs/llm-prompt.md``, unchanged.

The same words a person pastes into any chat, so what the app does with a photo
and what an LLM does with a PDF are one thing to get right. ``tests/test_docs.py``
fails if the file here and the block in the doc ever differ.
"""

from __future__ import annotations

from importlib.resources import files

from memo.importers.base import DatafileImporter

PROMPT = files("memo.importers").joinpath("prompts/general.md").read_text(encoding="utf-8")

IMPORTER = DatafileImporter(
    name="general",
    description="Any page of study material: lists, tables, glossaries, questions, or prose. The fallback.",
    prompt=PROMPT,
    kinds=("image", "pdf", "text"),
)
