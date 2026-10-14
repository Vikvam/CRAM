from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from memo.db import Base, make_engine, make_session_factory
from memo.models.datafile import DataFile, load_datafile
from memo.models.extraction import ExtractionResult

FIXTURES = Path(__file__).parent / "fixtures"
#: The shipped example specs, so tests see the same importers on every machine,
#: whatever is in that machine's own ``importers.local/``.
EXAMPLE_IMPORTERS = Path(__file__).resolve().parents[1] / "examples" / "importers"
#: A stand-in for the photo the format was designed around (PLAN 2), which is a publisher's
#: page and not in git. The fake provider never looks at it: only the bytes travel.
SAMPLE_IMAGE = FIXTURES / "sample-page.jpg"


@pytest.fixture(autouse=True)
def example_importers(monkeypatch) -> Path:
    monkeypatch.setenv("MEMO_IMPORTERS_DIR", str(EXAMPLE_IMPORTERS))
    return EXAMPLE_IMPORTERS


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURES


@pytest.fixture
def sample_image() -> Path:
    return SAMPLE_IMAGE


@pytest.fixture
def vocab1_extraction() -> ExtractionResult:
    return ExtractionResult.model_validate_json(
        (FIXTURES / "vocab1.extraction.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def vocab1_text() -> str:
    return (FIXTURES / "vocab1.datafile.json").read_text(encoding="utf-8")


@pytest.fixture
def vocab1(vocab1_text: str) -> DataFile:
    return load_datafile(vocab1_text)


@pytest.fixture
def vocab1_raw(vocab1_text: str) -> dict:
    return json.loads(vocab1_text)


@pytest.fixture
def session() -> Session:
    engine = make_engine(":memory:")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        yield session
