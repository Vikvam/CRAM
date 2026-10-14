"""Finding a word again (PLAN 6, phase 4).

The collection the fixtures build is small, so these tests mostly check *which*
field a hit came from and in what order — the two things a scan can get wrong
without anyone noticing, because a wrong answer still looks like a list of words.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memo.api import create_app
from memo.config import Settings


@pytest.fixture
def api(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(var_dir=tmp_path / "var", data_dir=tmp_path / "data")))


@pytest.fixture
def editing(api) -> tuple[TestClient, str, str]:
    """A category with one empty data file in it: api, category id, file id."""
    category = api.post("/api/categories", json={"path": "korean/book1/03-daily-life"}).json()
    file = api.post(
        f"/api/categories/{category['id']}/files",
        json={
            "title": "3-1 Vocabulary",
            "front_lang": "ko",
            "back_lang": "en",
            "default_type": "bidirectional",
        },
    )
    assert file.status_code == 201, file.text
    return api, category["id"], file.json()["id"]


@pytest.fixture
def stocked(editing) -> tuple[TestClient, str, str]:
    """A file of words with every searchable field in use: api, category, file."""
    api, category, file = editing
    created = api.post(
        f"/api/files/{file}/notes",
        json={
            "notes": [
                {"front": "아래", "back": "under, below", "group": "위치"},
                {"front": "밑", "back": "under, below", "group": "위치"},
                {"front": "미국", "back": "USA", "accept": {"back": ["america"]}, "group": "나라"},
                {"front": "누가", "back": "who + 가 (subject)", "note": "누구+가 → 누가"},
                {"front": "아래층", "back": "the floor below"},
            ]
        },
    )
    assert created.status_code == 201, created.text
    notes = api.get(f"/api/files/{file}/notes").json()["notes"]
    by_front = {note["front"]: note["id"] for note in notes}
    api.patch(f"/api/notes/{by_front['밑']}", json={"accept": {"front": ["아래"]}})
    api.patch(f"/api/notes/{by_front['아래층']}", json={"suspended": True})
    api.patch(f"/api/notes/{by_front['미국']}", json={"priority": "crucial"})
    return api, category, file


def _find(api: TestClient, q: str, **params) -> dict:
    response = api.get("/api/notes/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_word_is_found_by_its_own_two_sides(stocked):
    api, _, _ = stocked
    assert [hit["front"] for hit in _find(api, "미국")["hits"]] == ["미국"]
    assert _find(api, "미국")["hits"][0]["where"] == "front"
    usa = _find(api, "USA")["hits"][0]
    assert (usa["front"], usa["where"], usa["how"]) == ("미국", "back", "exact")


def test_a_word_is_found_by_a_spelling_it_merely_accepts(stocked):
    """Typing the English the page did not print is the whole point of ``accept``."""
    api, _, _ = stocked
    hit = _find(api, "america")["hits"][0]
    assert (hit["front"], hit["where"], hit["how"]) == ("미국", "accept", "exact")


def test_a_word_is_found_by_its_note_its_heading_and_its_lesson(stocked):
    api, _, _ = stocked
    by_note = _find(api, "누구+가")
    assert [hit["front"] for hit in by_note["hits"]] == ["누가"]
    assert by_note["hits"][0]["where"] == "note"

    by_group = _find(api, "위치")
    assert {hit["front"] for hit in by_group["hits"]} == {"아래", "밑"}
    assert {hit["where"] for hit in by_group["hits"]} == {"group"}

    by_file = _find(api, "3-1 Vocabulary")
    assert by_file["total"] == 5, "the whole lesson, and nothing outside it"
    assert {hit["where"] for hit in by_file["hits"]} == {"file"}


def test_the_word_itself_outranks_what_is_written_about_it(stocked):
    """A file title matches thirty-two notes at once; it must never lead."""
    api, _, _ = stocked
    hits = _find(api, "아래")["hits"]
    assert [(hit["front"], hit["where"], hit["how"]) for hit in hits] == [
        ("아래", "front", "exact"),
        ("아래층", "front", "prefix"),
        ("밑", "accept", "exact"),
    ], "exact before prefix before a mere acceptance"


def test_an_exact_meaning_beats_a_partial_word(stocked):
    """Ranking goes by tier, then exactness, and only then by which side."""
    api, _, _ = stocked
    hits = _find(api, "under, below")["hits"]
    assert [hit["front"] for hit in hits] == ["아래", "밑"]
    assert {hit["how"] for hit in hits} == {"exact"}


def test_a_word_set_aside_is_still_found(stocked):
    """The one word nothing else in the app could reach."""
    api, _, _ = stocked
    hits = _find(api, "아래층")["hits"]
    assert [(hit["front"], hit["suspended"]) for hit in hits] == [("아래층", True)]
    assert [hit["front"] for hit in _find(api, "아래", aside=True)["hits"]] == ["아래층"]
    assert "아래층" not in [hit["front"] for hit in _find(api, "아래", aside=False)["hits"]]


def test_a_hit_carries_how_well_the_word_is_known_both_ways(stocked):
    api, _, _ = stocked
    hit = _find(api, "미국")["hits"][0]
    assert (hit["forward"], hit["reverse"]) == ("new", "new")
    assert hit["priority"] == "crucial", "the mark as set, not as a session damps it"


def test_the_mark_filters(stocked):
    api, _, _ = stocked
    assert [hit["front"] for hit in _find(api, "u", mark="crucial")["hits"]] == ["미국"]
    assert "미국" not in [hit["front"] for hit in _find(api, "u", mark="normal")["hits"]]


def test_an_empty_query_finds_nothing_rather_than_everything(stocked):
    api, _, _ = stocked
    assert _find(api, "   ") == {"q": "   ", "total": 0, "hits": []}


def test_a_page_reports_the_whole_total(stocked):
    api, _, _ = stocked
    page = _find(api, "3-1 Vocabulary", limit=2)
    assert (len(page["hits"]), page["total"]) == (2, 5)
    rest = _find(api, "3-1 Vocabulary", limit=2, offset=2)
    assert len(rest["hits"]) == 2
    assert {hit["note_id"] for hit in page["hits"]} & {hit["note_id"] for hit in rest["hits"]} == set()


def test_a_nonsense_filter_is_refused_rather_than_ignored(stocked):
    api, _, _ = stocked
    assert api.get("/api/notes/search", params={"q": "a", "mark": "urgent"}).status_code == 422
    assert api.get("/api/notes/search", params={"q": "a", "standing": "fluent"}).status_code == 422
    assert api.get("/api/notes/search", params={"q": "a", "category_id": "nope"}).status_code == 404
