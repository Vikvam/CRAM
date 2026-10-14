"""Which importers exist here: the built-in general reader, plus the local folder.

Read from disk on every call, which costs a directory listing, so a spec edited
in ``importers.local/`` counts from the next upload, without a restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from memo.importers.base import AnyImporter
from memo.importers.general import IMPORTER as GENERAL
from memo.importers.local import load_folder

BUILTINS: tuple[AnyImporter, ...] = (GENERAL,)
FALLBACK = GENERAL.name
#: Names that used to exist, so an old job can still be retried.
ALIASES = {"generic": GENERAL.name}


class UnknownImporter(ValueError):
    """A name this install has no importer for."""


@dataclass(slots=True)
class Registry:
    importers: dict[str, AnyImporter] = field(default_factory=dict)
    #: One line per local file that could not be used.
    errors: list[str] = field(default_factory=list)

    def get(self, name: str | None) -> AnyImporter:
        """No name means the fallback. A name that is not here is an error, not a guess."""
        if not name:
            return self.importers[FALLBACK]
        name = ALIASES.get(name, name)
        try:
            return self.importers[name]
        except KeyError:
            known = ", ".join(self.importers)
            raise UnknownImporter(f"no importer called {name!r} here (there is: {known})") from None

    def all(self, kind: str | None = None) -> list[AnyImporter]:
        importers = list(self.importers.values())
        return importers if kind is None else [i for i in importers if kind in i.kinds]


def load_registry(folder: Path | None) -> Registry:
    registry = Registry(importers={i.name: i for i in BUILTINS})
    local, registry.errors = load_folder(folder)
    for importer in local:
        if importer.name in registry.importers or importer.name in ALIASES:
            registry.errors.append(f"{importer.name}: that name is taken")
            continue
        registry.importers[importer.name] = importer
    return registry
