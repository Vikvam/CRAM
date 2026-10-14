"""Pull JSON objects out of whatever the model actually said.

Used where there is no guarantee of anything — prose before the JSON, a ```json
fence around it, or a trailing apology.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json_object(text: str) -> dict[str, Any]:
    for candidate in _candidates(text):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no JSON object found in the response")


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Every object the reply holds: each fenced block, or failing that, each bare one."""
    fenced = [value for value in map(_parse, (m.group(1).strip() for m in _FENCE.finditer(text))) if value]
    if fenced:
        return fenced
    whole = _parse(text.strip())
    if whole:
        return [whole]
    found, start = [], text.find("{")
    while start != -1:
        piece = next(_balanced(text, start), None)
        if piece is None:
            break
        value = _parse(piece)
        if value:
            found.append(value)
            start = text.find("{", start + len(piece))
        else:
            start = text.find("{", start + 1)
    if not found:
        raise ValueError("no JSON object found in the response")
    return found


def _parse(candidate: str) -> dict[str, Any] | None:
    try:
        value = json.loads(candidate)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _candidates(text: str):
    stripped = text.strip()
    yield stripped
    for match in _FENCE.finditer(text):
        yield match.group(1).strip()
    start = stripped.find("{")
    if start != -1:
        yield from _balanced(stripped, start)


def _balanced(text: str, start: int):
    """Scan for a brace-balanced slice, ignoring braces inside strings."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                yield text[start : index + 1]
                return
