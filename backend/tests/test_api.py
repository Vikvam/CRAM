"""Phase 1's thin path over HTTP (PLAN 6): photo → review → practise."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from memo.api import create_app
from memo.api.auth import hash_password
from memo.config import Settings
from memo.db.models import Category
from tests.fakes import FakeLLM

SECRET_KEY = "sk-this-must-never-leave-the-server"


@pytest.fixture
def extraction(fixture_dir) -> str:
    return (fixture_dir / "vocab1.extraction.json").read_text(encoding="utf-8")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        var_dir=tmp_path / "var",
        data_dir=tmp_path / "data",
        llm_api_key=SecretStr(SECRET_KEY),
        llm_model="fake-model",
    )


@pytest.fixture
def api(settings, extraction) -> TestClient:
    app = create_app(settings, client_factory=lambda: FakeLLM(lambda m: extraction))
    return TestClient(app)


@pytest.fixture
def gated(tmp_path, extraction) -> TestClient:
    settings = Settings(
        var_dir=tmp_path / "gated",
        auth_password_hash=hash_password("correct horse"),
        login_attempts=3,
    )
    return TestClient(create_app(settings, client_factory=lambda: FakeLLM(lambda m: extraction)))


def _import(
    api: TestClient,
    sample_image,
    category_path="korean/book1/02-introduction",
    *,
    into: str | None = None,
) -> dict:
    category = api.post("/api/categories", json={"path": category_path}).json()
    data = {"category_id": category["id"], "importer": "korean-textbook-vocab", "first_page": "6"}
    if into:
        data["target_data_file_id"] = into
    with sample_image.open("rb") as handle:
        response = api.post(
            "/api/imports", data=data, files=[("files", ("vocab1.jpg", handle, "image/jpeg"))]
        )
    assert response.status_code == 202, response.text
    return api.get(f"/api/imports/{response.json()['id']}").json()


# --- the gate ---------------------------------------------------------------


def test_without_a_password_configured_the_gate_is_open(api):
    assert api.get("/api/auth/status").json()["signed_in"] is True
    assert api.get("/api/categories").status_code == 200


def test_the_api_is_closed_until_you_sign_in(gated):
    assert gated.get("/api/auth/status").json() == {"signed_in": False, "gate_open": False, "profile": None}
    assert gated.get("/api/categories").status_code == 401


def test_a_wrong_password_is_refused(gated):
    assert gated.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    assert gated.get("/api/categories").status_code == 401


def test_the_right_password_opens_it(gated):
    response = gated.post("/api/auth/login", json={"password": "correct horse"})
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()
    assert gated.get("/api/categories").status_code == 200


def test_logins_are_rate_limited(gated):
    for _ in range(3):
        gated.post("/api/auth/login", json={"password": "nope"})
    blocked = gated.post("/api/auth/login", json={"password": "correct horse"})
    assert blocked.status_code == 429, "even the right password waits once the limit is hit"


def test_a_forged_cookie_is_refused(gated):
    gated.cookies.set("memo_session", "forged.value.sig")
    assert gated.get("/api/categories").status_code == 401


def test_logging_out_closes_the_session(gated):
    gated.post("/api/auth/login", json={"password": "correct horse"})
    gated.post("/api/auth/logout")
    assert gated.get("/api/categories").status_code == 401


def test_the_llm_key_never_reaches_the_client(api, sample_image):
    """PLAN 5: the key stays server-side."""
    settings = api.get("/api/settings")
    assert settings.json()["llm_configured"] is True
    job = _import(api, sample_image)
    for response in (settings, api.get("/api/openapi.json"), api.get(f"/api/imports/{job['id']}")):
        assert SECRET_KEY not in response.text


# --- photo → review ---------------------------------------------------------


def test_an_upload_becomes_a_draft_waiting_for_review(api, sample_image):
    job = _import(api, sample_image)
    assert job["status"] == "review"
    assert job["importer"] == "korean-textbook-vocab"
    assert len(job["draft"]["notes"]) == 32
    assert {n["status"] for n in job["draft"]["notes"]} == {"unverified"}
    assert job["pages"][0]["status"] == "done"


def test_the_raw_photo_is_kept_and_served_for_the_review_screen(api, sample_image):
    job = _import(api, sample_image)
    photo = api.get(f"/api/raw/{job['pages'][0]['path']}")
    assert photo.status_code == 200
    assert photo.content == sample_image.read_bytes()


def test_raw_files_cannot_escape_the_raw_directory(api):
    assert api.get("/api/raw/../memo.db").status_code == 404
    assert api.get("/api/raw/%2e%2e/memo.db").status_code == 404


def test_a_non_image_upload_is_refused(api):
    category = api.post("/api/categories", json={"path": "korean"}).json()
    response = api.post(
        "/api/imports",
        data={"category_id": category["id"]},
        files=[("files", ("notes.exe", b"MZ", "application/octet-stream"))],
    )
    assert response.status_code == 400


def test_a_failed_extraction_is_visible_and_retryable(settings, sample_image, extraction):
    from memo.llm.client import LLMError

    answers = iter([LLMError("provider down"), extraction])

    def factory():
        return FakeLLM(lambda m: (_ for _ in ()).throw(e) if isinstance(e := next(answers), Exception) else e)

    api = TestClient(create_app(settings, client_factory=factory))
    job = _import(api, sample_image)
    assert job["status"] == "failed" and "provider down" in job["error"]

    retried = api.post(f"/api/imports/{job['id']}/retry")
    assert retried.status_code == 200
    assert api.get(f"/api/imports/{job['id']}").json()["status"] == "review"


def test_editing_the_draft_is_validated(api, sample_image):
    job = _import(api, sample_image)
    draft = job["draft"]
    draft["notes"] = [n for n in draft["notes"] if n["front"] != "주부"]
    draft["notes"][0]["back"] = "Russia (the country)"
    saved = api.put(f"/api/imports/{job['id']}/draft", json=draft)
    assert saved.status_code == 200
    assert len(saved.json()["draft"]["notes"]) == 31

    broken = api.put(f"/api/imports/{job['id']}/draft", json={"format": "anki.deck", "version": 1})
    assert broken.status_code == 422


def test_committing_stores_the_notes_as_confirmed(api, sample_image):
    job = _import(api, sample_image)
    committed = api.post(f"/api/imports/{job['id']}/commit").json()
    assert committed["status"] == "committed"

    stored = api.get(f"/api/files/{committed['target_data_file_id']}").json()
    assert len(stored["notes"]) == 32
    assert {n["status"] for n in stored["notes"]} == {"confirmed"}

    assert api.post(f"/api/imports/{job['id']}/commit").status_code == 409, "a job commits once"


def test_the_category_tree_counts_what_is_in_it(api, sample_image):
    job = _import(api, sample_image)
    api.post(f"/api/imports/{job['id']}/commit")
    tree = {c["path"]: c for c in api.get("/api/categories").json()}
    assert set(tree) == {"korean", "korean/book1", "korean/book1/02-introduction"}
    lesson = tree["korean/book1/02-introduction"]
    assert (lesson["notes"], lesson["cards"], lesson["new"], lesson["due"]) == (32, 64, 64, 0)


# --- practise ---------------------------------------------------------------


@pytest.fixture
def practising(api, sample_image) -> tuple[TestClient, str]:
    job = _import(api, sample_image)
    api.post(f"/api/imports/{job['id']}/commit")
    return api, job["category_id"]


def test_the_queue_takes_new_cards_in_page_order_but_does_not_ask_them_in_it(practising):
    """Which cards you get follows the book; the order you meet them does not."""
    api, category = practising
    cards = api.get("/api/practice/queue", params={"category_id": category, "new_limit": 4}).json()["cards"]

    assert {(c["prompt"], c["direction"]) for c in cards} == {
        ("러시아", "fwd"),
        ("Russia", "rev"),
        ("중국", "fwd"),
        ("China", "rev"),
    }, "the first two notes of the page, both ways"

    pairs = {c["prompt"]: (c["answer"], c["answer_lang"]) for c in cards}
    assert pairs["러시아"] == ("Russia", "en")
    assert pairs["Russia"] == ("러시아", "ko")

    notes = [c["note_id"] for c in cards]
    assert all(a != b for a, b in zip(notes, notes[1:], strict=False)), "a note is never asked twice in a row"


def test_a_category_decides_how_its_cards_are_practised(api):
    """Phase 3: the ⋯ panel writes these; the queue and its suggestions obey them."""
    book = api.post("/api/categories", json={"path": "korean/book1"}).json()
    lesson = api.post("/api/categories", json={"path": "korean/book1/02-introduction"}).json()
    assert book["practice"] == {"modes": None, "distractor_scope": None}, "nothing of its own yet"
    assert book["practice_resolved"]["modes"] == ["flip", "typed", "choice", "match", "build"]

    set_on_book = api.patch(
        f"/api/categories/{book['id']}",
        json={"practice": {"modes": ["typed", "flip"], "distractor_scope": "file"}},
    )
    assert set_on_book.status_code == 200, set_on_book.text
    assert set_on_book.json()["practice"]["modes"] == ["flip", "typed"], "kept in UI order"

    # The lesson below says nothing, so it answers with what it inherits.
    rows = {c["id"]: c for c in api.get("/api/categories").json()}
    assert rows[lesson["id"]]["practice"] == {"modes": None, "distractor_scope": None}
    assert rows[lesson["id"]]["practice_resolved"] == {
        "modes": ["flip", "typed"],
        "distractor_scope": "file",
    }

    # And it can disagree with its parent about one key without restating the other.
    api.patch(f"/api/categories/{lesson['id']}", json={"practice": {"distractor_scope": "group"}})
    rows = {c["id"]: c for c in api.get("/api/categories").json()}
    assert rows[lesson["id"]]["practice_resolved"] == {
        "modes": ["flip", "typed"],
        "distractor_scope": "group",
    }

    queue = api.get("/api/practice/queue", params={"category_id": lesson["id"]}).json()
    assert queue["modes"] == ["flip", "typed"]
    assert queue["distractor_scope"] == "group"


def test_practising_everything_offers_what_every_subject_agrees_on(api):
    """There is no one category to ask, so the roots have to agree."""
    korean = api.post("/api/categories", json={"path": "korean"}).json()
    maths = api.post("/api/categories", json={"path": "maths"}).json()
    api.patch(f"/api/categories/{korean['id']}", json={"practice": {"modes": ["flip", "typed", "choice"]}})
    api.patch(f"/api/categories/{maths['id']}", json={"practice": {"modes": ["flip", "typed", "build"]}})

    everything = api.get("/api/practice/queue").json()
    assert everything["modes"] == ["flip", "typed"], "not a mode only one subject allows"
    assert everything["distractor_scope"] == "auto", "the two disagree, so neither wins"

    api.patch(f"/api/categories/{korean['id']}", json={"practice": {"distractor_scope": "file"}})
    api.patch(f"/api/categories/{maths['id']}", json={"practice": {"distractor_scope": "file"}})
    assert api.get("/api/practice/queue").json()["distractor_scope"] == "file", "agreed"


def test_a_category_cannot_be_left_with_no_way_to_practise_it(api):
    category = api.post("/api/categories", json={"path": "korean"}).json()
    assert api.patch(f"/api/categories/{category['id']}", json={"practice": {"modes": []}}).status_code == 409
    nonsense = api.patch(f"/api/categories/{category['id']}", json={"practice": {"modes": ["sing"]}})
    assert nonsense.status_code == 409 and "sing" in nonsense.text
    bad_scope = api.patch(
        f"/api/categories/{category['id']}", json={"practice": {"distractor_scope": "galaxy"}}
    )
    assert bad_scope.status_code == 409


def test_clearing_a_categorys_practice_settings_goes_back_to_inheriting(api):
    category = api.post("/api/categories", json={"path": "korean"}).json()
    api.patch(f"/api/categories/{category['id']}", json={"practice": {"modes": ["flip"]}})
    cleared = api.patch(f"/api/categories/{category['id']}", json={"practice": None}).json()
    assert cleared["practice"] == {"modes": None, "distractor_scope": None}
    assert cleared["practice_resolved"]["modes"] == ["flip", "typed", "choice", "match", "build"]


def test_the_queue_brings_the_options_and_the_mode_with_it(practising):
    """Phase 3: a card arrives knowing what it can be asked as, and what the wrong
    options are, so a session needs one request and then nothing until the answer."""
    api, category = practising
    queue = api.get("/api/practice/queue", params={"category_id": category, "new_limit": 100}).json()

    assert queue["modes"] == ["flip", "typed", "choice", "match", "build"]
    assert queue["distractor_scope"] == "auto"

    card = next(c for c in queue["cards"] if c["prompt"] == "러시아")
    assert card["suggest"] == "choice", "never seen before: recognise it first"
    assert len(card["distractors"]) == 3
    assert card["answer"] not in card["distractors"]
    assert "Russia" not in card["distractors"]

    narrowed = api.get(
        "/api/practice/queue",
        params={"category_id": category, "new_limit": 100, "distractor_scope": "group"},
    ).json()
    assert narrowed["distractor_scope"] == "group"
    same = next(c for c in narrowed["cards"] if c["prompt"] == "러시아")
    assert set(same["distractors"]) <= {c["answer"] for c in narrowed["cards"]}
    assert same["distractors"] != card["distractors"] or len(same["distractors"]) == 3


def test_a_card_is_oriented_with_the_accepted_answers_for_its_answer_side(practising):
    api, category = practising
    cards = api.get("/api/practice/queue", params={"category_id": category, "new_limit": 100}).json()["cards"]
    which = next(c for c in cards if c["prompt"] == "어느")
    assert which["accepted"] == ["what", "which"]
    reverse = next(c for c in cards if c["prompt"] == "what, which")
    assert reverse["accepted"] == [], "no accept list was given for the Korean side"


def test_answering_schedules_the_card_and_takes_it_out_of_the_queue(practising):
    api, category = practising
    first = api.get("/api/practice/queue", params={"category_id": category}).json()["cards"][0]
    answered = api.post(
        "/api/practice/answer",
        json={"card_key": first["key"], "mode": "typed", "outcome": "correct", "raw_answer": "Russia"},
    )
    assert answered.status_code == 200
    assert answered.json()["state"]["reps"] == 1

    remaining = api.get("/api/practice/queue", params={"category_id": category, "new_limit": 100}).json()
    assert first["key"] not in {c["key"] for c in remaining["cards"]}


def test_the_queue_says_what_the_scope_holds(practising):
    """An empty list used to be all the client was told, so it had to guess why."""
    api, category = practising
    whole = api.get("/api/practice/queue", params={"category_id": category, "new_limit": 100}).json()
    assert whole["total"] == len(whole["cards"]) and whole["new_count"] == whole["total"]
    assert whole["ahead_count"] == 0 and whole["next_due"] is None

    for card in whole["cards"]:
        api.post(
            "/api/practice/answer",
            json={"card_key": card["key"], "mode": "typed", "outcome": "correct"},
        )

    caught_up = api.get("/api/practice/queue", params={"category_id": category, "ahead": False}).json()
    assert caught_up["cards"] == []
    assert caught_up["due_count"] == caught_up["new_count"] == 0
    assert caught_up["total"] == whole["total"], "caught up, not empty"
    assert caught_up["next_due"] is not None, "and it says when"

    ahead = api.get("/api/practice/queue", params={"category_id": category}).json()
    assert ahead["cards"], "a scope you asked for is never a dead end"
    assert ahead["ahead_count"] == len(ahead["cards"])
    assert all(c["early"] for c in ahead["cards"])


def test_flip_requires_a_grade(practising):
    api, category = practising
    card = api.get("/api/practice/queue", params={"category_id": category}).json()["cards"][0]
    assert api.post("/api/practice/answer", json={"card_key": card["key"], "mode": "flip"}).status_code == 422
    ok = api.post("/api/practice/answer", json={"card_key": card["key"], "mode": "flip", "grade": 3})
    assert ok.status_code == 200


def test_a_batch_from_the_phone_lands_once_however_often_it_is_offered(practising):
    """Practice with no network, handed back later (PLAN 5) — by wire and by file."""
    api, category = practising
    cards = api.get("/api/practice/queue", params={"category_id": category}).json()["cards"][:2]
    rows = [
        {
            "client_id": f"phone-{n}",
            "at": f"2026-10-06T0{n}:30:00+00:00",
            "card_key": card["key"],
            "mode": "typed",
            "outcome": "correct",
            "raw_answer": "whatever the checker said",
        }
        for n, card in enumerate(cards)
    ]
    first = api.post("/api/practice/answers", json={"rows": rows})
    assert first.status_code == 200
    assert first.json() == {
        "accepted": 2,
        "duplicates": 0,
        "unknown": [],
        "rebuilt": 2,
        "rejected": [],
    }

    again = api.post("/api/practice/answers", json={"rows": rows}).json()
    assert (again["accepted"], again["duplicates"]) == (0, 2), "the file after the upload, say"

    # Answered last Tuesday, so they are due again today — but no longer new.
    queue = api.get("/api/practice/queue", params={"category_id": category, "new_limit": 100}).json()
    seen = {c["key"]: c["is_new"] for c in queue["cards"]}
    assert [seen[card["key"]] for card in cards] == [False, False]


def test_a_batch_survives_a_card_that_is_gone(practising):
    api, category = practising
    card = api.get("/api/practice/queue", params={"category_id": category}).json()["cards"][0]
    report = api.post(
        "/api/practice/answers",
        json={
            "rows": [
                {
                    "client_id": "a",
                    "at": "2026-10-06T01:00:00+00:00",
                    "card_key": card["key"],
                    "mode": "typed",
                    "outcome": "correct",
                },
                {
                    "client_id": "b",
                    "at": "2026-10-06T01:01:00+00:00",
                    "card_key": "n_gone:fwd",
                    "mode": "typed",
                    "outcome": "correct",
                },
            ]
        },
    ).json()
    assert (report["accepted"], report["unknown"]) == (1, ["n_gone:fwd"])


def test_the_log_rebuilds_the_cached_state(practising):
    """The review log is the evidence; card_state is only a cache (PLAN 5)."""
    from memo.collection.profiles import get_or_create_profile
    from memo.db.models import CardState as Row
    from memo.practice.service import replay

    api, category = practising
    card = api.get("/api/practice/queue", params={"category_id": category}).json()["cards"][0]
    for outcome in ("wrong", "almost", "correct", "correct"):
        api.post("/api/practice/answer", json={"card_key": card["key"], "mode": "typed", "outcome": outcome})

    factory = api.app.state.sessions
    with factory() as session:
        profile = get_or_create_profile(session)
        cached = session.get(Row, (profile.id, card["key"], "fsrs"))
        rebuilt = replay(session, profile, card["key"], "fsrs")
        assert rebuilt.reps == cached.reps == 4
        assert rebuilt.state == cached.state
        assert rebuilt.due == cached.due


def test_add_to_accepted_improves_the_collection(practising):
    api, category = practising
    cards = api.get("/api/practice/queue", params={"category_id": category, "new_limit": 100}).json()["cards"]
    card = next(c for c in cards if c["prompt"] == "미국")
    response = api.post(f"/api/notes/{card['note_id']}/accept", json={"side": "back", "value": "America"})
    assert response.json()["accepted"] == ["America"]

    again = api.get("/api/practice/queue", params={"category_id": category, "new_limit": 100}).json()["cards"]
    assert next(c for c in again if c["key"] == card["key"])["accepted"] == ["America"]


def test_switching_scheduler_keeps_separate_state(practising):
    api, category = practising
    card = api.get("/api/practice/queue", params={"category_id": category}).json()["cards"][0]
    api.post("/api/practice/answer", json={"card_key": card["key"], "mode": "typed", "outcome": "correct"})

    assert api.put("/api/settings", json={"scheduler": "sm2"}).json()["scheduler"] == "sm2"
    sm2_queue = api.get("/api/practice/queue", params={"category_id": category, "new_limit": 100}).json()
    assert sm2_queue["scheduler"] == "sm2"
    assert card["key"] in {c["key"] for c in sm2_queue["cards"]}, "SM-2 has not seen this card yet"

    assert api.put("/api/settings", json={"scheduler": "bogus"}).status_code == 422


def test_the_subtree_includes_child_categories(practising):
    api, _ = practising
    parent = next(c for c in api.get("/api/categories").json() if c["path"] == "korean")
    queue = api.get("/api/practice/queue", params={"category_id": parent["id"], "new_limit": 100}).json()
    assert len(queue["cards"]) == 64


def test_unknown_things_are_404(api):
    assert api.get("/api/files/df_nope").status_code == 404
    assert api.get("/api/imports/job_nope").status_code == 404
    assert api.get("/api/practice/queue", params={"category_id": "cat_nope"}).status_code == 404
    assert (
        api.post(
            "/api/practice/answer", json={"card_key": "n:fwd", "mode": "typed", "outcome": "correct"}
        ).status_code
        == 404
    )


# --- editing by hand (PLAN 6, phase 2) --------------------------------------


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


def test_a_file_can_be_typed_from_nothing_and_practised(editing):
    api, category, file = editing
    created = api.post(
        f"/api/files/{file}/notes",
        json={
            "notes": [
                {"front": "나라", "back": "country", "group": "나라"},
                {"front": "한국", "back": "Korea", "group": "나라", "accept": {"back": ["South Korea"]}},
            ]
        },
    )
    assert created.status_code == 201, created.text
    assert [n["cards"] for n in created.json()["notes"]] == [2, 2]
    assert created.json()["duplicates"] == []

    listed = api.get(f"/api/files/{file}/notes").json()
    assert [n["front"] for n in listed["notes"]] == ["나라", "한국"]
    assert [g["key"] for g in listed["groups"]] == ["나라"]
    assert listed["file"]["notes"] == 2

    queue = api.get("/api/practice/queue", params={"category_id": category}).json()
    assert len(queue["cards"]) == 4
    assert "South Korea" in next(c for c in queue["cards"] if c["prompt"] == "한국")["accepted"]


def test_the_exported_file_is_the_one_that_was_typed(editing):
    api, _, file = editing
    api.post(f"/api/files/{file}/notes", json={"notes": [{"front": "나라", "back": "country"}]})
    exported = api.get(f"/api/files/{file}").json()
    assert exported["format"] == "memo.datafile"
    assert exported["title"] == "3-1 Vocabulary"
    assert [n["front"] for n in exported["notes"]] == ["나라"]


def test_a_row_can_be_corrected_afterwards(editing):
    api, _, file = editing
    note = api.post(f"/api/files/{file}/notes", json={"notes": [{"front": "나라"}]}).json()["notes"][0]
    assert note["cards"] == 0, "half a note makes no cards"

    patched = api.patch(f"/api/notes/{note['id']}", json={"back": "country", "note": "also 국가"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["cards"] == 2
    assert patched.json()["note"] == "also 국가"

    assert api.patch(f"/api/notes/{note['id']}", json={"id": "n_forged"}).status_code == 422


def test_a_word_can_be_marked_for_how_often_it_comes_up(editing):
    api, category, file = editing
    notes = api.post(
        f"/api/files/{file}/notes",
        json={"notes": [{"front": "나라", "back": "country"}, {"front": "한국", "back": "Korea"}]},
    ).json()["notes"]

    marked = api.patch(f"/api/notes/{notes[0]['id']}", json={"priority": "high"})
    assert marked.status_code == 200 and marked.json()["priority"] == "high"
    assert api.patch(f"/api/notes/{notes[0]['id']}", json={"priority": "urgent"}).status_code == 422

    cards = api.get("/api/practice/queue", params={"category_id": category}).json()["cards"]
    mine = {c["key"]: c for c in cards}
    first = cards[0]
    assert first["note_id"] == notes[0]["id"], "marked words are asked first"
    assert (first["priority"], first["twice"]) == ("high", True)
    assert all(c["priority"] == "normal" for c in cards if c["note_id"] != notes[0]["id"])
    assert mine[f"{notes[0]['id']}:rev"]["twice"] is True, "a word is marked, not one of its cards"

    cleared = api.patch(f"/api/notes/{notes[0]['id']}", json={"priority": "normal"})
    assert cleared.json()["priority"] is None, "the middle of the three is the absence of a mark"


def test_archiving_a_note_takes_it_out_of_practice_but_keeps_it(editing):
    api, category, file = editing
    notes = api.post(
        f"/api/files/{file}/notes",
        json={"notes": [{"front": "나라", "back": "country"}, {"front": "한국", "back": "Korea"}]},
    ).json()["notes"]
    api.post(
        "/api/practice/answer",
        json={"card_key": f"{notes[0]['id']}:fwd", "mode": "typed", "outcome": "correct"},
    )

    archived = api.post(f"/api/notes/{notes[0]['id']}/archive")
    assert archived.json()["archived"] is True
    assert archived.json()["reviewed"] == 1, "the log still knows about it"
    assert [n["front"] for n in api.get(f"/api/files/{file}/notes").json()["notes"]] == ["한국"]
    assert len(api.get(f"/api/files/{file}/notes", params={"archived": True}).json()["notes"]) == 2
    assert len(api.get("/api/practice/queue", params={"category_id": category}).json()["cards"]) == 2

    api.post(f"/api/notes/{notes[0]['id']}/archive", params={"restore": True})
    # Three, not four: the card that was answered is scheduled, so it is not due again
    # yet. Asked without `ahead`, which would bring it forward — that is its own test.
    due = api.get("/api/practice/queue", params={"category_id": category, "ahead": False})
    assert len(due.json()["cards"]) == 3


def test_archiving_a_file_hides_it_from_the_category(editing):
    api, category, file = editing
    api.post(f"/api/files/{file}/notes", json={"notes": [{"front": "나라", "back": "country"}]})
    assert api.post(f"/api/files/{file}/archive").json()["archived"] is True
    assert api.get(f"/api/categories/{category}/files").json() == []
    assert next(c for c in api.get("/api/categories").json() if c["id"] == category)["notes"] == 0

    api.post(f"/api/files/{file}/archive", params={"restore": True})
    assert len(api.get(f"/api/categories/{category}/files").json()) == 1


def test_a_duplicate_is_reported_but_never_blocks(editing):
    api, _, file = editing
    other = api.post("/api/categories", json={"path": "korean/book2"}).json()
    other_file = api.post(f"/api/categories/{other['id']}/files", json={}).json()["id"]
    api.post(f"/api/files/{other_file}/notes", json={"notes": [{"front": "나라", "back": "country"}]})

    created = api.post(
        f"/api/files/{file}/notes",
        json={"notes": [{"front": "나라", "back": "nation"}, {"front": "한국", "back": "Korea"}]},
    )
    assert created.status_code == 201
    assert [n["front"] for n in created.json()["notes"]] == ["나라", "한국"], "both were added"
    [row] = created.json()["duplicates"]
    assert row["index"] == 0
    assert row["matches"][0]["category_path"] == "korean/book2"
    assert row["matches"][0]["same_back"] is False, "a different meaning is a clash, not a copy"


def test_duplicates_can_be_checked_before_typing_anything(editing):
    api, category, file = editing
    api.post(f"/api/files/{file}/notes", json={"notes": [{"front": "나라", "back": "country"}]})
    checked = api.post("/api/notes/duplicates", json={"pairs": [["  나라  ", "country"], ["새", "new"]]})
    assert [row["index"] for row in checked.json()["rows"]] == [0]
    assert checked.json()["rows"][0]["matches"][0]["same_back"] is True

    narrowed = api.post(
        "/api/notes/duplicates", json={"pairs": [["나라", "country"]], "category_id": category}
    )
    assert len(narrowed.json()["rows"]) == 1
    assert (
        api.post(
            "/api/notes/duplicates", json={"pairs": [["나라", "country"]], "category_id": "cat_nope"}
        ).status_code
        == 404
    )


def test_rows_can_be_reordered(editing):
    api, _, file = editing
    notes = api.post(
        f"/api/files/{file}/notes",
        json={"notes": [{"front": "1", "back": "one"}, {"front": "2", "back": "two"}]},
    ).json()["notes"]
    reordered = api.post(f"/api/files/{file}/reorder", json={"note_ids": [notes[1]["id"], notes[0]["id"]]})
    assert [n["front"] for n in reordered.json()["notes"]] == ["2", "1"]


def test_a_category_can_be_renamed_and_moved(editing):
    api, category, file = editing
    renamed = api.patch(
        f"/api/categories/{category}",
        json={"slug": "03 Daily life", "label": {"ko": "일상", "en": "Daily life"}},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["path"] == "korean/book1/03-daily-life"
    assert renamed.json()["label"] == {"ko": "일상", "en": "Daily life"}

    korean = next(c for c in api.get("/api/categories").json() if c["path"] == "korean")
    moved = api.patch(f"/api/categories/{category}", json={"parent_id": korean["id"]})
    assert moved.json()["path"] == "korean/03-daily-life"
    assert api.get(f"/api/categories/{category}/files").json()[0]["id"] == file, "its files came along"

    assert api.patch(f"/api/categories/{korean['id']}", json={"parent_id": category}).status_code == 409


def test_a_category_is_only_deleted_when_it_is_empty(editing):
    api, category, file = editing
    assert api.delete(f"/api/categories/{category}").status_code == 409
    api.post(f"/api/files/{file}/archive")
    assert api.delete(f"/api/categories/{category}").status_code == 409, "archived is not gone"

    empty = api.post("/api/categories", json={"path": "korean/book1/04-empty"}).json()
    assert api.delete(f"/api/categories/{empty['id']}").status_code == 204
    assert not any(c["id"] == empty["id"] for c in api.get("/api/categories").json())


def test_a_file_can_be_retitled_and_moved_between_categories(editing):
    api, category, file = editing
    api.post(f"/api/files/{file}/notes", json={"notes": [{"front": "나라", "back": "country"}]})
    other = api.post("/api/categories", json={"path": "korean/book1/99-mistakes"}).json()

    patched = api.patch(
        f"/api/files/{file}",
        json={"title": "3-1 Words", "category_id": other["id"], "default_type": "directional"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "3-1 Words"
    assert api.get(f"/api/categories/{category}/files").json() == []
    assert len(api.get("/api/practice/queue", params={"category_id": other["id"]}).json()["cards"]) == 1
    assert api.patch(f"/api/files/{file}", json={"category_id": "cat_nope"}).status_code == 422


def test_renaming_a_file_stores_exactly_what_was_sent(editing):
    """The old title was a language map shown joined, so every rename through the
    box prepended the native title to what you typed. A title is one line now."""
    api, _, file = editing
    api.patch(f"/api/files/{file}", json={"title": "2-2 · 이것이 무엇이에요? · What is this?"})
    for _ in range(3):
        shown = api.get(f"/api/files/{file}/notes").json()["file"]["title"]
        assert shown == "2-2 · 이것이 무엇이에요? · What is this?"
        api.patch(f"/api/files/{file}", json={"title": shown})

    assert api.patch(f"/api/files/{file}", json={"title": None}).json()["title"] is None


def test_export_writes_the_tree_and_reports_strangers(editing, settings, tmp_path):
    api, category, file = editing
    api.post(f"/api/files/{file}/notes", json={"notes": [{"front": "나라", "back": "country"}]})
    stranger = settings.data_dir / "korean/book1/03-daily-life/mine.json"
    stranger.parent.mkdir(parents=True, exist_ok=True)
    stranger.write_text("{}\n", encoding="utf-8")

    report = api.post("/api/export", json={}).json()
    assert report["root"] == str(settings.data_dir)
    assert report["notes"] == 1
    assert [f["path"].split("/")[-1] for f in report["files"]] == ["3-1-vocabulary.json"]
    assert report["unknown"] == [str(stranger)], "found, reported, left alone"
    assert stranger.is_file()

    written = json.loads(Path(report["files"][0]["path"]).read_text(encoding="utf-8"))
    assert written["format"] == "memo.datafile"
    assert [n["front"] for n in written["notes"]] == ["나라"]
    assert api.post("/api/export", json={"category_id": "cat_nope"}).status_code == 404


def test_a_staged_import_can_be_sent_to_another_category(api, sample_image):
    """The destination is a decision, not whichever row you pressed Add pages on."""
    job = _import(api, sample_image)
    elsewhere = api.post("/api/categories", json={"path": "korean/book2"}).json()

    moved = api.patch(f"/api/imports/{job['id']}", json={"category_id": elsewhere["id"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["category_id"] == elsewhere["id"]

    committed = api.post(f"/api/imports/{job['id']}/commit").json()
    files = api.get(f"/api/categories/{elsewhere['id']}/files").json()
    assert [f["id"] for f in files] == [committed["target_data_file_id"]]
    assert api.get(f"/api/categories/{job['category_id']}/files").json() == []


def test_moving_a_job_forgets_the_file_it_was_going_to_join(api, sample_image):
    first = _import(api, sample_image)
    file_id = api.post(f"/api/imports/{first['id']}/commit").json()["target_data_file_id"]
    second = _import(api, sample_image, into=file_id)
    elsewhere = api.post("/api/categories", json={"path": "korean/book2"}).json()

    moved = api.patch(f"/api/imports/{second['id']}", json={"category_id": elsewhere["id"]}).json()
    assert moved["target_data_file_id"] is None, "that file is in the category we left"

    joining_again = api.patch(f"/api/imports/{second['id']}", json={"target_data_file_id": file_id})
    assert joining_again.status_code == 409, "it is not in this category"
    assert api.patch(f"/api/imports/{second['id']}", json={"category_id": "cat_nope"}).status_code == 404


def test_a_committed_import_cannot_be_sent_anywhere(api, sample_image):
    job = _import(api, sample_image)
    api.post(f"/api/imports/{job['id']}/commit")
    elsewhere = api.post("/api/categories", json={"path": "korean/book2"}).json()
    assert api.patch(f"/api/imports/{job['id']}", json={"category_id": elsewhere["id"]}).status_code == 409


def test_a_staged_import_is_discarded_with_its_photos(api, sample_image, settings):
    job = _import(api, sample_image)
    photos = [settings.raw_dir / page["path"] for page in job["pages"]]
    assert photos and all(p.is_file() for p in photos)

    assert api.delete(f"/api/imports/{job['id']}").status_code == 204
    assert api.get(f"/api/imports/{job['id']}").status_code == 404
    assert not any(p.exists() for p in photos), "the pages went with the job"
    assert not photos[0].parent.exists(), "and so did its folder"
    assert api.delete(f"/api/imports/{job['id']}").status_code == 404


def test_a_committed_import_is_kept_because_the_notes_point_at_it(api, sample_image, settings):
    job = _import(api, sample_image)
    api.post(f"/api/imports/{job['id']}/commit")
    assert api.delete(f"/api/imports/{job['id']}").status_code == 409
    assert all((settings.raw_dir / page["path"]).is_file() for page in job["pages"])


def test_more_pages_can_be_added_to_the_file_an_earlier_import_made(api, sample_image):
    """PLAN 6, phase 2: a chapter photographed over several days is one data file."""
    first = _import(api, sample_image)
    file_id = api.post(f"/api/imports/{first['id']}/commit").json()["target_data_file_id"]
    notes = api.get(f"/api/files/{file_id}/notes").json()["notes"]

    second = _import(api, sample_image, into=file_id)
    assert second["target_data_file_id"] == file_id
    draft = second["draft"]
    draft["notes"] = draft["notes"][:2]
    api.put(f"/api/imports/{second['id']}/draft", json=draft)
    committed = api.post(f"/api/imports/{second['id']}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["target_data_file_id"] == file_id, "no second file was made"

    after = api.get(f"/api/files/{file_id}/notes").json()
    assert len(after["notes"]) == len(notes) + 2
    assert [n["id"] for n in after["notes"]][: len(notes)] == [n["id"] for n in notes]
    category_files = api.get(f"/api/categories/{after['file']['category_id']}/files").json()
    assert len(category_files) == 1

    missing = api.post(
        "/api/imports",
        data={"category_id": after["file"]["category_id"], "target_data_file_id": "df_nope"},
        files=[("files", ("vocab1.jpg", sample_image.open("rb"), "image/jpeg"))],
    )
    assert missing.status_code == 400


def test_a_csv_is_imported_without_any_model(api):
    """PLAN 6, phase 2: a file that says what its columns are needs no LLM."""
    category = api.post("/api/categories", json={"path": "korean/book2"}).json()
    csv = "front,back,group\n나라,country,Countries\n한국,Korea,Countries\n"
    response = api.post(
        "/api/imports",
        data={"category_id": category["id"]},
        files=[("files", ("words.csv", csv.encode(), "text/csv"))],
    )
    assert response.status_code == 202, response.text
    job = api.get(f"/api/imports/{response.json()['id']}").json()
    assert job["status"] == "review"
    assert job["importer"] == "csv"
    assert [n["front"] for n in job["draft"]["notes"]] == ["나라", "한국"]
    assert job["pages"][0]["status"] == "done"

    committed = api.post(f"/api/imports/{job['id']}/commit").json()
    notes = api.get(f"/api/files/{committed['target_data_file_id']}/notes").json()
    assert [n["back"] for n in notes["notes"]] == ["country", "Korea"]
    assert {n["status"] for n in notes["notes"]} == {"confirmed"}


def test_a_file_nothing_can_read_fails_with_a_reason(api):
    category = api.post("/api/categories", json={"path": "korean/book2"}).json()
    response = api.post(
        "/api/imports",
        data={"category_id": category["id"]},
        files=[("files", ("prose.txt", b"Just some prose.\nNo pairs here.\n", "text/plain"))],
    )
    job = api.get(f"/api/imports/{response.json()['id']}").json()
    assert job["status"] == "failed"
    assert "no separator" in job["error"]

    refused = api.post(
        "/api/imports",
        data={"category_id": category["id"]},
        files=[("files", ("notes.docx", b"PK", "application/octet-stream"))],
    )
    assert refused.status_code == 400
    assert "cannot import" in refused.text or "can import" in refused.text


def test_photos_and_data_files_cannot_be_mixed_in_one_import(api, sample_image):
    category = api.post("/api/categories", json={"path": "korean/book2"}).json()
    with sample_image.open("rb") as handle:
        response = api.post(
            "/api/imports",
            data={"category_id": category["id"]},
            files=[
                ("files", ("vocab1.jpg", handle, "image/jpeg")),
                ("files", ("words.csv", b"front,back\na,b\n", "text/csv")),
            ],
        )
    assert response.status_code == 400
    assert "not both" in response.json()["detail"]


# --- reading the collection (PLAN 6, phase 4) -------------------------------


def _answer_card(api, card, outcome="correct"):
    body = {"card_key": card["key"], "mode": "typed", "outcome": outcome}
    response = api.post("/api/practice/answer", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_sheet_marks_every_row_with_what_is_known_about_it(editing):
    api, category, file = editing
    api.post(
        f"/api/files/{file}/notes",
        json={"notes": [{"front": "나라", "back": "country"}, {"front": "한국", "back": "Korea"}]},
    )
    notes = api.get(f"/api/files/{file}/notes").json()["notes"]
    assert [n["progress"] for n in notes] == ["new", "new"]

    queue = api.get("/api/practice/queue", params={"category_id": category}).json()["cards"]
    for card in (c for c in queue if c["note_id"] == notes[0]["id"]):
        _answer_card(api, card)  # both directions of the first note

    marked = {n["front"]: n["progress"] for n in api.get(f"/api/files/{file}/notes").json()["notes"]}
    assert marked == {"나라": "learning", "한국": "new"}


def test_a_session_can_be_started_from_one_lesson_or_one_heading(editing):
    """The sheet's "practise this" buttons — the options still come from around it."""
    api, category, file = editing
    other = api.post(
        f"/api/categories/{category}/files", json={"title": "3-2", "default_type": "bidirectional"}
    ).json()
    api.post(
        f"/api/files/{file}/notes",
        json={
            "notes": [
                {"front": "나라", "back": "country", "group": "나라"},
                {"front": "한국", "back": "Korea", "group": "나라"},
                {"front": "의사", "back": "doctor", "group": "직업"},
            ]
        },
    )
    api.post(f"/api/files/{other['id']}/notes", json={"notes": [{"front": "책", "back": "book"}]})

    whole = api.get("/api/practice/queue", params={"category_id": category}).json()
    lesson = api.get("/api/practice/queue", params={"file_id": file}).json()
    heading = api.get("/api/practice/queue", params={"file_id": file, "group": "직업"}).json()

    assert len(whole["cards"]) == 8, "both files, both ways"
    assert {c["prompt"] for c in lesson["cards"]} == {"나라", "country", "한국", "Korea", "의사", "doctor"}
    assert {c["prompt"] for c in heading["cards"]} == {"의사", "doctor"}
    assert "book" in next(c for c in heading["cards"] if c["prompt"] == "의사")["distractors"], (
        "a heading of one note cannot fill four options from itself"
    )


def test_an_unknown_file_cannot_be_practised(api):
    assert api.get("/api/practice/queue", params={"file_id": "df_nope"}).status_code == 404


def test_progress_counts_the_tree_and_names_what_keeps_going_wrong(editing):
    api, category, file = editing
    api.post(
        f"/api/files/{file}/notes",
        json={"notes": [{"front": "나라", "back": "country"}, {"front": "한국", "back": "Korea"}]},
    )

    before = api.get("/api/progress").json()
    rows = {row["path"]: row for row in before["mastery"]}
    assert rows["korean"]["notes"] == 2, "the subject counts what is under it, a note once"
    assert rows["korean"]["new"] == 2
    assert rows["korean/book1/03-daily-life"]["depth"] == 2
    assert before["weak"] == [], "nothing has gone wrong yet"
    assert before["rule"]["known_points"] == 6, "the page says what the bars mean"
    assert before["rule"]["writing_points"] == 3
    assert [d["reviews"] for d in before["activity"]] == [0], "today, empty"

    queue = api.get("/api/practice/queue", params={"category_id": category}).json()["cards"]
    missed = next(c for c in queue if c["prompt"] == "나라")
    _answer_card(api, missed, "wrong")

    after = api.get("/api/progress").json()
    assert next(r for r in after["mastery"] if r["path"] == "korean")["learning"] == 0, (
        "one direction asked, so the note has not been met both ways yet"
    )
    assert [(w["prompt"], w["answer"], w["wrong"]) for w in after["weak"]] == [("나라", "country", 1)]
    assert after["weak"][0]["category_path"] == "korean/book1/03-daily-life"
    assert after["activity"][-1]["reviews"] == 1
    assert after["activity"][-1]["correct"] == 0


def test_the_bars_survive_switching_scheduler(editing):
    """What you know is read from the log, so it is not one algorithm's property."""
    api, category, file = editing
    api.post(f"/api/files/{file}/notes", json={"notes": [{"front": "나라", "back": "country"}]})
    for card in api.get("/api/practice/queue", params={"category_id": category}).json()["cards"]:
        _answer_card(api, card)

    used = api.get("/api/settings").json()["scheduler"]
    other = next(name for name in api.get("/api/settings").json()["schedulers"] if name != used)
    for name in (used, other):
        row = next(
            r
            for r in api.get("/api/progress", params={"scheduler": name}).json()["mastery"]
            if r["path"] == "korean"
        )
        assert (row["learning"], row["new"]) == (1, 0), f"{name}: the answers still count"
    assert api.get("/api/progress", params={"scheduler": "guesswork"}).status_code == 422


def test_reorganising_the_tree_keeps_every_answer(editing):
    """Progress is keyed on notes, not on paths (PLAN 5) — so a file can be
    moved into a subcategory of its own, and a category renamed above it,
    without costing a single review."""
    api, category, file = editing
    api.post(
        f"/api/files/{file}/notes",
        json={"notes": [{"front": "나라", "back": "country"}, {"front": "한국", "back": "Korea"}]},
    )
    for card in api.get("/api/practice/queue", params={"category_id": category}).json()["cards"]:
        _answer_card(api, card, "correct" if card["direction"] == "fwd" else "wrong")
    before = api.get("/api/progress").json()
    assert next(r for r in before["mastery"] if r["path"] == "korean")["learning"] == 2

    lesson = api.post("/api/categories", json={"path": "korean/book1/03-daily-life/3-1"}).json()
    assert api.patch(f"/api/files/{file}", json={"category_id": lesson["id"]}).status_code == 200
    assert api.patch(f"/api/categories/{category}", json={"slug": "daily-life"}).status_code == 200

    after = api.get("/api/progress").json()
    assert next(r for r in after["mastery"] if r["path"] == "korean")["learning"] == 2
    assert [(w["prompt"], w["wrong"]) for w in after["weak"]] == [
        (w["prompt"], w["wrong"]) for w in before["weak"]
    ], "the weak list is the same cards, under their new path"
    assert after["weak"][0]["category_path"].endswith("3-1")
    assert [n["progress"] for n in api.get(f"/api/files/{file}/notes").json()["notes"]] == [
        "learning",
        "learning",
    ], "and the sheet still marks them"


# --- serving the app itself (PLAN 5) ----------------------------------------


def test_the_app_shell_is_never_cached_but_its_chunks_are_kept(api, tmp_path, monkeypatch):
    """What makes a new build arrive, and makes the old one cost nothing to reopen."""
    from memo.api import app as module

    build = tmp_path / "build"
    (build / "_app" / "immutable").mkdir(parents=True)
    (build / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (build / "_app" / "immutable" / "chunk.Bq1xZ.js").write_text("export {}", encoding="utf-8")
    monkeypatch.setattr(module, "FRONTEND_BUILD", build)
    client = TestClient(create_app(Settings(var_dir=tmp_path / "var")))

    page = client.get("/")
    chunk = client.get("/_app/immutable/chunk.Bq1xZ.js")
    assert page.headers["cache-control"] == "no-cache"
    assert "immutable" in chunk.headers["cache-control"]


def _behind_proxy(tmp_path, peer: str) -> TestClient:
    """A gated app reached from `peer`, the way a proxy on this machine reaches it."""
    settings = Settings(
        var_dir=tmp_path / peer, auth_password_hash=hash_password("correct horse"), login_attempts=3
    )
    return TestClient(create_app(settings), client=(peer, 50000))


def test_a_device_behind_our_own_proxy_is_rate_limited_as_itself(tmp_path):
    """`tailscale serve` terminates TLS here and forwards from localhost, so
    without this every device on the tailnet would share one bucket (PLAN 5)."""
    api = _behind_proxy(tmp_path, "127.0.0.1")
    wrong = {"password": "nope"}
    for _ in range(4):
        api.post("/api/auth/login", json=wrong, headers={"x-forwarded-for": "100.64.0.9"})
    locked = api.post("/api/auth/login", json=wrong, headers={"x-forwarded-for": "100.64.0.9"})
    other = api.post("/api/auth/login", json=wrong, headers={"x-forwarded-for": "100.64.0.8"})
    assert locked.status_code == 429
    assert other.status_code == 401, "a different device has its own patience"


def test_a_stranger_cannot_name_their_own_bucket(tmp_path):
    """The header is only believed from a proxy on this machine. Otherwise anyone
    locked out could simply claim to be someone else."""
    api = _behind_proxy(tmp_path, "10.0.0.5")
    wrong = {"password": "nope"}
    for n in range(4):
        api.post("/api/auth/login", json=wrong, headers={"x-forwarded-for": f"1.2.3.{n}"})
    again = api.post("/api/auth/login", json=wrong, headers={"x-forwarded-for": "1.2.3.99"})
    assert again.status_code == 429


# --- progress is about words (PLAN 6, phase 4) ------------------------------


def test_the_progress_page_is_handed_words_not_just_counts(practising):
    """The strips: a glimpse of each list, so the page shows words on arrival."""
    api, category = practising
    body = api.get("/api/progress").json()

    assert body["set_aside"] == 0
    assert body["mastered"] == [], "nothing is mastered on the first day"
    assert len(body["unseen"]) == 6, "a strip's worth of words nobody has met"
    first = body["unseen"][0]
    assert first["prompt"] and first["answer"], "oriented, so the row reads one way round"
    assert first["since"] is None, "never answered, so it got nowhere at no time"


def test_the_whole_of_a_list_is_one_request_away(practising):
    api, category = practising
    body = api.get("/api/progress/words", params={"bucket": "new", "limit": 3}).json()
    assert body["bucket"] == "new"
    assert body["total"] > 3, "the count is the bucket, not the page"
    assert len(body["words"]) == 3

    page = api.get("/api/progress/words", params={"bucket": "new", "limit": 3, "offset": 3}).json()
    assert {w["card_key"] for w in page["words"]}.isdisjoint({w["card_key"] for w in body["words"]})


def test_a_lesson_in_full(editing):
    """The screen Progress drills down to: counts, headings, and the words by bucket."""
    api, category, file = editing
    api.post(
        f"/api/files/{file}/notes",
        json={
            "notes": [
                {"front": "나라", "back": "country", "group": "places"},
                {"front": "한국", "back": "Korea", "group": "places"},
                {"front": "네", "back": "yes"},
            ]
        },
    )
    for card in api.get("/api/practice/queue", params={"category_id": category}).json()["cards"]:
        if card["prompt"] in ("나라", "country"):
            _answer_card(api, card)

    body = api.get(f"/api/progress/files/{file}").json()
    assert (body["file"]["notes"], body["file"]["learning"], body["file"]["new"]) == (3, 1, 2)
    assert [(g["key"], g["notes"], g["learning"]) for g in body["groups"]] == [
        (None, 1, 0),
        ("places", 2, 1),
    ]
    assert set(body["words"]) == {"mastered", "known", "learning", "new"}
    assert [w["prompt"] for w in body["words"]["learning"]] == ["나라"]
    assert sum(len(found) for found in body["words"].values()) == body["file"]["notes"], (
        "the lists add up to the count"
    )
    assert api.get("/api/progress/files/nonsense").status_code == 404


def test_a_list_of_words_can_be_one_lesson_or_one_category(editing):
    api, category, file = editing
    api.post(f"/api/files/{file}/notes", json={"notes": [{"front": "나라", "back": "country"}]})
    by_file = api.get("/api/progress/words", params={"bucket": "new", "file": file}).json()
    by_category = api.get("/api/progress/words", params={"bucket": "new", "category": category}).json()
    assert by_file["total"] == by_category["total"] == 1
    assert api.get("/api/progress/words", params={"category": "nonsense"}).status_code == 404


def test_a_word_set_aside_can_be_found_again(practising):
    """Suspending used to put a word somewhere nothing in the app could look."""
    api, category = practising
    card = api.get("/api/practice/queue", params={"category_id": category}).json()["cards"][0]
    api.patch(f"/api/notes/{card['note_id']}", json={"suspended": True})

    assert api.get("/api/progress").json()["set_aside"] == 1, "one note, counted once"
    found = api.get("/api/progress/words", params={"bucket": "set-aside"}).json()
    assert {w["note_id"] for w in found["words"]} == {card["note_id"]}

    api.patch(f"/api/notes/{card['note_id']}", json={"suspended": False})
    assert api.get("/api/progress").json()["set_aside"] == 0


def test_there_is_no_such_bucket_as_nonsense(practising):
    api, _ = practising
    assert api.get("/api/progress/words", params={"bucket": "nonsense"}).status_code == 422


# --- the collection, looked over --------------------------------------------


def test_a_clean_collection_says_so(practising):
    api, _ = practising
    assert api.get("/api/collection/audit").json() == {
        "clean": True,
        "collisions": [],
        "duplicates": [],
        "one_sided": [],
        # Hints rather than faults, so they do not bear on `clean` — but the API
        # computed them and threw them away until now, and `near` is the same
        # signal as "what else do I know that means this".
        "near": [],
        "resolved": [],
    }


def test_two_words_glossed_the_same_are_an_unanswerable_question(practising):
    """The extractor produces these honestly, and the CLI was the only witness."""
    api, category = practising
    file = api.get(f"/api/categories/{category}/files").json()[0]["id"]
    api.post(
        f"/api/files/{file}/notes",
        json={"notes": [{"front": "밑", "back": "under"}, {"front": "아래", "back": "under"}]},
    )

    report = api.get("/api/collection/audit").json()
    assert report["clean"] is False
    assert [f["key"] for f in report["collisions"]] == ["under"]
    assert {n["front"] for n in report["collisions"][0]["notes"]} == {"밑", "아래"}
    assert all(n["data_file_id"] == file for n in report["collisions"][0]["notes"]), "so it can link"


def test_a_collision_both_notes_accept_is_not_a_finding(practising):
    """Either answer is taken whichever is asked, so the question is answerable."""
    api, category = practising
    file = api.get(f"/api/categories/{category}/files").json()[0]["id"]
    added = api.post(
        f"/api/files/{file}/notes",
        json={"notes": [{"front": "밑", "back": "under"}, {"front": "아래", "back": "under"}]},
    ).json()["notes"]
    pair = {n["front"]: n["id"] for n in added if n["back"] == "under"}
    api.patch(f"/api/notes/{pair['밑']}", json={"accept": {"front": ["아래"]}})
    api.patch(f"/api/notes/{pair['아래']}", json={"accept": {"front": ["밑"]}})

    assert api.get("/api/collection/audit").json()["clean"] is True


# --- an answer is recorded under the scheduler the queue offered it with -----


def test_an_answer_follows_the_category_s_own_scheduler(practising):
    """The queue honours it, so the answer has to, or the two write to different
    caches and the session reads a state nothing is updating."""
    api, category = practising
    with api.app.state.sessions() as session:
        row = session.get(Category, category)
        row.config = {"practice": {"scheduler": "sm2"}}
        session.commit()

    queue = api.get("/api/practice/queue", params={"category_id": category}).json()
    assert queue["scheduler"] == "sm2"
    card = queue["cards"][0]

    # No scheduler named: the card's own category decides, not the profile default.
    answered = api.post(
        "/api/practice/answer",
        json={"card_key": card["key"], "mode": "typed", "outcome": "correct"},
    ).json()
    assert answered["scheduler"] == "sm2"


def test_the_queue_takes_the_timezone_the_pace_is_counted_in(practising):
    api, category = practising
    body = api.get("/api/practice/queue", params={"category_id": category, "tz_offset": 540})
    assert body.status_code == 200
