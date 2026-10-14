"""Shared base for every storage-side model.

Null tolerance and losslessness are properties of the base class, not of each
field: unknown keys survive a round-trip (``extra="allow"``) and nothing is
coerced silently into the wrong type.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class LenientModel(BaseModel):
    """Keeps unknown keys, so a file written by a newer version still round-trips."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        str_strip_whitespace=False,
        validate_assignment=True,
    )

    def dumps(self) -> dict[str, Any]:
        """Serialise for a data file.

        ``None`` fields are omitted rather than written as ``null``: a reader treats
        an absent key and a null key identically (PLAN 3, rule 1), so this loses
        nothing and keeps the files readable. Nulls *inside* ``fields``/``extra``
        maps are dict values, not model fields, and are preserved.
        """
        return self.model_dump(mode="json", exclude_none=True, by_alias=True)
