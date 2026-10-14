"""The docs say things the code can contradict, and examples are what rots first.

Every data-file example in ``docs/`` must load, survive the upload path and come
out of the audit clean, because the LLM prompt hands them to a model as the thing
to imitate. Every ``memo <command>`` the docs mention must exist.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import typer.main

from memo import cli
from memo.collection import store_datafile
from memo.collection.audit import audit
from memo.importers.files import read_json
from memo.importers.general import PROMPT
from memo.models.category import ALL_MODES
from memo.models.datafile import FORMAT, load_datafile

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
EXAMPLE_DOCS = [DOCS / "llm-prompt.md", DOCS / "format.md"]
COMMAND_DOCS = [ROOT / "README.md", *sorted(DOCS.glob("*.md")), ROOT / "backend" / "README.md"]

_JSON_BLOCK = re.compile(r"^```json\n(.*?)^```", re.DOTALL | re.MULTILINE)
#: Only as code — in a backtick span or after ``uv run`` — since prose says "memo" for the app.
_COMMAND = re.compile(r"(?:uv run |`)memo ([a-z][a-z-]+)")


def _examples() -> list[tuple[str, dict]]:
    found = []
    for path in EXAMPLE_DOCS:
        for i, block in enumerate(_JSON_BLOCK.findall(path.read_text(encoding="utf-8"))):
            raw = json.loads(block)
            if isinstance(raw, dict) and raw.get("format") == FORMAT:
                found.append((f"{path.name}#{i}", raw))
    return found


EXAMPLES = _examples()


def test_the_docs_have_examples_to_check():
    names = {name.split("#")[0] for name, _ in EXAMPLES}
    assert names == {p.name for p in EXAMPLE_DOCS}


@pytest.mark.parametrize(("name", "raw"), EXAMPLES, ids=[name for name, _ in EXAMPLES])
def test_an_example_is_a_good_data_file(name, raw, tmp_path, session):
    datafile = load_datafile(raw)
    assert datafile.notes, "an example with no notes teaches nothing"
    assert not datafile.flagged(), "every example note should be practisable"
    assert all(note.id is None for note in datafile.notes), "the prompt says not to write ids"

    groups = {group.id for group in datafile.groups}
    for note in datafile.notes:
        assert note.group is None or note.group in groups, f"{note.front}: undefined group {note.group}"
        assert set(note.modes or []) <= set(ALL_MODES), f"{note.front}: unknown mode in {note.modes}"

    # The route an upload takes: the reader keeps every field and blanks the ids.
    path = tmp_path / "example.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    uploaded = read_json(path)
    assert [n.model_dump(exclude={"id", "status"}) for n in uploaded.notes] == [
        n.model_dump(exclude={"id", "status"}) for n in datafile.notes
    ]

    # An example the audit objects to would teach the model the defect.
    store_datafile(session, uploaded, category_path="docs/example")
    report = audit(session)
    assert report.clean, f"{name}: collisions={report.collisions} one_sided={report.one_sided}"


def test_every_command_the_docs_mention_exists():
    commands = set(typer.main.get_command(cli.app).commands)
    for path in COMMAND_DOCS:
        mentioned = set(_COMMAND.findall(path.read_text(encoding="utf-8")))
        missing = sorted(mentioned - commands)
        assert not missing, f"{path.relative_to(ROOT)}: no such command {missing}"


def test_the_app_reads_photos_with_the_prompt_the_doc_gives_people():
    doc = (DOCS / "llm-prompt.md").read_text(encoding="utf-8")
    block = re.search(r"^## The prompt\n\n````text\n(.*?)^````", doc, re.DOTALL | re.MULTILINE)
    assert block, "llm-prompt.md lost its prompt block"
    assert block.group(1) == PROMPT, (
        "docs/llm-prompt.md and src/memo/importers/prompts/general.md differ: change both, or copy one over"
    )
    assert PROMPT.rstrip().endswith("--- My instructions ---"), "the app fills in what comes after it"
