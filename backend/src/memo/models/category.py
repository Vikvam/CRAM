"""Category config (PLAN 3.3).

A row in the DB; exported as ``_category.json``. Settings are inherited down the
tree, so every field is optional and ``None`` means "ask my parent".
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from memo.models.base import LenientModel
from memo.models.datafile import CATEGORY_FORMAT, CURRENT_VERSION, Label, NoteType

#: Every practice mode that exists (PLAN 3.5). Order is the UI order.
ALL_MODES = ("flip", "typed", "choice", "match", "build")

#: Where multiple-choice distractors may come from (PLAN 3.5).
DISTRACTOR_SCOPES = ("auto", "group", "file", "category")


class TypedSettings(LenientModel):
    """Overrides for the typed-answer checker.

    Defaults are language-neutral (PLAN 3.7); these exist for content that needs
    something else, e.g. maths splitting on terms rather than grapheme clusters.
    """

    almost_distance_short: int | None = None
    almost_distance_long: int | None = None
    long_threshold: int | None = None
    split: str | None = None  # "auto" | "whitespace" | "grapheme" | "terms"


class PracticeSettings(LenientModel):
    modes: list[str] | None = None
    adaptive: bool | None = None
    distractor_scope: str | None = None
    typed: TypedSettings | None = None
    scheduler: str | None = None  # "sm2" | "fsrs"
    extra: dict[str, Any] | None = None


class ImportSettings(LenientModel):
    profiles: list[str] | None = None
    upload_page: bool | None = None
    default_profile: str | None = None
    extra: dict[str, Any] | None = None


class CategoryConfig(LenientModel):
    format: str = CATEGORY_FORMAT
    version: int = CURRENT_VERSION
    label: Label | None = None
    default_type: NoteType | None = None
    front_lang: str | None = None
    back_lang: str | None = None
    practice: PracticeSettings | None = None
    import_: ImportSettings | None = Field(default=None, alias="import")
    extra: dict[str, Any] | None = None


def inherit(child: CategoryConfig | None, parent: CategoryConfig | None) -> CategoryConfig:
    """Resolve one level of inheritance: the child wins wherever it says anything.

    Nested blocks merge key by key, so a category can override
    ``practice.distractor_scope`` without restating ``practice.modes``.
    """
    if child is None and parent is None:
        return CategoryConfig()
    if child is None:
        return parent.model_copy(deep=True)  # type: ignore[union-attr]
    if parent is None:
        return child.model_copy(deep=True)

    merged = parent.model_dump(mode="json", exclude_none=True, by_alias=True)
    over = child.model_dump(mode="json", exclude_none=True, by_alias=True)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return CategoryConfig.model_validate(merged)


def effective_modes(config: CategoryConfig) -> list[str]:
    modes = (config.practice.modes if config.practice else None) or list(ALL_MODES)
    return [m for m in modes if m in ALL_MODES]


def effective_distractor_scope(config: CategoryConfig) -> str:
    scope = (config.practice.distractor_scope if config.practice else None) or "auto"
    return scope if scope in DISTRACTOR_SCOPES else "auto"
