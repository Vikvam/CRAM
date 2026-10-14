"""A named set of words, and a dated focus on it (PLAN 6, phase 4).

The tests that matter most here are the ones about what a list *cannot* do. A
list reorders a queue; if it ever reached ``card_state`` or ``review_log`` it
would be rewriting history to win an argument about today, and nothing on screen
would show it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from memo.api import create_app
from memo.config import Settings

SOON = (datetime.now(UTC) + timedelta(days=4)).isoformat()


def _ahead(days: int = 3) -> datetime:
    """A focus date still to come."""
    return datetime.now(UTC) + timedelta(days=days)


GONE = (datetime.now(UTC) - timedelta(days=1)).isoformat()


@pytest.fixture
def api(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(var_dir=tmp_path / "var", data_dir=tmp_path / "data")))


@pytest.fixture
def stocked(api) -> tuple[TestClient, str, list[dict]]:
    """A lesson of eight words under two headings: api, file id, notes."""
    category = api.post("/api/categories", json={"path": "korean/book1/03-daily-life"}).json()
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
                {"front": "위", "back": "above", "group": "위치"},
                {"front": "밑", "back": "under", "group": "위치"},
                {"front": "옆", "back": "next to", "group": "위치"},
                {"front": "앞", "back": "in front", "group": "위치"},
                {"front": "학교", "back": "school", "group": "장소"},
                {"front": "교실", "back": "classroom", "group": "장소"},
                {"front": "서점", "back": "bookshop", "group": "장소"},
                {"front": "회사", "back": "company", "group": "장소"},
            ]
        },
    )
    assert created.status_code == 201, created.text
    notes = api.get(f"/api/files/{file['id']}/notes").json()["notes"]
    return api, file["id"], notes


def _make(api: TestClient, name="Friday test", **body) -> dict:
    made = api.post("/api/lists", json={"name": name, **body})
    assert made.status_code == 201, made.text
    return made.json()


# --- the set itself ---------------------------------------------------------


def test_a_list_holds_words_without_moving_them(stocked):
    """The whole premise: membership is a selection, not a place."""
    api, file, notes = stocked
    made = _make(api)
    before = api.get(f"/api/files/{file}/notes").json()["notes"]
    filled = api.post(f"/api/lists/{made['id']}/notes", json={"note_ids": [n["id"] for n in notes[:3]]})
    assert filled.status_code == 200, filled.text
    assert filled.json()["count"] == 3
    after = api.get(f"/api/files/{file}/notes").json()["notes"]
    assert [n["id"] for n in after] == [n["id"] for n in before], "nothing moved out of the lesson"
    # Null, not "normal": on a note the ordinary middle is the absence of a mark.
    assert all(n["priority"] is None for n in after), "and no mark was written"


def test_a_whole_heading_goes_on_in_one_call(stocked):
    """The bulk gesture: a heading is already a set you think in."""
    api, file, _ = stocked
    made = _make(api)
    filled = api.post(f"/api/lists/{made['id']}/notes", json={"file_id": file, "group": "장소"})
    assert filled.status_code == 200, filled.text
    assert {word["front"] for word in filled.json()["words"]} == {"학교", "교실", "서점", "회사"}


def test_a_whole_lesson_goes_on_in_one_call(stocked):
    api, file, _ = stocked
    made = _make(api)
    filled = api.post(f"/api/lists/{made['id']}/notes", json={"file_id": file})
    assert filled.json()["count"] == 8


def test_adding_a_word_twice_is_not_an_error(stocked):
    """Half the point of searching is not remembering whether you dealt with it."""
    api, _, notes = stocked
    made = _make(api)
    first = [notes[0]["id"]]
    api.post(f"/api/lists/{made['id']}/notes", json={"note_ids": first})
    again = api.post(f"/api/lists/{made['id']}/notes", json={"note_ids": first})
    assert again.status_code == 200
    assert again.json()["count"] == 1


def test_a_words_order_on_the_list_is_the_order_it_was_added(stocked):
    api, _, notes = stocked
    made = _make(api)
    wanted = [notes[4]["id"], notes[1]["id"], notes[6]["id"]]
    added = api.post(f"/api/lists/{made['id']}/notes", json={"note_ids": wanted})
    assert [word["note_id"] for word in added.json()["words"]] == wanted


def test_two_lists_cannot_share_a_name(api):
    _make(api)
    clash = api.post("/api/lists", json={"name": "Friday test"})
    assert clash.status_code == 422
    assert "already a list" in clash.text


def test_a_list_needs_a_name(api):
    assert api.post("/api/lists", json={"name": "   "}).status_code == 422


def test_deleting_a_list_leaves_the_words_alone(stocked):
    api, file, notes = stocked
    made = _make(api)
    api.post(f"/api/lists/{made['id']}/notes", json={"file_id": file})
    assert api.delete(f"/api/lists/{made['id']}").status_code == 204
    assert api.get(f"/api/lists/{made['id']}").status_code == 404
    assert len(api.get(f"/api/files/{file}/notes").json()["notes"]) == 8
    assert api.get("/api/lists").json()["lists"] == []


def test_a_word_can_be_taken_off(stocked):
    api, _, notes = stocked
    made = _make(api)
    api.post(f"/api/lists/{made['id']}/notes", json={"note_ids": [n["id"] for n in notes[:3]]})
    off = api.delete(f"/api/lists/{made['id']}/notes/{notes[1]['id']}")
    assert off.status_code == 200
    assert off.json()["count"] == 2


# --- the focus, which is the half that expires ------------------------------


def test_a_focus_is_only_on_while_its_date_is_ahead(api):
    coming = _make(api, name="Friday", focus_until=SOON)
    assert coming["focused"] is True
    been = _make(api, name="Last week", focus_until=GONE)
    assert been["focused"] is False, "a date gone by is not a focus"
    plain = _make(api, name="Someday")
    assert (plain["focused"], plain["focus_until"]) == (False, None)


def test_a_focus_can_be_ended_and_re_dated_without_touching_the_list(stocked):
    api, file, _ = stocked
    made = _make(api, focus_until=SOON)
    api.post(f"/api/lists/{made['id']}/notes", json={"file_id": file})
    ended = api.patch(f"/api/lists/{made['id']}", json={"focus_until": None})
    assert (ended.json()["focused"], ended.json()["count"]) == (False, 8), "the words stayed"
    again = api.patch(f"/api/lists/{made['id']}", json={"focus_until": SOON})
    assert again.json()["focused"] is True


def test_a_field_left_out_of_a_patch_is_left_alone(api):
    """Null ends a focus; absent keeps it. They cannot be the same thing."""
    made = _make(api, focus_until=SOON, note="chapter 3")
    renamed = api.patch(f"/api/lists/{made['id']}", json={"name": "Monday test"})
    assert renamed.json()["name"] == "Monday test"
    assert renamed.json()["focused"] is True, "renaming did not end the focus"
    assert renamed.json()["note"] == "chapter 3"


def test_focused_lists_are_listed_first(api):
    _make(api, name="Someday")
    _make(api, name="Friday", focus_until=SOON)
    assert [one["name"] for one in api.get("/api/lists").json()["lists"]][0] == "Friday"


def test_one_persons_list_is_not_another_ones(api, tmp_path):
    """Keyed by profile like everything else, so this is only a 404 today."""
    made = _make(api)
    assert api.get(f"/api/lists/{made['id']}").status_code == 200
    assert api.get("/api/lists/wl_nonesuch").status_code == 404
    assert api.patch("/api/lists/wl_nonesuch", json={"name": "x"}).status_code == 404
    assert api.delete("/api/lists/wl_nonesuch").status_code == 404


def test_a_list_cannot_be_filled_with_a_word_that_is_not_there(stocked):
    api, _, _ = stocked
    made = _make(api)
    missing = api.post(f"/api/lists/{made['id']}/notes", json={"note_ids": ["n_nonesuch"]})
    assert missing.status_code == 404
    assert api.post(f"/api/lists/{made['id']}/notes", json={}).status_code == 422


# --- how a list meets the queue ---------------------------------------------
#
# This is the half that had to be got right. A list changes which cards are
# asked and in what order; it must not be able to change what a card's history
# says, or which `card_state` row the session reads.

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from memo.collection.categories import ensure_category  # noqa: E402
from memo.collection.editing import create_file, create_notes, update_note  # noqa: E402
from memo.collection.lists import add_notes, create_list, focused  # noqa: E402
from memo.collection.profiles import get_or_create_profile  # noqa: E402
from memo.db.models import CardState as CardStateRow  # noqa: E402
from memo.db.models import Note as NoteRow  # noqa: E402
from memo.db.models import ReviewLog  # noqa: E402
from memo.practice.priority import FOCUS_PUSH  # noqa: E402
from memo.practice.service import (  # noqa: E402
    FOCUS_SHARE,
    AnswerIn,
    due_queue,
    record_answer,
    replay,
    resolve_scheduler_name,
)


def _lesson(session: Session, titles: list[str]) -> tuple[str, list[NoteRow]]:
    category = ensure_category(session, "korean")
    file = create_file(session, category, title="lesson", default_type="directional")
    return file.id, create_notes(session, file, [{"front": t, "back": f"{t}-en"} for t in titles])


def _answer(session: Session, keys: list[str], *, outcome: str = "correct", at=None) -> None:
    profile = get_or_create_profile(session)
    name = resolve_scheduler_name(session, profile, None, None)
    for key in keys:
        record_answer(
            session, profile, AnswerIn(card_key=key, mode="typed", outcome=outcome, at=at), scheduler=name
        )
    session.flush()


def test_a_drill_asks_every_word_on_the_list_due_or_not(session):
    """A test is coming and the schedule does not know that."""
    file_id, notes = _lesson(session, [f"w{i}" for i in range(10)])
    profile = get_or_create_profile(session)
    keys = [f"{n.id}:fwd" for n in notes]
    _answer(session, keys)  # every one now scheduled for later
    assert due_queue(session, profile, file_id=file_id).due_count == 0

    made = create_list(session, profile, name="Friday")
    add_notes(session, profile, made.id, note_ids=[n.id for n in notes[:6]])
    drilled = due_queue(session, profile, list_id=made.id)
    assert {c.key for c in drilled.cards} == set(keys[:6]), "the whole list, and only the list"
    assert all(c.early for c in drilled.cards), "and it says they were brought forward"


def test_drilling_a_word_you_know_cannot_cost_you_the_interval(session):
    """``schedule_answer`` already guarantees this; a drill must not route round it."""
    file_id, notes = _lesson(session, ["하나", "둘"])
    profile = get_or_create_profile(session)
    keys = [f"{n.id}:fwd" for n in notes]
    name = resolve_scheduler_name(session, profile, None, None)
    for step in range(4):  # earn a real interval
        _answer(session, keys, at=datetime.now(UTC) - timedelta(days=12) + step * timedelta(days=3))

    def due_of(key: str):
        return (
            session.scalars(
                select(CardStateRow).where(
                    CardStateRow.profile_id == profile.id,
                    CardStateRow.card_key == key,
                    CardStateRow.scheduler == name,
                )
            )
            .one()
            .due
        )

    before = {key: due_of(key) for key in keys}
    assert all(d - datetime.now(UTC) > timedelta(days=1) for d in before.values()), "well ahead"

    made = create_list(session, profile, name="Friday")
    add_notes(session, profile, made.id, note_ids=[n.id for n in notes])
    drilled = due_queue(session, profile, list_id=made.id)
    _answer(session, [c.key for c in drilled.cards])
    assert {key: due_of(key) for key in keys} == before, "counted, but not rescheduled"


def test_a_focus_leads_a_sitting_without_taking_it(session):
    """The reserved share, which is the whole reason a focus is safe."""
    file_id, notes = _lesson(session, [f"w{i}" for i in range(40)])
    profile = get_or_create_profile(session)
    made = create_list(session, profile, name="Friday", focus_until=_ahead())
    on_list = [n.id for n in notes[:30]]
    add_notes(session, profile, made.id, note_ids=on_list)

    found = due_queue(session, profile, file_id=file_id, limit=20)
    assert len(found.cards) == 20
    held = [c for c in found.cards if c.note_id in set(on_list)]
    assert len(held) == int(20 * FOCUS_SHARE), "half the sitting, no more"
    assert len(found.cards) - len(held) == 10, "and the rest of the collection still gets a look"


def test_a_focus_smaller_than_its_share_gives_the_rest_back(session):
    file_id, notes = _lesson(session, [f"w{i}" for i in range(40)])
    profile = get_or_create_profile(session)
    made = create_list(session, profile, name="Friday", focus_until=_ahead())
    add_notes(session, profile, made.id, note_ids=[n.id for n in notes[:3]])

    found = due_queue(session, profile, file_id=file_id, limit=20)
    assert len(found.cards) == 20, "the sitting is still the size that was asked for"


def test_a_focused_word_says_which_list_pushed_it_and_claims_no_mark(session):
    file_id, notes = _lesson(session, [f"w{i}" for i in range(6)])
    profile = get_or_create_profile(session)
    made = create_list(session, profile, name="Friday test", focus_until=_ahead())
    add_notes(session, profile, made.id, note_ids=[notes[0].id])

    found = due_queue(session, profile, file_id=file_id)
    pushed = next(c for c in found.cards if c.note_id == notes[0].id)
    assert pushed.focus == "Friday test"
    assert pushed.priority == "normal", "a list is not a mark and must not read as one"
    assert pushed.twice is False, "one slot per word: twenty of these must not be forty"
    assert all(c.focus is None for c in found.cards if c.note_id != notes[0].id)


def test_a_mark_and_a_focus_compose_rather_than_overrule(session):
    file_id, notes = _lesson(session, [f"w{i}" for i in range(6)])
    profile = get_or_create_profile(session)
    update_note(session, notes[0], {"priority": "crucial"})
    made = create_list(session, profile, name="Friday", focus_until=_ahead())
    add_notes(session, profile, made.id, note_ids=[notes[0].id, notes[1].id])

    found = due_queue(session, profile, file_id=file_id)
    crucial = next(c for c in found.cards if c.note_id == notes[0].id)
    plain = next(c for c in found.cards if c.note_id == notes[1].id)
    assert (crucial.priority, crucial.twice) == ("crucial", True), "it kept its own second ask"
    assert (plain.priority, plain.twice) == ("normal", False)


def test_a_focus_that_has_passed_pushes_nothing(session):
    file_id, notes = _lesson(session, [f"w{i}" for i in range(6)])
    profile = get_or_create_profile(session)
    made = create_list(session, profile, name="Last week", focus_until=_ahead(-1))
    add_notes(session, profile, made.id, note_ids=[n.id for n in notes])

    assert focused(session, profile) == set()
    found = due_queue(session, profile, file_id=file_id)
    assert all(c.focus is None for c in found.cards), "the push left on the date, unasked"
    # ...and the list is still there to drill.
    assert len(due_queue(session, profile, list_id=made.id).cards) == 6


def test_a_focused_word_damps_to_nothing_once_mastered(session):
    """A test needs the words you have not got."""
    assert FOCUS_PUSH["mastered"] == 0
    file_id, notes = _lesson(session, ["하나", "둘", "셋"])
    profile = get_or_create_profile(session)
    made = create_list(session, profile, name="Friday", focus_until=_ahead())
    add_notes(session, profile, made.id, note_ids=[notes[0].id])
    key = f"{notes[0].id}:fwd"
    start = datetime.now(UTC) - timedelta(days=2)
    for step in range(4):
        _answer(session, [key], at=start + step * timedelta(hours=9))

    found = due_queue(session, profile, file_id=file_id)
    mastered = next(c for c in found.cards if c.key == key)
    assert mastered.focus is None, "nothing left to say: the push is gone"


def test_a_list_never_reaches_a_cards_history(session):
    """The claim the whole design rests on."""
    file_id, notes = _lesson(session, ["하나", "둘"])
    profile = get_or_create_profile(session)
    keys = [f"{n.id}:fwd" for n in notes]
    made = create_list(session, profile, name="Friday", focus_until=_ahead())
    add_notes(session, profile, made.id, note_ids=[n.id for n in notes])

    drilled = due_queue(session, profile, list_id=made.id)
    _answer(session, [c.key for c in drilled.cards])
    name = resolve_scheduler_name(session, profile, None, None)
    rows = session.scalars(select(ReviewLog).where(ReviewLog.profile_id == profile.id)).all()
    assert rows, "the answers were recorded"
    assert not any("list" in (c.name or "") for c in ReviewLog.__table__.columns), (
        "no column on the log could hold a list"
    )

    # Everything that schedules, which is everything except the FSRS bag's own
    # ``card_id`` — that is stamped from the clock on each fresh card, so it
    # differs between two replays of one log and nothing reads it.
    def scheduled(key: str) -> dict:
        state = replay(session, profile, key, name)
        bag = {k: v for k, v in state.data.items() if k != "card_id"}
        return {**state.dump(), "data": bag}

    after = {key: scheduled(key) for key in keys}

    # Delete the list; replaying the same log must reach the same state.
    session.delete(made)
    session.flush()
    assert {key: scheduled(key) for key in keys} == after


def test_a_drill_does_not_change_which_scheduler_the_session_reads(session):
    """A list is not a category, so it cannot move a card to another state row."""
    file_id, notes = _lesson(session, ["하나", "둘"])
    profile = get_or_create_profile(session)
    made = create_list(session, profile, name="Friday")
    add_notes(session, profile, made.id, note_ids=[n.id for n in notes])
    ordinary = due_queue(session, profile, file_id=file_id).scheduler
    assert due_queue(session, profile, list_id=made.id).scheduler == ordinary


def test_a_focus_brings_its_words_forward_from_next_week(session):
    """A test on Friday is not something the schedule knows about."""
    file_id, notes = _lesson(session, [f"w{i}" for i in range(20)])
    profile = get_or_create_profile(session)
    keys = [f"{n.id}:fwd" for n in notes]
    _answer(session, keys)  # everything now scheduled for later
    assert due_queue(session, profile, file_id=file_id, limit=10).due_count == 0

    made = create_list(session, profile, name="Friday", focus_until=_ahead())
    on_list = [n.id for n in notes[:4]]
    add_notes(session, profile, made.id, note_ids=on_list)

    found = due_queue(session, profile, file_id=file_id, limit=10, ahead=False)
    held = [c for c in found.cards if c.note_id in set(on_list)]
    assert len(held) == 4, "its words came up although none of them was due"
    assert all(c.early for c in held), "and answering one cannot cost it its interval"


def test_a_sitting_is_still_exactly_the_size_that_was_asked_for(session):
    """The focus takes a share of the sitting, never an extra helping on top."""
    file_id, notes = _lesson(session, [f"w{i}" for i in range(60)])
    profile = get_or_create_profile(session)
    made = create_list(session, profile, name="Friday", focus_until=_ahead())
    add_notes(session, profile, made.id, note_ids=[n.id for n in notes[:40]])
    for size in (10, 20, 40):
        assert len(due_queue(session, profile, file_id=file_id, limit=size).cards) == size


# --- a drill without a list --------------------------------------------------
#
# The same coverage, asked for from the setup screen instead of from a list.
# `list_id` now narrows the scope and implies a drill; `drill` is the drill on
# its own. Neither is a scheduler, which is the property the last test here
# pins down for the general case as well as the list one.


def test_a_drill_asks_everything_in_scope_due_or_not(session):
    """Practice rescues an empty scope up to ``ahead_to``; a drill covers it."""
    file_id, notes = _lesson(session, [f"w{i}" for i in range(30)])
    profile = get_or_create_profile(session)
    keys = [f"{n.id}:fwd" for n in notes]
    _answer(session, keys)  # every one now scheduled for later

    practice = due_queue(session, profile, file_id=file_id)
    assert practice.due_count == 0 and practice.new_count == 0, "nothing the schedule wants"
    assert len(practice.cards) == 20, "practice still rescues the scope, but only to ahead_to"

    drilled = due_queue(session, profile, file_id=file_id, drill=True)
    assert {c.key for c in drilled.cards} == set(keys), "all thirty, due or not"
    assert all(c.early for c in drilled.cards), "and each says it was brought forward"


def test_a_drill_is_still_the_size_you_asked_for(session):
    file_id, notes = _lesson(session, [f"w{i}" for i in range(30)])
    profile = get_or_create_profile(session)
    _answer(session, [f"{n.id}:fwd" for n in notes])

    assert len(due_queue(session, profile, file_id=file_id, drill=True, limit=12).cards) == 12
    assert len(due_queue(session, profile, file_id=file_id, drill=True).cards) == 30


def test_a_drill_stays_inside_the_scope_it_was_given(session):
    """The whole point of drilling one heading is that it is one heading."""
    file_id, notes = _lesson(session, [f"w{i}" for i in range(6)])
    other_file, other_notes = _lesson(session, ["elsewhere"])
    profile = get_or_create_profile(session)
    _answer(session, [f"{n.id}:fwd" for n in (*notes, *other_notes)])

    drilled = due_queue(session, profile, file_id=file_id, drill=True)
    assert {c.key for c in drilled.cards} == {f"{n.id}:fwd" for n in notes}
    assert f"{other_notes[0].id}:fwd" not in {c.key for c in drilled.cards}
    assert other_file != file_id


def test_drilling_without_a_list_cannot_cost_you_an_interval_either(session):
    """The same guarantee the list drill has, now that `early` is set elsewhere."""
    file_id, notes = _lesson(session, ["하나", "둘"])
    profile = get_or_create_profile(session)
    keys = [f"{n.id}:fwd" for n in notes]
    name = resolve_scheduler_name(session, profile, None, None)
    for step in range(4):  # earn a real interval
        _answer(session, keys, at=datetime.now(UTC) - timedelta(days=12) + step * timedelta(days=3))

    def due_of(key: str):
        return (
            session.scalars(
                select(CardStateRow).where(
                    CardStateRow.profile_id == profile.id,
                    CardStateRow.card_key == key,
                    CardStateRow.scheduler == name,
                )
            )
            .one()
            .due
        )

    before = {key: due_of(key) for key in keys}
    assert all(d - datetime.now(UTC) > timedelta(days=1) for d in before.values()), "well ahead"

    drilled = due_queue(session, profile, file_id=file_id, drill=True)
    _answer(session, [c.key for c in drilled.cards])
    assert {key: due_of(key) for key in keys} == before, "counted, but not rescheduled"


def test_a_drill_reads_and_writes_the_same_card_state_as_practice(session):
    """A sitting style is not a scheduler: `card_state` is keyed by that name."""
    file_id, notes = _lesson(session, ["하나", "둘"])
    profile = get_or_create_profile(session)
    keys = [f"{n.id}:fwd" for n in notes]
    _answer(session, keys)
    name = resolve_scheduler_name(session, profile, None, None)

    drilled = due_queue(session, profile, file_id=file_id, drill=True)
    assert drilled.scheduler == name
    assert {c.state["due"] for c in drilled.cards if c.state}, "it can see what practice wrote"

    rows = session.scalars(select(CardStateRow).where(CardStateRow.profile_id == profile.id)).all()
    assert {r.scheduler for r in rows} == {name}, "one row per card, not one per style"
    assert len(rows) == len(keys)


# --- asking a note one way round ---------------------------------------------
#
# A two-sided note makes two cards; this chooses which of them a sitting gets.
# Nothing in it knows what either side holds, so every test here is about cards
# and directions and never about what is written on them.


def _both(
    session: Session, titles: list[str], *, slug: str = "two-way", groups: list[str] | None = None
) -> tuple[str, list[NoteRow]]:
    """A file of two-sided notes, so every note has a fwd *and* a rev card.

    Headings are given at creation rather than patched on afterwards: a note
    whose ``group`` was read before it was set keeps the loaded relationship,
    and the test would be asserting against a stale one.
    """
    category = ensure_category(session, "korean")
    file = create_file(session, category, title=slug, slug=slug, default_type="bidirectional")
    items: list[dict] = [{"front": t, "back": f"{t}-b"} for t in titles]
    for item, key in zip(items, groups or [], strict=False):
        item["group"] = key
    return file.id, create_notes(session, file, items)


def test_a_direction_asks_one_side_and_the_scope_says_which_it_has(session):
    file_id, notes = _both(session, [f"w{i}" for i in range(5)])
    profile = get_or_create_profile(session)

    both = due_queue(session, profile, file_id=file_id)
    assert both.ways == {"fwd": 5, "rev": 5}
    assert len(both.cards) == 10

    for way in ("fwd", "rev"):
        only = due_queue(session, profile, file_id=file_id, direction=way)
        assert {c.direction for c in only.cards} == {way}
        assert len(only.cards) == 5
        assert only.ways == {"fwd": 5, "rev": 5}, "the scope is counted before the filter"
        assert {c.note_id for c in only.cards} == {n.id for n in notes}, "every note, once"


def test_a_one_way_note_is_absent_rather_than_asked_backwards(session):
    one_id, one = _lesson(session, ["alpha", "beta"])  # directional
    two_id, two = _both(session, ["gamma"], slug="pair")
    profile = get_or_create_profile(session)

    scope = due_queue(session, profile)
    assert scope.ways == {"fwd": 3, "rev": 1}

    forward = due_queue(session, profile, direction="fwd")
    assert {c.note_id for c in forward.cards} == {one[0].id, one[1].id, two[0].id}

    back = due_queue(session, profile, direction="rev")
    assert {c.note_id for c in back.cards} == {two[0].id}, "the one-way notes have no back"
    assert one_id != two_id


def test_a_scope_with_nothing_to_choose_says_so(session):
    """One entry is how the queue tells the screen not to offer a choice."""
    file_id, _ = _lesson(session, ["alpha", "beta"])
    profile = get_or_create_profile(session)
    assert due_queue(session, profile, file_id=file_id).ways == {"fwd": 2}


def test_distractors_still_come_from_the_whole_subtree_under_a_filter(session):
    """Half a pool is not four plausible wrong options."""
    file_id, _ = _both(session, [f"w{i}" for i in range(8)])
    profile = get_or_create_profile(session)
    cards = due_queue(session, profile, file_id=file_id, direction="fwd", modes=["choice"]).cards
    offered = {d for c in cards for d in c.distractors}
    backs = {f"w{i}-b" for i in range(8)}
    assert offered & backs, "the other side's answers are still available as distractors"


def test_a_direction_composes_with_a_drill_and_with_a_heading(session):
    file_id, notes = _both(session, [f"w{i}" for i in range(6)], groups=["one"] + ["two"] * 5)
    profile = get_or_create_profile(session)
    _answer(session, [f"{n.id}:fwd" for n in notes])
    _answer(session, [f"{n.id}:rev" for n in notes])

    drilled = due_queue(session, profile, file_id=file_id, drill=True, direction="rev")
    assert {c.direction for c in drilled.cards} == {"rev"}
    assert len(drilled.cards) == 6, "everything in scope, one way round"
    assert all(c.early for c in drilled.cards)

    narrow = due_queue(session, profile, file_id=file_id, group="one", drill=True, direction="rev")
    assert [c.note_id for c in narrow.cards] == [notes[0].id]
    assert narrow.ways == {"fwd": 1, "rev": 1}, "counted within the heading, not the file"
