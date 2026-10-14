"""The general reader: the prompt from docs/llm-prompt.md, answered in data files."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from memo.api import create_app
from memo.config import Settings
from memo.importers import DatafileImporter, load_registry
from memo.importers.general import IMPORTER as GENERAL
from memo.importers.general import PROMPT
from memo.importers.local import load_folder
from memo.importpipe import run_import
from memo.llm.client import LLMError
from tests.conftest import EXAMPLE_IMPORTERS
from tests.fakes import FakeLLM

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
_BLOCK = re.compile(r"^```json\n(.*?)^```", re.DOTALL | re.MULTILINE)
#: The two worked examples in the prompt: what a good answer looks like.
VOCAB, OHM = (json.loads(b) for b in _BLOCK.findall((ROOT / "docs" / "llm-prompt.md").read_text("utf-8")))


def fenced(*objects: dict, before: str = "", after: str = "") -> str:
    blocks = "\n\n".join(f"```json\n{json.dumps(o, ensure_ascii=False, indent=2)}\n```" for o in objects)
    return f"{before}{blocks}{after}"


def read(answers, paths, **kwargs):
    client = FakeLLM(answers)
    return client, run_import(client, GENERAL, paths, tier=kwargs.pop("tier", "text"), **kwargs)


def test_an_answer_like_the_prompts_example_becomes_the_draft(sample_image):
    client, outcome = read([fenced(VOCAB)], [sample_image])
    draft = outcome.datafile
    assert not outcome.failed_pages
    assert [n.front for n in draft.notes] == [n["front"] for n in VOCAB["notes"]]
    assert (
        draft.title == VOCAB["title"]
        and draft.front_lang == "de"
        and str(draft.default_type) == "bidirectional"
    )
    assert [g.id for g in draft.groups] == ["verbs", "transport"]
    assert draft.notes[0].accept.back == ["to go", "to walk", "go", "walk"]
    assert draft.notes[0].fields == {"past participle": "gegangen"}
    assert draft.source.context == VOCAB["source"]["context"]


def test_what_the_model_has_no_say_in_is_replaced(sample_image):
    answer = json.loads(json.dumps(OHM))
    answer["id"] = "df_made_up"
    answer["source"]["import"] = {"profile": "me", "model": "me"}
    answer["notes"][0] |= {"id": "n_made_up", "status": "confirmed", "suspended": True}
    _, outcome = read([fenced(answer)], [sample_image])
    draft = outcome.datafile
    assert draft.id != "df_made_up" and draft.id.startswith("df_")
    assert all(n.id.startswith("n_") and n.id != "n_made_up" for n in draft.notes)
    assert {str(n.status) for n in draft.notes} == {"unverified"}
    assert draft.notes[0].suspended is None
    info = draft.source.import_
    assert (info.profile, info.model, info.job_id) == ("general", "fake-model", outcome.job)
    assert len(info.extra["prompt_sha"]) == 12
    assert draft.source.kind == "image"


def test_the_prompt_is_sent_as_written_with_the_instructions_after_it(sample_image):
    client, _ = read([fenced(VOCAB)], [sample_image], instructions=["Only the verbs."])
    [message] = client.calls[0]["messages"]
    assert message.role == "user", "no system prompt: the same thing a person pastes into a chat"
    text, image = message.content
    assert text["text"].startswith(PROMPT.rstrip("\n") + "\n")
    after = text["text"].removeprefix(PROMPT.rstrip("\n") + "\n").splitlines()
    assert after == ["This is one photo.", "Only the verbs."]
    assert image["type"] == "image_url"


def test_page_lines_say_which_photo_and_the_printed_page_when_known(sample_image):
    client, outcome = read([fenced(OHM)], [sample_image, sample_image], first_page_number=12)
    lines = [c["messages"][0].content[0]["text"].splitlines()[-1] for c in client.calls]
    assert lines == [
        "This is photo 1 of 2 in one upload. It is printed page 12.",
        "This is photo 2 of 2 in one upload. It is printed page 13.",
    ]
    pages = {n.page for n in outcome.datafile.notes}
    assert pages == {12}, "the second page repeated the first, so its notes were dropped as overlap"


def test_without_a_printed_page_no_page_is_made_up(sample_image):
    _, outcome = read([fenced(OHM)], [sample_image], first_page_number=None)
    assert {n.page for n in outcome.datafile.notes} == {None}
    assert outcome.datafile.source.page is None


def test_it_is_plain_text_whatever_the_provider_can_do(sample_image):
    client, _ = read([fenced(OHM)], [sample_image], tier="json_schema")
    assert client.calls[0]["response_format"] is None


def test_prose_around_the_blocks_is_ignored(sample_image):
    _, outcome = read(
        [fenced(OHM, before="Here you go:\n\n", after="\n\nSorry if I missed any.")], [sample_image]
    )
    assert len(outcome.datafile.notes) == len(OHM["notes"])


def test_two_objects_on_one_page_are_one_draft(sample_image):
    _, outcome = read([fenced(VOCAB, OHM)], [sample_image])
    draft = outcome.datafile
    assert len(draft.notes) == len(VOCAB["notes"]) + len(OHM["notes"])
    assert [g.id for g in draft.groups] == ["verbs", "transport", "ohm", "units"]
    assert draft.title == VOCAB["title"], "the first object names the file"
    ohm = [n for n in draft.notes if n.group == "ohm"]
    assert {str(n.type) for n in ohm} == {"directional"}, "a different type is kept on its own notes"


def test_a_broken_answer_is_handed_back_to_be_fixed(sample_image):
    client, outcome = read(['```json\n{"notes": [ {"front": "a",, }]}\n```', fenced(OHM)], [sample_image])
    assert not outcome.failed_pages
    assert len(client.calls) == 2
    retry = client.calls[1]["messages"]
    assert retry[1].role == "assistant" and "could not be used" in retry[2].content


def test_an_answer_with_no_notes_is_not_accepted(sample_image):
    client, outcome = read([fenced({"format": "memo.datafile", "version": 1, "notes": []})], [sample_image])
    assert len(client.calls) == 3, "two repairs, then it gives up"
    assert "no notes with a front or a back" in outcome.failed_pages[0].error


def test_one_failed_page_does_not_lose_the_others(sample_image):
    _, outcome = read([LLMError("timed out"), fenced(OHM)], [sample_image, sample_image], first_page_number=1)
    assert [p.number for p in outcome.failed_pages] == [1]
    assert len(outcome.datafile.notes) == len(OHM["notes"])


def test_doubt_and_gaps_reach_the_review_screen(sample_image):
    answer = json.loads(json.dumps(OHM))
    answer["notes"][0]["confidence"] = 0.4
    answer["notes"][1]["back"] = None
    answer["notes"][2]["confidence"] = 7
    answer["notes"][3]["group"] = "never-defined"
    _, outcome = read([fenced(answer)], [sample_image])
    notes = outcome.datafile.notes
    assert notes[0].confidence == 0.4
    assert notes[1] in outcome.datafile.flagged()
    assert notes[2].confidence == 1.0
    assert notes[3].group is None


# --- through the app --------------------------------------------------------


@pytest.fixture
def app_with(tmp_path):
    def make(answer: str, folder=EXAMPLE_IMPORTERS):
        client = FakeLLM(lambda m: answer)
        settings = Settings(var_dir=tmp_path / "var", data_dir=tmp_path / "data", importers_dir=folder)
        return TestClient(create_app(settings, client_factory=lambda: client)), client

    return make


def _upload(api, sample_image, **data):
    category = api.post("/api/categories", json={"path": "physics"}).json()
    with sample_image.open("rb") as handle:
        return api.post(
            "/api/imports",
            data={"category_id": category["id"], **data},
            files=[("files", ("page.jpg", handle, "image/jpeg"))],
        )


def test_a_photo_with_no_reader_named_on_a_fresh_install_uses_the_general_one(
    app_with, sample_image, tmp_path
):
    api, client = app_with(fenced(OHM), folder=tmp_path / "no-local-importers")
    response = _upload(api, sample_image, instructions="  Ask about units only.  ")
    assert response.status_code == 202, response.text
    job = api.get(f"/api/imports/{response.json()['id']}").json()
    assert job["status"] == "review" and job["importer"] == "general"
    assert len(client.calls) == 1, "nothing to choose between, so no router call"
    lines = client.calls[0]["messages"][0].content[0]["text"].splitlines()
    assert lines[-3:] == [
        "This is one photo.",
        'These cards go into the category "physics".',
        "Ask about units only.",
    ]


def test_what_the_category_says_becomes_a_default_for_the_model(session):
    from memo.collection.categories import ensure_category
    from memo.importers.local import load_spec
    from memo.importpipe.jobs import _category_lines, instruction_lines

    root = ensure_category(session, "german")
    root.config = {"front_lang": "de", "back_lang": "en", "default_type": "bidirectional"}
    lesson = ensure_category(session, "german/a1")
    hints = _category_lines(session, lesson)
    assert hints == [
        'These cards go into the category "german/a1".',
        'Unless the material says otherwise, use front_lang "de" and back_lang "en".',
        'Unless the material calls for the other, use default_type "bidirectional".',
    ]
    assert instruction_lines(GENERAL, hints, "Typed.") == [*hints, "Typed."]
    [korean] = load_spec(EXAMPLE_IMPORTERS / "korean-textbook-vocab.toml")
    assert instruction_lines(korean, hints, "Typed.") == ["Typed."], "it knows its languages already"


def test_naming_a_reader_that_is_not_installed_is_refused(app_with, sample_image):
    api, _ = app_with(fenced(OHM))
    response = _upload(api, sample_image, importer="nope")
    assert response.status_code == 400
    assert "no importer called 'nope'" in response.json()["detail"]


def test_retrying_a_job_whose_reader_was_removed_fails_visibly(app_with, sample_image, tmp_path):
    folder = tmp_path / "local"
    folder.mkdir()
    (folder / "mine.toml").write_text(
        (EXAMPLE_IMPORTERS / "korean-textbook-vocab.toml").read_text("utf-8"), "utf-8"
    )
    api, _ = app_with("not json at all", folder=folder)
    job = _upload(api, sample_image, importer="korean-textbook-vocab").json()
    (folder / "mine.toml").unlink()
    api.post(f"/api/imports/{job['id']}/retry")
    after = api.get(f"/api/imports/{job['id']}").json()
    assert after["status"] == "failed"
    assert "no importer called 'korean-textbook-vocab'" in after["error"]


def test_the_importer_list_says_where_each_one_comes_from(app_with):
    api, _ = app_with("")
    listed = {i["name"]: i["origin"] for i in api.get("/api/importers").json()}
    assert listed == {"general": "builtin", "korean-textbook-vocab": "local"}


# --- local importers --------------------------------------------------------


def test_a_datafile_spec_and_a_module_both_load(tmp_path):
    (tmp_path / "glossary.toml").write_text(
        'kind = "datafile"\nname = "glossary"\ndescription = "A glossary page."\n'
        'default_type = "directional"\nprompt_file = "glossary.md"\n',
        encoding="utf-8",
    )
    (tmp_path / "glossary.md").write_text("Read the glossary.\n\n--- My instructions ---\n", encoding="utf-8")
    (tmp_path / "custom.py").write_text(
        "from memo.importers import DatafileImporter\n"
        "IMPORTER = DatafileImporter(name='custom', description='Code.', prompt='Go.')\n",
        encoding="utf-8",
    )
    importers, errors = load_folder(tmp_path)
    assert errors == []
    by_name = {i.name: i for i in importers}
    assert set(by_name) == {"glossary", "custom"}
    assert isinstance(by_name["glossary"], DatafileImporter)
    assert by_name["glossary"].prompt == "Read the glossary.\n\n--- My instructions ---\n"
    assert {i.origin for i in importers} == {"local"}


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("name = ", "not valid TOML"),
        ('name = "x"\n', "needs a description"),
        ('kind = "magic"\nname = "x"\ndescription = "d"\nprompt = "p"\n', "kind must be one of"),
        ('name = "x"\ndescription = "d"\nprompt = "p"\n', "needs an example"),
        (
            'name = "x"\ndescription = "d"\nprompt = "p"\nexample = "{\\"items\\": 3}"\n',
            "not a valid extraction",
        ),
    ],
)
def test_a_spec_that_cannot_be_used_is_skipped_and_said_why(tmp_path, content, error):
    (tmp_path / "bad.toml").write_text(content, encoding="utf-8")
    (tmp_path / "good.toml").write_text(
        'kind = "datafile"\nname = "good"\ndescription = "d"\nprompt = "p"\n', encoding="utf-8"
    )
    importers, errors = load_folder(tmp_path)
    assert [i.name for i in importers] == ["good"]
    assert len(errors) == 1 and errors[0].startswith("bad.toml: ") and error in errors[0]


def test_a_local_importer_cannot_take_a_built_in_name(tmp_path):
    (tmp_path / "general.toml").write_text(
        'kind = "datafile"\nname = "general"\ndescription = "Mine."\nprompt = "p"\n', encoding="utf-8"
    )
    registry = load_registry(tmp_path)
    assert registry.get("general") is GENERAL
    assert registry.errors == ["general: that name is taken"]


def test_no_folder_is_just_no_local_importers(tmp_path):
    registry = load_registry(tmp_path / "missing")
    assert [i.name for i in registry.all()] == ["general"] and registry.errors == []
