"""Words beside a word (PLAN 6, phase 4).

Built out of what is already written down, so the tests are mostly about what it
is honest about: it knows what two words *mean*, and it does not know that one is
the opposite of another.
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
def stocked(api) -> tuple[TestClient, dict[str, str]]:
    """A lesson with a synonym pair, a near pair, and an opposite: api, front → id."""
    category = api.post("/api/categories", json={"path": "korean/book1/03"}).json()
    file = api.post(
        f"/api/categories/{category['id']}/files",
        json={
            "title": "3-1 Vocabulary",
            "front_lang": "ko",
            "back_lang": "en",
            "default_type": "bidirectional",
        },
    ).json()
    created = api.post(
        f"/api/files/{file['id']}/notes",
        json={
            "notes": [
                {"front": "밑", "back": "under, below", "group": "위치"},
                {"front": "아래", "back": "under, below", "group": "위치"},
                {"front": "위", "back": "above", "group": "위치"},
                {"front": "그것", "back": "that", "group": "지시"},
                {"front": "그게", "back": "that (over there)", "group": "지시"},
                {"front": "사과", "back": "apple", "group": "음식"},
            ]
        },
    )
    assert created.status_code == 201, created.text
    notes = api.get(f"/api/files/{file['id']}/notes").json()["notes"]
    return api, {note["front"]: note["id"] for note in notes}


def _related(api: TestClient, note_id: str) -> list[dict]:
    response = api.get(f"/api/notes/{note_id}/related")
    assert response.status_code == 200, response.text
    return response.json()["related"]


def test_a_word_finds_the_one_that_means_the_same(stocked):
    api, ids = stocked
    found = _related(api, ids["밑"])
    same = [one for one in found if one["how"] == "same-meaning"]
    assert [one["front"] for one in same] == ["아래"]


def test_a_gloss_narrowed_by_a_bracket_is_only_nearly_the_same(stocked):
    """What the extractor tried to tell apart and nearly did."""
    api, ids = stocked
    found = _related(api, ids["그것"])
    assert [(one["front"], one["how"]) for one in found if one["how"] == "near-meaning"] == [
        ("그게", "near-meaning")
    ]


def test_the_heading_is_what_stands_in_for_an_opposite(stocked):
    """위 and 밑 are a pair because the page prints them as one, not because the data says so."""
    api, ids = stocked
    found = _related(api, ids["밑"])
    assert ("위", "same-heading") in [(one["front"], one["how"]) for one in found]
    assert "사과" not in [one["front"] for one in found], "another heading is not a relation"


def test_the_closest_relation_comes_first_and_a_word_appears_once(stocked):
    api, ids = stocked
    found = _related(api, ids["밑"])
    assert [one["how"] for one in found] == sorted(
        (one["how"] for one in found), key=["same-meaning", "near-meaning", "same-heading"].index
    )
    assert len({one["note_id"] for one in found}) == len(found)
    assert [one["front"] for one in found][0] == "아래", "the synonym leads, not the heading-mate"


def test_a_pair_says_whether_it_already_accepts_itself_both_ways(stocked):
    """The audit's one-sided finding, where you can actually act on it."""
    api, ids = stocked
    bare = next(one for one in _related(api, ids["밑"]) if one["front"] == "아래")
    assert (bare["accepts"], bare["accepted_by"]) == (False, False), "neither way, to begin with"

    api.patch(f"/api/notes/{ids['밑']}", json={"accept": {"front": ["아래"]}})
    half = next(one for one in _related(api, ids["밑"]) if one["front"] == "아래")
    assert (half["accepts"], half["accepted_by"]) == (True, False), "one way only"
    other = next(one for one in _related(api, ids["아래"]) if one["front"] == "밑")
    assert (other["accepts"], other["accepted_by"]) == (False, True), "and it reads both ways round"

    api.patch(f"/api/notes/{ids['아래']}", json={"accept": {"front": ["밑"]}})
    done = next(one for one in _related(api, ids["밑"]) if one["front"] == "아래")
    assert (done["accepts"], done["accepted_by"]) == (True, True)


def test_a_word_set_aside_is_still_a_related_word(stocked):
    """It still means what it meant, and this is how you find out why you set it aside."""
    api, ids = stocked
    api.patch(f"/api/notes/{ids['아래']}", json={"suspended": True})
    found = next(one for one in _related(api, ids["밑"]) if one["front"] == "아래")
    assert found["suspended"] is True


def test_a_word_with_nothing_beside_it_says_so(stocked):
    api, ids = stocked
    assert [one["front"] for one in _related(api, ids["사과"])] == []


def test_no_such_note(api):
    assert api.get("/api/notes/n_nonesuch/related").status_code == 404


def test_the_audit_now_hands_over_the_hints_it_was_computing(stocked):
    """`near` was dropped on the floor by the API until now."""
    api, _ = stocked
    report = api.get("/api/collection/audit").json()
    assert "near" in report and "resolved" in report
    assert [f["key"] for f in report["near"]] == ["that"], "그것 beside 그게"
    assert [f["key"] for f in report["collisions"]] == ["under, below"]
    assert report["clean"] is False

    # Cross-accept the pair; the collision becomes a resolved one and `clean` holds.
    clash = report["collisions"][0]["notes"]
    ids = {note["front"]: note["note_id"] for note in clash}
    api.patch(f"/api/notes/{ids['밑']}", json={"accept": {"front": ["아래"]}})
    api.patch(f"/api/notes/{ids['아래']}", json={"accept": {"front": ["밑"]}})
    after = api.get("/api/collection/audit").json()
    assert after["collisions"] == [] and [f["key"] for f in after["resolved"]] == ["under, below"]
