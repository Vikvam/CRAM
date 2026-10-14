"""Importers that live on one machine, not in the app (``importers.local/``).

A reader written for one textbook is worth keeping, and worth keeping out of a
public repository. Each file in the folder is one importer:

- ``*.toml`` — a spec, the documented way. ``kind = "extraction"`` asks for the
  strict extraction shape and needs an ``example``; ``kind = "datafile"`` asks for
  a whole data file, as the general reader does. The prompt is ``prompt = '''…'''``
  or ``prompt_file = "name.md"`` beside the spec. See
  ``examples/importers/korean-textbook-vocab.toml``.
- ``*.py`` — a module defining ``IMPORTER`` (or a list, ``IMPORTERS``), for
  anything a spec cannot say. It runs as code, so the folder is only ever one
  you wrote yourself.

A file that does not load is skipped and reported, never fatal: one typo should
not stop the server or the other importers.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from memo.importers.base import LOCAL, AnyImporter, DatafileImporter, Importer
from memo.models.datafile import NoteType
from memo.models.extraction import PROMPT_VERSION, ExtractionResult

KINDS = ("extraction", "datafile")


class SpecError(ValueError):
    """A local importer file that cannot be used, and why."""


def load_folder(folder: Path | None) -> tuple[list[AnyImporter], list[str]]:
    """Every importer in ``folder``, in name order, and one line per file that failed."""
    if folder is None or not folder.is_dir():
        return [], []
    importers: list[AnyImporter] = []
    errors: list[str] = []
    for path in sorted(folder.iterdir()):
        if path.name.startswith((".", "_")) or path.suffix not in (".toml", ".py"):
            continue
        try:
            found = load_spec(path) if path.suffix == ".toml" else load_module(path)
        except (SpecError, OSError, ValueError, SyntaxError, ImportError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        importers.extend(dataclasses.replace(i, origin=LOCAL) for i in found)
    return importers, errors


def load_spec(path: Path) -> list[AnyImporter]:
    try:
        spec = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f"not valid TOML: {exc}") from None

    kind = spec.get("kind", "extraction")
    if kind not in KINDS:
        raise SpecError(f"kind must be one of {', '.join(KINDS)}, not {kind!r}")
    name = _required(spec, "name")
    description = _required(spec, "description")
    prompt = _prompt(spec, path)
    common: dict[str, Any] = {
        "name": name,
        "description": description,
        "front_lang": spec.get("front_lang"),
        "back_lang": spec.get("back_lang"),
        "kinds": tuple(spec.get("kinds") or ("image", "pdf")),
    }
    default_type = spec.get("default_type")
    if default_type is not None:
        try:
            common["default_type"] = NoteType(default_type)
        except ValueError:
            raise SpecError(
                f"default_type must be bidirectional or directional, not {default_type!r}"
            ) from None

    if kind == "datafile":
        return [DatafileImporter(prompt=prompt, prompt_version=int(spec.get("prompt_version", 1)), **common)]

    example = _example(spec, path)
    try:
        ExtractionResult.model_validate(example)
    except ValueError as exc:
        raise SpecError(f"the example is not a valid extraction: {exc}") from None
    return [
        Importer(
            system_prompt=prompt,
            example=example,
            prompt_version=int(spec.get("prompt_version", PROMPT_VERSION)),
            **common,
        )
    ]


def load_module(path: Path) -> list[AnyImporter]:
    module_name = f"memo_local_importer_{path.stem.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SpecError("cannot be loaded as a module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    found = getattr(module, "IMPORTERS", None) or [getattr(module, "IMPORTER", None)]
    found = [i for i in found if i is not None]
    if not found:
        raise SpecError("defines neither IMPORTER nor IMPORTERS")
    for importer in found:
        if not isinstance(importer, Importer | DatafileImporter):
            raise SpecError(f"{importer!r} is not an Importer or a DatafileImporter")
    return found


def _required(spec: dict[str, Any], key: str) -> str:
    value = spec.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SpecError(f"needs a {key}")
    return value.strip()


def _prompt(spec: dict[str, Any], path: Path) -> str:
    if "prompt_file" in spec:
        return (path.parent / spec["prompt_file"]).read_text(encoding="utf-8")
    _required(spec, "prompt")
    return spec["prompt"]  # as written: a prompt is sent exactly as it is


def _example(spec: dict[str, Any], path: Path) -> dict[str, Any]:
    """An extraction example, as JSON: TOML has no null, and extractions are full of them."""
    if "example_file" in spec:
        raw = (path.parent / spec["example_file"]).read_text(encoding="utf-8")
    elif isinstance(spec.get("example"), str):
        raw = spec["example"]
    else:
        raise SpecError("an extraction importer needs an example (a JSON string, or example_file)")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise SpecError(f"the example is not valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise SpecError("the example must be a JSON object")
    return value
