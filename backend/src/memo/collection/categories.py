"""The category tree.

``path`` is materialised (``korean/book1/02-introduction``) so "everything in
this subtree" — the query the learn views live on — is a single ``LIKE``.
"""

from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from memo.db.models import Category, DataFileRow
from memo.models.category import (
    ALL_MODES,
    DISTRACTOR_SCOPES,
    CategoryConfig,
    PracticeSettings,
    inherit,
)
from memo.models.ids import new_id

#: "the caller said nothing", which is not the same as "the caller said null".
UNSET = object()

_SLUG_STRIP = re.compile(r"[^\w.-]+", re.UNICODE)


def slugify(value: str) -> str:
    """Keep it readable and Unicode-friendly; this is a path segment, not an id."""
    slug = _SLUG_STRIP.sub("-", value.strip().lower()).strip("-")
    return slug or "untitled"


def split_path(path: str) -> list[str]:
    return [segment for segment in path.strip("/").split("/") if segment]


def ensure_category(session: Session, path: str, *, label: dict[str, str] | None = None) -> Category:
    """Create every missing node on ``path`` and return the leaf."""
    parent: Category | None = None
    parent_path = ""
    node: Category | None = None
    for segment in split_path(path):
        slug = slugify(segment)
        full = f"{parent_path}/{slug}" if parent_path else slug
        node = session.scalar(
            select(Category).where(
                Category.parent_id == (parent.id if parent else None), Category.slug == slug
            )
        )
        if node is None:
            node = Category(id=new_id("cat"), parent_id=parent.id if parent else None, slug=slug, path=full)
            session.add(node)
            session.flush()
        parent, parent_path = node, full
    if node is None:
        raise ValueError("category path is empty")
    if label:
        node.label = {**(node.label or {}), **label}
    return node


def subtree(session: Session, category: Category) -> list[Category]:
    """``category`` first, then everything under it, shallowest first."""
    rows = session.scalars(
        select(Category)
        .where(or_(Category.path == category.path, Category.path.like(f"{category.path}/%")))
        .order_by(Category.path)
    ).all()
    return list(rows)


def _sibling(session: Session, parent_id: str | None, slug: str, *, ignore: str) -> Category | None:
    return session.scalar(
        select(Category).where(Category.parent_id == parent_id, Category.slug == slug, Category.id != ignore)
    )


def _repath(session: Session, category: Category, new_path: str) -> None:
    """Rewrite the node's path and its descendants'. Progress is keyed on note IDs,
    never on paths (PLAN 3.4), so nothing else has to move."""
    old = category.path
    for node in subtree(session, category):
        node.path = new_path + node.path[len(old) :]
    session.flush()


def update_practice(
    session: Session,
    category: Category,
    *,
    modes: list[str] | None | object = UNSET,
    distractor_scope: str | None | object = UNSET,
) -> Category:
    """This category's own practice settings; ``None`` clears one and goes back
    to inheriting it from the parent (PLAN 3.3).

    Only the keys given are touched, so setting the distractor scope here does
    not silently pin the modes as well.
    """
    config = CategoryConfig.model_validate(category.config) if category.config else CategoryConfig()
    practice = config.practice.model_copy() if config.practice else PracticeSettings()

    if modes is not UNSET:
        if modes is None:
            practice.modes = None
        else:
            unknown = [m for m in modes if m not in ALL_MODES]
            if unknown:
                raise ValueError(f"no such practice mode: {', '.join(sorted(unknown))}")
            chosen = [m for m in ALL_MODES if m in modes]  # always in UI order
            if not chosen:
                raise ValueError("a category has to allow at least one practice mode")
            practice.modes = chosen

    if distractor_scope is not UNSET:
        if distractor_scope is not None and distractor_scope not in DISTRACTOR_SCOPES:
            raise ValueError(f"no such distractor scope: {distractor_scope}")
        practice.distractor_scope = distractor_scope  # type: ignore[assignment]

    # An empty block is no block: the category simply inherits again.
    config.practice = practice if practice.model_dump(exclude_none=True) else None
    category.config = config.model_dump(mode="json", exclude_none=True, by_alias=True)
    session.flush()
    return category


def rename_category(
    session: Session, category: Category, *, slug: str | None = None, label: dict[str, str] | None = None
) -> Category:
    """Rename a node. ``slug`` changes the path of the whole branch below it."""
    if label is not None:
        category.label = label or None
    if slug is not None:
        new_slug = slugify(slug)
        if new_slug != category.slug:
            if _sibling(session, category.parent_id, new_slug, ignore=category.id):
                raise ValueError(f"a sibling category is already called {new_slug!r}")
            parent = session.get(Category, category.parent_id) if category.parent_id else None
            category.slug = new_slug
            _repath(session, category, f"{parent.path}/{new_slug}" if parent else new_slug)
    session.flush()
    return category


def move_category(session: Session, category: Category, parent_id: str | None) -> Category:
    """Re-parent a node (``None`` makes it a root), carrying its branch with it."""
    if parent_id == category.parent_id:
        return category
    parent = None
    if parent_id is not None:
        parent = session.get(Category, parent_id)
        if parent is None:
            raise ValueError(f"no such category: {parent_id}")
        if parent.id == category.id or parent.path.startswith(f"{category.path}/"):
            raise ValueError("a category cannot be moved inside itself")
    if _sibling(session, parent_id, category.slug, ignore=category.id):
        raise ValueError(f"a sibling category is already called {category.slug!r}")
    category.parent_id = parent_id
    _repath(session, category, f"{parent.path}/{category.slug}" if parent else category.slug)
    return category


def delete_category(session: Session, category: Category) -> None:
    """Only ever an empty node: with files or children it would take notes with it."""
    if session.scalar(select(Category.id).where(Category.parent_id == category.id)):
        raise ValueError("this category has sub-categories; move or delete them first")
    if session.scalar(select(DataFileRow.id).where(DataFileRow.category_id == category.id)):
        raise ValueError("this category still has data files; archive or move them first")
    session.delete(category)
    session.flush()


def ancestors(session: Session, category: Category) -> list[Category]:
    """Root first, ``category`` last."""
    chain: list[Category] = []
    node: Category | None = category
    while node is not None:
        chain.append(node)
        node = session.get(Category, node.parent_id) if node.parent_id else None
    return list(reversed(chain))


def category_config(session: Session, category: Category) -> CategoryConfig:
    """Settings with inheritance applied down the tree (PLAN 3.3)."""
    resolved = CategoryConfig()
    for node in ancestors(session, category):
        own = CategoryConfig.model_validate(node.config) if node.config else None
        resolved = inherit(own, resolved)
    return resolved
