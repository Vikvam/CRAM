"""A PDF goes to the model a few pages at a time, as its text or as pictures (importpipe/units.py)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from memo.api import create_app
from memo.config import Settings
from memo.importers import load_registry
from memo.importers.general import IMPORTER as GENERAL
from memo.importpipe import run_import
from memo.importpipe.units import UnreadablePdf, units_for
from memo.llm.client import LLMError
from tests.conftest import EXAMPLE_IMPORTERS
from tests.fakes import FakeLLM, write_pdf


def answer(*pairs: tuple[str, str]) -> str:
    notes = [{"front": f, "back": b} for f, b in pairs]
    body = {
        "format": "memo.datafile",
        "version": 1,
        "title": "Numbers",
        "default_type": "directional",
        "front_lang": "en",
        "back_lang": "en",
        "notes": notes,
    }
    return f"```json\n{json.dumps(body)}\n```"


def material(call) -> list[dict]:
    """What the model was shown, after the prompt."""
    return call["messages"][-1].content[1:]


@pytest.fixture
def twelve_pages(tmp_path):
    path = tmp_path / "chapter.pdf"
    write_pdf(path, [[f"term {i} = meaning {i}"] for i in range(1, 13)])
    return path


def test_a_pdf_is_read_a_few_pages_at_a_time_as_text(twelve_pages):
    client = FakeLLM([answer(("term 1", "meaning 1")), answer(("term 6", "meaning 6")), answer(("t", "m"))])
    outcome = run_import(client, GENERAL, [twelve_pages], tier="text", pages_per_call=5)
    assert len(client.calls) == 3
    texts = [material(c) for c in client.calls]
    assert all(len(parts) == 1 and parts[0]["type"] == "text" for parts in texts)
    assert "--- page 1 ---\nterm 1 = meaning 1" in texts[0][0]["text"]
    assert "--- page 6 ---" in texts[1][0]["text"] and "--- page 5 ---" not in texts[1][0]["text"]
    assert len(outcome.datafile.notes) == 3
    assert outcome.datafile.source.kind == "pdf"
    assert [p.count for p in outcome.pages] == [5, 5, 2]


def test_the_model_is_told_which_pages_and_their_printed_numbers(twelve_pages):
    client = FakeLLM(lambda m: answer(("a", "b")))
    run_import(client, GENERAL, [twelve_pages], tier="text", pages_per_call=5, first_page_number=40)
    lines = [c["messages"][0].content[0]["text"].splitlines()[-1] for c in client.calls]
    assert lines == [
        "This is pages 1–5 of chapter.pdf. It is part 1 of 3 in one upload. They are printed pages 40–44.",
        "This is pages 6–10 of chapter.pdf. It is part 2 of 3 in one upload. They are printed pages 45–49.",
        "This is pages 11–12 of chapter.pdf. It is part 3 of 3 in one upload. They are printed pages 50–51.",
    ]


def test_as_pictures_each_page_is_an_image(twelve_pages):
    client = FakeLLM(lambda m: answer(("a", "b")))
    run_import(client, GENERAL, [twelve_pages], tier="text", pages_per_call=5, pdf_mode="images")
    shown = [material(c) for c in client.calls]
    assert [len(parts) for parts in shown] == [5, 5, 2]
    assert all(p["image_url"]["url"].startswith("data:image/jpeg;base64,") for parts in shown for p in parts)


def test_a_scan_is_sent_as_pictures_even_when_text_was_asked_for(tmp_path):
    path = tmp_path / "scan.pdf"
    write_pdf(path, [[], []])
    client = FakeLLM(lambda m: answer(("a", "b")))
    run_import(client, GENERAL, [path], tier="text")
    assert [p["type"] for p in material(client.calls[0])] == ["image_url", "image_url"]


def test_photos_and_pdfs_share_one_page_count(tmp_path, sample_image):
    pdf = tmp_path / "two.pdf"
    write_pdf(pdf, [["a = 1"], ["b = 2"]])
    units = units_for([sample_image, pdf, sample_image], pages_per_call=5)
    assert [(u.offset, u.count) for u in units] == [(0, 1), (1, 2), (3, 1)]
    client = FakeLLM(lambda m: answer(("x", "y")))
    run_import(client, GENERAL, [sample_image, pdf, sample_image], tier="text", first_page_number=10)
    lines = [c["messages"][0].content[0]["text"].splitlines()[-1] for c in client.calls]
    assert lines[1].endswith("They are printed pages 11–12.")
    assert lines[2] == "This is photo 3 of 3 in one upload. It is printed page 13."


def test_one_failed_chunk_costs_only_its_pages(twelve_pages):
    client = FakeLLM([answer(("a", "b")), LLMError("timed out"), answer(("c", "d"))])
    outcome = run_import(client, GENERAL, [twelve_pages], tier="text", pages_per_call=5)
    assert [p.number for p in outcome.failed_pages] == [6]
    assert [n.front for n in outcome.datafile.notes] == ["a", "c"]


def test_an_extraction_importer_reads_pdf_text_too(twelve_pages, fixture_dir):
    korean = load_registry(EXAMPLE_IMPORTERS).get("korean-textbook-vocab")
    client = FakeLLM(lambda m: (fixture_dir / "vocab1.extraction.json").read_text("utf-8"))
    outcome = run_import(client, korean, [twelve_pages], tier="text", pages_per_call=12)
    assert len(client.calls) == 1 and material(client.calls[0])[0]["type"] == "text"
    assert len(outcome.datafile.notes) == 32


def test_something_that_is_not_a_pdf_says_so(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(UnreadablePdf, match="could not be opened"):
        units_for([path])


# --- through the app --------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    client = FakeLLM(lambda m: answer(("term", "meaning")))
    settings = Settings(
        var_dir=tmp_path / "var",
        data_dir=tmp_path / "data",
        importers_dir=tmp_path / "none",
        pdf_pages_per_call=5,
    )
    return TestClient(create_app(settings, client_factory=lambda: client)), client


def _upload(api, files, **data):
    category = api.post("/api/categories", json={"path": "notes"}).json()
    return api.post("/api/imports", data={"category_id": category["id"], **data}, files=files)


def test_a_pdf_upload_becomes_one_draft(api, twelve_pages):
    app, client = api
    with twelve_pages.open("rb") as handle:
        response = _upload(
            app, [("files", ("chapter.pdf", handle, "application/pdf"))], pdf_mode="images", first_page="3"
        )
    assert response.status_code == 202, response.text
    job = app.get(f"/api/imports/{response.json()['id']}").json()
    assert job["status"] == "review" and job["importer"] == "general"
    assert len(client.calls) == 3
    assert all(p["type"] == "image_url" for p in material(client.calls[0]))
    assert [p["page_number"] for p in job["pages"]] == [3]
    assert job["pages"][0]["status"] == "done"
    assert job["draft"]["source"]["kind"] == "pdf"


def test_pdf_mode_must_be_one_of_the_two(api, twelve_pages):
    app, _ = api
    with twelve_pages.open("rb") as handle:
        response = _upload(app, [("files", ("chapter.pdf", handle, "application/pdf"))], pdf_mode="magic")
    assert response.status_code == 400 and "pdf_mode" in response.json()["detail"]


def test_a_broken_pdf_is_refused_at_upload(api):
    app, _ = api
    response = _upload(app, [("files", ("x.pdf", b"not a pdf", "application/pdf"))])
    assert response.status_code == 400 and "could not be opened" in response.json()["detail"]


def test_pages_after_a_pdf_are_numbered_past_it(api, twelve_pages, sample_image):
    app, _ = api
    with twelve_pages.open("rb") as pdf, sample_image.open("rb") as photo:
        response = _upload(
            app,
            [("files", ("chapter.pdf", pdf, "application/pdf")), ("files", ("p.jpg", photo, "image/jpeg"))],
            first_page="1",
        )
    job = app.get(f"/api/imports/{response.json()['id']}").json()
    assert [p["page_number"] for p in job["pages"]] == [1, 13]


def test_a_pdf_and_a_csv_cannot_share_an_import(api, twelve_pages):
    app, _ = api
    with twelve_pages.open("rb") as handle:
        response = _upload(
            app,
            [
                ("files", ("chapter.pdf", handle, "application/pdf")),
                ("files", ("w.csv", b"a,b\n", "text/csv")),
            ],
        )
    assert response.status_code == 400 and "not both" in response.json()["detail"]
