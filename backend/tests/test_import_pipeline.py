"""The import pipeline end to end, with a stand-in provider (PLAN 4)."""

from __future__ import annotations

import json

import pytest

from memo.importers import Importer, UnknownImporter, load_registry, route
from memo.importpipe import run_import
from memo.llm.client import LLMError
from tests.conftest import EXAMPLE_IMPORTERS
from tests.fakes import FakeLLM, as_json

REGISTRY = load_registry(EXAMPLE_IMPORTERS)
KOREAN = REGISTRY.get("korean-textbook-vocab")


def _extraction(fixture_dir):
    return (fixture_dir / "vocab1.extraction.json").read_text(encoding="utf-8")


def test_a_page_becomes_the_expected_data_file(fixture_dir, sample_image, vocab1_raw):
    """Phase 0's acceptance run, minus the network (PLAN 6)."""
    client = FakeLLM([_extraction(fixture_dir)])
    outcome = run_import(
        client,
        KOREAN,
        [sample_image],
        tier="json_schema",
        first_page_number=6,
    )
    produced = outcome.datafile
    assert not outcome.failed_pages
    assert [n.front for n in produced.notes] == [n["front"] for n in vocab1_raw["notes"]]
    assert [n.back for n in produced.notes] == [n["back"] for n in vocab1_raw["notes"]]
    assert produced.source.import_.profile == "korean-textbook-vocab"
    assert produced.source.import_.job_id == outcome.job


def test_the_image_is_sent_inline_with_the_importer_prompt(fixture_dir, sample_image):
    client = FakeLLM([_extraction(fixture_dir)])
    run_import(client, KOREAN, [sample_image], tier="text")
    messages = client.calls[0]["messages"]
    assert any("TWO Korean/English pairs per row" in str(m.content) for m in messages)
    parts = messages[-1].content
    assert any(p.get("type") == "image_url" for p in parts)
    assert parts[-1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_one_failed_page_does_not_lose_the_others(fixture_dir, sample_image):
    client = FakeLLM([LLMError("provider timed out"), _extraction(fixture_dir)])
    outcome = run_import(
        client,
        KOREAN,
        [sample_image, sample_image],
        tier="text",
        first_page_number=6,
    )
    assert [p.number for p in outcome.failed_pages] == [6]
    assert len(outcome.datafile.notes) == 32, "page 7 still made it to review"


@pytest.mark.parametrize("name", ["korean-textbook-vocab", "general"])
def test_every_page_failing_still_yields_a_reviewable_empty_draft(sample_image, name):
    client = FakeLLM([LLMError("nope")])
    outcome = run_import(client, REGISTRY.get(name), [sample_image], tier="text")
    assert outcome.datafile.notes == []
    assert len(outcome.failed_pages) == 1


def test_the_importer_decides_the_note_type(fixture_dir, sample_image):
    client = FakeLLM([_extraction(fixture_dir)])
    outcome = run_import(client, KOREAN, [sample_image], tier="text")
    assert {str(n.type) for n in outcome.datafile.notes} == {"bidirectional"}


def test_typed_instructions_reach_an_extraction_importer_too(fixture_dir, sample_image):
    client = FakeLLM([_extraction(fixture_dir)])
    run_import(client, KOREAN, [sample_image], tier="text", instructions=["Skip the footnotes."])
    assert "Skip the footnotes." in client.calls[0]["messages"][-1].content[0]["text"]


# --- the router -------------------------------------------------------------


def test_the_router_proposes_an_importer_and_says_why(sample_image):
    client = FakeLLM([as_json({"choice": 2, "why": "Korean vocabulary table."})])
    importer, why = route(client, sample_image, registry=REGISTRY, tier="json_schema")
    assert importer.name == REGISTRY.all("image")[1].name == "korean-textbook-vocab"
    assert why == "Korean vocabulary table."


def test_with_only_the_general_reader_there_is_nothing_to_ask(sample_image, tmp_path):
    client = FakeLLM([LLMError("must not be called")])
    importer, why = route(client, sample_image, registry=load_registry(tmp_path / "none"), tier="text")
    assert importer.name == "general" and why is None
    assert client.calls == []


def test_a_router_failure_falls_back_instead_of_stopping_the_import(sample_image):
    client = FakeLLM([LLMError("router is down")])
    importer, why = route(client, sample_image, registry=REGISTRY, tier="text")
    assert importer.name == "general" and why is None


def test_an_out_of_range_choice_falls_back(sample_image):
    client = FakeLLM([as_json({"choice": 99, "why": "confident nonsense"})])
    importer, _ = route(client, sample_image, registry=REGISTRY, tier="json_schema")
    assert importer.name == "general"


def test_no_name_is_the_general_reader_and_an_unknown_name_is_an_error():
    assert REGISTRY.get(None).name == "general"
    assert REGISTRY.get("generic").name == "general", "the old fallback's name still works"
    with pytest.raises(UnknownImporter, match="does-not-exist"):
        REGISTRY.get("does-not-exist")


def test_every_extraction_importer_ships_a_valid_example():
    extraction = [i for i in REGISTRY.all() if isinstance(i, Importer)]
    assert extraction, "the examples folder should hold at least one"
    for importer in extraction:
        assert importer.example is not None, f"{importer.name} has no example for the text tier"
        importer.extraction_model.model_validate(json.loads(json.dumps(importer.example)))


# --- a chapter over several days (PLAN 6, phase 2) --------------------------


def test_a_second_upload_can_be_added_to_the_file_the_first_made(session, vocab1):
    from memo.collection.store import append_datafile, export_datafile, store_datafile
    from memo.models.datafile import DataFile, Group, ImportInfo, Note, NoteType, Source

    first = store_datafile(session, vocab1, category_path="korean/book1/02-introduction")
    before = len(first.notes)

    second = DataFile(
        default_type=NoteType.BIDIRECTIONAL,
        source=Source(kind="image", files=["raw/vocab2.jpg"], page=7, import_=ImportInfo(model="m")),
        groups=[Group(id="countries", label={"en": "Countries"}), Group(id="food", label={"en": "Food"})],
        notes=[
            Note(front="김치", back="kimchi", group="food"),
            Note(front="일본", back="Japan", group="countries"),
        ],
    )
    added = append_datafile(session, first, second)

    assert len(first.notes) == before + 2
    assert [row.position for row in added] == [before, before + 1]
    assert sorted(g.key for g in first.groups) == sorted({*(g.id for g in vocab1.groups), "food"}), (
        "a group the file already had is joined, not repeated"
    )
    countries = next(g for g in first.groups if g.key == "countries")
    assert added[1].group_id == countries.id
    assert all(len(row.cards) == 2 for row in added), "the file's own default decides the cards"

    exported = export_datafile(session, first.id)
    assert [n.front for n in exported.notes][-2:] == ["김치", "일본"]
    assert exported.source is not None
    assert "raw/vocab2.jpg" in (exported.source.files or [])
    assert exported.source.page == 6, "the first page stays the file's page"
    appended = (exported.source.extra or {})["appended"]
    assert [a["page"] for a in appended] == [7], "the second import's provenance is kept beside it"
