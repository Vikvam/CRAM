"""Data-file serialisation.

One canonical spelling on disk (2-space indent, unescaped Unicode, trailing
newline) so that export → import → export is byte-identical and a diff of two
exports shows content changes only.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from memo.models.datafile import DataFile, load_datafile


def dump_json(datafile: DataFile) -> str:
    """Canonical text for a data file."""
    return json.dumps(datafile.dumps(), ensure_ascii=False, indent=2) + "\n"


def load_json(text: str | bytes) -> DataFile:
    return load_datafile(text)


def read_datafile(path: str | Path) -> DataFile:
    return load_json(Path(path).read_text(encoding="utf-8"))


def write_datafile(path: str | Path, datafile: DataFile) -> Path:
    """Write atomically: a crash mid-write must not leave half a collection."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dump_json(datafile))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def round_trip(datafile: DataFile) -> DataFile:
    """Serialise and parse again — the identity the format has to satisfy."""
    return load_json(dump_json(datafile))
