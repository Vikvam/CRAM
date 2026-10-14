"""Writing the collection back out as a tree of data files (PLAN 6, phase 2)."""

from __future__ import annotations

import json

import pytest

from memo.collection.categories import ensure_category
from memo.collection.editing import archive_file, archive_note, create_file, create_notes
from memo.collection.store import store_datafile
from memo.dataio.datafile_io import dump_json, read_datafile
from memo.dataio.export_tree import CATEGORY_FILE, export_tree
from memo.models.category import CategoryConfig, PracticeSettings

#: What the fixture's title ("2-1 · 어휘와 표현 · Vocabulary & Expressions") slugifies to.
VOCAB1 = "2-1-어휘와-표현-vocabulary-expressions.json"


@pytest.fixture
def collection(session, vocab1):
    """The imported Korean file, plus one typed by hand in another category."""
    store_datafile(session, vocab1, category_path="korean/book1/02-introduction")
    typed = create_file(
        session,
        ensure_category(session, "korean/book1/03-daily-life", label={"en": "Daily life"}),
        title="3-1 Vocabulary",
        front_lang="ko",
        back_lang="en",
        default_type="bidirectional",
    )
    create_notes(session, typed, [{"front": "나라", "back": "country"}])
    return typed


def test_the_tree_mirrors_the_categories(session, collection, tmp_path):
    report = export_tree(session, tmp_path)

    assert (tmp_path / "korean" / CATEGORY_FILE).is_file()
    assert (tmp_path / "korean/book1/02-introduction" / VOCAB1).is_file()
    assert (tmp_path / "korean/book1/03-daily-life/3-1-vocabulary.json").is_file()
    assert report.notes == 33
    assert len(report.categories) == 4
    assert report.unknown == []


def test_an_exported_file_reads_back_as_the_same_file(session, collection, tmp_path, vocab1):
    export_tree(session, tmp_path)
    again = read_datafile(tmp_path / "korean/book1/02-introduction" / VOCAB1)
    assert dump_json(again) == dump_json(vocab1), "export → import reproduces it exactly"


def test_exporting_twice_changes_nothing(session, collection, tmp_path):
    export_tree(session, tmp_path)
    before = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*.json"))}
    report = export_tree(session, tmp_path)
    assert {p: p.read_bytes() for p in sorted(tmp_path.rglob("*.json"))} == before
    assert report.unknown == [], "its own files are not strangers"


def test_a_category_config_is_exported_beside_its_files(session, collection, tmp_path):
    category = ensure_category(session, "korean")
    category.label = {"en": "Korean", "ko": "한국어"}
    category.config = CategoryConfig(front_lang="ko", practice=PracticeSettings(scheduler="fsrs")).dumps()
    session.flush()

    export_tree(session, tmp_path)
    written = json.loads((tmp_path / "korean" / CATEGORY_FILE).read_text(encoding="utf-8"))
    assert written["format"] == "memo.category"
    assert written["label"] == {"en": "Korean", "ko": "한국어"}
    assert written["front_lang"] == "ko"
    assert written["practice"] == {"scheduler": "fsrs"}


def test_only_one_subtree_can_be_exported(session, collection, tmp_path):
    category = ensure_category(session, "korean/book1/03-daily-life")
    report = export_tree(session, tmp_path, category_id=category.id)
    assert [f.path.name for f in report.files] == ["3-1-vocabulary.json"]
    assert not (tmp_path / "korean/book1/02-introduction").exists()

    with pytest.raises(KeyError):
        export_tree(session, tmp_path, category_id="cat_nope")


def test_archived_notes_and_files_stay_out_of_the_tree(session, collection, tmp_path):
    [note] = create_notes(session, collection, [{"front": "한국", "back": "Korea"}])
    archive_note(session, note)
    export_tree(session, tmp_path)
    exported = read_datafile(tmp_path / "korean/book1/03-daily-life/3-1-vocabulary.json")
    assert [n.front for n in exported.notes] == ["나라"]

    archive_file(session, collection)
    report = export_tree(session, tmp_path)
    assert all("03-daily-life" not in str(f.path) for f in report.files)
    # The file written before it was archived is left where it is, and reported.
    assert [p.name for p in report.unknown] == ["3-1-vocabulary.json"]


def test_a_file_this_export_did_not_write_is_reported_never_deleted(session, collection, tmp_path):
    stranger = tmp_path / "korean/book1/03-daily-life/notes-of-my-own.json"
    stranger.parent.mkdir(parents=True)
    stranger.write_text('{"mine": true}\n', encoding="utf-8")

    report = export_tree(session, tmp_path)
    assert report.unknown == [stranger]
    assert stranger.read_text(encoding="utf-8") == '{"mine": true}\n'


def test_two_files_with_the_same_title_get_separate_names(session, tmp_path):
    category = ensure_category(session, "korean")
    for _ in range(2):
        file = create_file(session, category, title="Vocabulary")
        create_notes(session, file, [{"front": "나라", "back": "country"}])

    report = export_tree(session, tmp_path)
    assert sorted(f.path.name for f in report.files) == ["vocabulary-2.json", "vocabulary.json"]


def test_an_untitled_file_falls_back_to_its_id(session, tmp_path):
    file = create_file(session, ensure_category(session, "korean"))
    create_notes(session, file, [{"front": "나라", "back": "country"}])
    [exported] = export_tree(session, tmp_path).files
    assert exported.path.name == f"{file.id}.json".lower()


def test_the_photos_come_along_and_the_file_points_at_them(session, vocab1, tmp_path, sample_image):
    """The exported tree has to be readable on a machine that never had the database."""
    from memo.db.models import ImportJob, ImportPage
    from memo.models.ids import new_id

    file = store_datafile(session, vocab1, category_path="korean/book1/02-introduction")
    raw_root = tmp_path / "var" / "raw"
    page_path = "korean/book1/02-introduction/job_x/01-vocab1.jpg"
    (raw_root / page_path).parent.mkdir(parents=True)
    (raw_root / page_path).write_bytes(sample_image.read_bytes())
    job = ImportJob(id=new_id("job"), category_id=file.category_id, target_data_file_id=file.id)
    job.pages.append(ImportPage(id=new_id("pg"), job_id=job.id, position=0, path=page_path))
    session.add(job)
    session.flush()

    report = export_tree(session, tmp_path / "data", raw_root=raw_root)
    copied = tmp_path / "data/korean/book1/02-introduction/raw/job_x/01-vocab1.jpg"
    assert copied.is_file()
    assert copied.stat().st_size == sample_image.stat().st_size
    assert report.photos == [copied]

    exported = read_datafile(tmp_path / "data/korean/book1/02-introduction" / VOCAB1)
    assert exported.source is not None
    assert exported.source.files == ["raw/job_x/01-vocab1.jpg"], (
        "the job folder stays, so two photos with one name are two files"
    )


def test_photos_can_be_left_behind(session, vocab1, tmp_path):
    store_datafile(session, vocab1, category_path="korean")
    report = export_tree(session, tmp_path, raw_root=tmp_path / "raw", copy_photos=False)
    assert report.photos == []
    assert not (tmp_path / "korean" / "raw").exists()


def test_a_file_keeps_the_name_it_has_on_disk(session, collection, tmp_path):
    """Renaming or retitling must not leave two copies of one file in the tree."""
    export_tree(session, tmp_path)
    directory = tmp_path / "korean/book1/03-daily-life"
    (directory / "3-1-vocabulary.json").rename(directory / "lesson-3-1.json")

    collection.title = "Words of lesson 3-1"
    session.flush()
    report = export_tree(session, tmp_path)

    assert [f.path.name for f in report.files if "03-daily-life" in str(f.path)] == ["lesson-3-1.json"]
    assert not (directory / "words-of-lesson-3-1.json").exists()
    assert report.unknown == []
