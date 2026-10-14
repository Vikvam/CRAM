"""The three provider tiers all end at one validated object (PLAN 3.6)."""

from __future__ import annotations

import pytest
from pydantic import Field

from memo.llm.client import ChatMessage, LLMError
from memo.llm.jsonblock import extract_json_object
from memo.llm.probe import StructuredOutput, probe
from memo.llm.structured import StructuredError, complete_structured
from memo.models.extraction import StrictModel, strict_json_schema
from tests.fakes import FakeLLM, as_json


class Toy(StrictModel):
    name: str = Field(description="a name")
    count: int = Field(description="a number")


ASK = [ChatMessage(role="user", content="go")]


# --- schema generation ------------------------------------------------------


def test_the_strict_schema_requires_every_property_and_forbids_extras():
    schema = strict_json_schema(Toy)
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == ["count", "name"]


def test_nested_objects_are_tightened_too():
    from memo.models.extraction import ExtractionResult

    item = strict_json_schema(ExtractionResult)["$defs"]["ExtractedItem"]
    assert item["additionalProperties"] is False
    assert "note" in item["required"], "strict mode spells absence as null, not omission"


# --- the tiers --------------------------------------------------------------


def test_tier_json_schema_sends_the_schema_and_parses_directly():
    client = FakeLLM([as_json({"name": "a", "count": 1})])
    result = complete_structured(client, Toy, ASK, tier=StructuredOutput.JSON_SCHEMA)
    assert result.count == 1
    assert client.calls[0]["response_format"]["type"] == "json_schema"
    assert client.calls[0]["response_format"]["json_schema"]["strict"] is True


def test_tier_json_object_puts_the_schema_in_the_prompt_instead():
    client = FakeLLM([as_json({"name": "a", "count": 1})])
    complete_structured(client, Toy, ASK, tier=StructuredOutput.JSON_OBJECT)
    assert client.calls[0]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in client.calls[0]["messages"][0].content


def test_tier_text_sends_no_response_format_and_digs_the_json_out():
    client = FakeLLM(['Sure!\n```json\n{"name": "a", "count": 1}\n```\nHope that helps.'])
    result = complete_structured(client, Toy, ASK, tier=StructuredOutput.TEXT)
    assert result.name == "a"
    assert client.calls[0]["response_format"] is None


def test_an_example_is_included_when_there_is_no_schema_enforcement():
    client = FakeLLM([as_json({"name": "a", "count": 1})])
    complete_structured(client, Toy, ASK, tier="text", example={"name": "x", "count": 0})
    assert "unrelated) example" in client.calls[0]["messages"][0].content


# --- the repair loop --------------------------------------------------------


def test_invalid_output_is_repaired_by_handing_back_the_errors():
    client = FakeLLM([as_json({"name": "a"}), as_json({"name": "a", "count": 2})])
    result = complete_structured(client, Toy, ASK, tier="text")
    assert result.count == 2
    assert len(client.calls) == 2
    assert "did not validate" in client.calls[1]["messages"][-1].content


def test_the_repair_loop_gives_up_rather_than_looping():
    client = FakeLLM([as_json({"name": "a"})])
    with pytest.raises(StructuredError):
        complete_structured(client, Toy, ASK, tier="text", max_repairs=2)
    assert len(client.calls) == 3, "the original call plus two repairs"


def test_a_schema_tier_failure_is_not_retried():
    """Tier 1 promised the schema; asking again would only cost money."""
    client = FakeLLM([as_json({"name": "a"})])
    with pytest.raises(StructuredError):
        complete_structured(client, Toy, ASK, tier=StructuredOutput.JSON_SCHEMA)
    assert len(client.calls) == 1


# --- the probe --------------------------------------------------------------


def test_the_probe_picks_the_strictest_tier_that_works():
    client = FakeLLM([as_json({"ok": True})])
    assert probe(client).structured_output is StructuredOutput.JSON_SCHEMA


def test_the_probe_falls_back_when_the_schema_call_is_refused():
    client = FakeLLM([LLMError("400 unsupported response_format"), as_json({"ok": True})])
    capabilities = probe(client)
    assert capabilities.structured_output is StructuredOutput.JSON_OBJECT
    assert capabilities.notes, "the refusal is recorded, not swallowed"


def test_the_probe_ends_at_text_when_nothing_structured_works():
    client = FakeLLM([LLMError("no"), LLMError("no"), 'here you go: {"ok": true}'])
    assert probe(client).structured_output is StructuredOutput.TEXT


def test_vision_is_probed_only_when_asked(tmp_path):
    image = tmp_path / "x.jpg"
    image.write_bytes(b"\xff\xd8\xff")
    client = FakeLLM([as_json({"ok": True}), "a cat"])
    assert probe(client, image=image).vision is True
    assert probe(FakeLLM([as_json({"ok": True})])).vision is False


# --- digging JSON out of prose ---------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Here you go:\n{"a": 1}\nAnything else?',
        '{"a": 1} ',
    ],
)
def test_json_is_found_however_it_is_wrapped(text):
    assert extract_json_object(text) == {"a": 1}


def test_braces_inside_strings_do_not_confuse_the_scan():
    assert extract_json_object('note: {"a": "}{", "b": 2} done') == {"a": "}{", "b": 2}


def test_a_response_with_no_json_raises():
    with pytest.raises(ValueError, match="no JSON object"):
        extract_json_object("I'm afraid I can't do that.")
