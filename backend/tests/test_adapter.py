"""extraction → storage (PLAN 3.6), pinned against the hand-checked fixture."""

from __future__ import annotations

import json

from memo.models.adapter import Page, to_datafile
from memo.models.datafile import NoteType
from memo.models.extraction import (
    Confidence,
    ExtractedContext,
    ExtractedGroup,
    ExtractedItem,
    ExtractionResult,
)


def _item(front: str, back: str, **kw) -> ExtractedItem:
    return ExtractedItem(
        group=kw.pop("group", None),
        front=front,
        back=back,
        front_accepted=kw.pop("front_accepted", []),
        back_accepted=kw.pop("back_accepted", []),
        note=kw.pop("note", None),
        confidence=kw.pop("confidence", Confidence.HIGH),
    )


def _result(items, **kw) -> ExtractionResult:
    return ExtractionResult(
        title_native=kw.pop("title_native", None),
        title_translated=kw.pop("title_translated", None),
        context=kw.pop("context", []),
        groups=kw.pop("groups", []),
        items=items,
        unreadable=kw.pop("unreadable", []),
    )


def _normalise(raw: dict) -> dict:
    """IDs and timestamps are assigned per run; everything else must match."""
    raw = json.loads(json.dumps(raw))
    raw["id"] = "df_X"
    for index, note in enumerate(raw.get("notes", [])):
        note["id"] = f"n_X{index}"
    raw.get("source", {}).get("import", {}).pop("at", None)
    raw.get("source", {}).get("import", {}).pop("job_id", None)
    return raw


def test_the_sample_page_adapts_to_the_golden_fixture(vocab1_extraction, vocab1_raw):
    """The acceptance fixture for phase 0 (PLAN 6)."""
    produced = to_datafile(
        [Page(vocab1_extraction, number=6, file="raw/vocab1.jpg")],
        profile="korean-textbook-vocab",
        model="fixture",
        prompt_version=1,
        default_type=NoteType.BIDIRECTIONAL,
        front_lang="ko",
        back_lang="en",
    )
    assert _normalise(produced.dumps()) == _normalise(vocab1_raw)


def test_ids_are_assigned_by_us_and_are_unique(vocab1_extraction):
    datafile = to_datafile([Page(vocab1_extraction)])
    ids = [note.id for note in datafile.notes]
    assert all(i and i.startswith("n_") for i in ids)
    assert len(set(ids)) == len(ids)
    assert datafile.id and datafile.id.startswith("df_")


def test_extracted_notes_start_unverified(vocab1_extraction):
    datafile = to_datafile([Page(vocab1_extraction)])
    assert {note.status for note in datafile.notes} == {"unverified"}


def test_multi_valued_meanings_become_explicit_accepted_answers(vocab1_extraction):
    datafile = to_datafile([Page(vocab1_extraction)])
    note = next(n for n in datafile.notes if n.front == "어느")
    assert note.accept is not None and note.accept.back == ["what", "which"]


def test_an_accepted_answer_equal_to_the_shown_one_is_dropped():
    datafile = to_datafile([Page(_result([_item("네", "yes", back_accepted=["yes", " Yes "])]))])
    assert datafile.notes[0].accept is None, "adds nothing beyond the displayed answer"


def test_footnote_markers_are_stripped_from_the_term():
    datafile = to_datafile([Page(_result([_item("-씨¹", "Mr., Ms.", note="…")]))])
    assert datafile.notes[0].front == "-씨"


def test_pages_merge_in_order_and_keep_their_page_number():
    pages = [
        Page(_result([_item("러시아", "Russia")]), number=6),
        Page(_result([_item("중국", "China")]), number=7),
    ]
    datafile = to_datafile(pages)
    assert [(n.front, n.page) for n in datafile.notes] == [("러시아", 6), ("중국", 7)]


def test_a_pair_photographed_twice_is_stored_once():
    pages = [
        Page(_result([_item("러시아", "Russia")]), number=6),
        Page(_result([_item(" 러시아 ", "russia"), _item("중국", "China")]), number=7),
    ]
    datafile = to_datafile(pages)
    assert [n.front for n in datafile.notes] == ["러시아", "중국"]


def test_a_group_heading_carries_across_a_page_break():
    groups = [ExtractedGroup(key="countries", label_native="나라", label_translated="Countries")]
    pages = [
        Page(_result([_item("러시아", "Russia", group="countries")], groups=groups), number=6),
        Page(_result([_item("중국", "China", group="countries")]), number=7),
    ]
    datafile = to_datafile(pages, front_lang="ko")
    assert [g.id for g in datafile.groups] == ["countries"]
    assert {n.group for n in datafile.notes} == {"countries"}


def test_a_group_reference_with_no_heading_is_dropped_not_dangling():
    datafile = to_datafile([Page(_result([_item("러시아", "Russia", group="ghost")]))])
    assert datafile.notes[0].group is None


def test_labels_are_keyed_by_the_language_code():
    groups = [ExtractedGroup(key="countries", label_native="나라", label_translated="Countries")]
    datafile = to_datafile([Page(_result([], groups=groups))], front_lang="ko")
    assert datafile.groups[0].label == {"ko": "나라", "en": "Countries"}


def test_unreadable_rows_are_kept_for_the_review_screen():
    datafile = to_datafile([Page(_result([], unreadable=["row 3, smudged"]))])
    assert datafile.extra == {"unreadable": ["row 3, smudged"]}


def test_no_pages_yields_an_empty_but_valid_file():
    datafile = to_datafile([])
    assert datafile.notes == [] and datafile.format == "memo.datafile"


def test_the_title_is_one_line_of_number_native_and_english():
    """A file has a single name: "2-1 · 어휘와 표현 · Vocabulary & Expressions"."""
    pages = [
        Page(
            _result(
                [_item("나라", "country")],
                title_native="어휘와 표현",
                title_translated="Vocabulary & Expressions",
                context=[
                    ExtractedContext(kind="chapter", number="02", native="소개", translated="Introduction"),
                    ExtractedContext(kind="lesson", number="2-1", native=None, translated=None),
                ],
            )
        )
    ]
    assert to_datafile(pages).title == "2-1 · 어휘와 표현 · Vocabulary & Expressions"


def test_a_page_with_no_title_and_no_numbers_gets_none():
    assert to_datafile([Page(_result([_item("나라", "country")]))]).title is None


def test_an_english_only_page_is_not_repeated():
    """Nothing is printed twice when both title fields say the same thing."""
    pages = [Page(_result([_item("a", "b")], title_native="Cells", title_translated="Cells"))]
    assert to_datafile(pages).title == "Cells"
