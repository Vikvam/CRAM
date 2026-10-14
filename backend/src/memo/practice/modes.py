"""Which mode a card asks for, and what the wrong options are (PLAN 3.5).

Two decisions live here, both small and both overridable:

* **Mode** — the card's own scheduler state picks it. A card you have never
  seen is recognised before it is produced (``choice``), one you have held for
  a day is typed, and one you have held for a week is built from pieces. The
  session can force a single mode instead; this is only the suggestion.
* **Distractors** — the wrong options for ``choice``, taken from the scope the
  category asks for (``auto`` widens from the group outwards) and preferred by
  shape, so the answer does not stand out by being the only long one.

Language-neutral (PLAN 3.7): the only thing resembling a script test is
"are these two written in the same alphabet", answered out of Unicode names.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass

#: Options shown in `choice` — one answer and the rest distractors.
CHOICE_OPTIONS = 4

#: A card held this long is produced, not recognised (PLAN 3.5: "≳ 1 day").
TYPED_AFTER_DAYS = 1.0

#: And this long, assembled from pieces when the answer is short enough.
BUILD_AFTER_DAYS = 7.0

#: Tiles a `build` answer may have: fewer is not a puzzle, more is a chore.
#: Words are the coarser cut, so a sentence runs out of patience sooner than
#: a single word does (PLAN 3.7: words, else grapheme clusters).
BUILD_WORDS = (2, 6)
BUILD_GRAPHEMES = (2, 12)

#: Pairs in one `match` round, and the fewest it is worth showing.
MATCH_PAIRS = 5
MATCH_MINIMUM = 4


@dataclass(slots=True, frozen=True)
class Candidate:
    """One possible wrong option: an answer that exists elsewhere in the tree."""

    answer: str
    #: The question this answer belongs to. Carried only so that a note which
    #: answers the *same* question is not offered as a wrong option — two notes
    #: glossed "that" are a real thing an extractor produces.
    prompt: str
    direction: str
    note_id: str
    group_id: str | None
    data_file_id: str


def _script(text: str) -> str:
    """``"러시아"`` → ``HANGUL``, ``"Russia"`` → ``LATIN``, digits and maths → ``""``.

    The first word of a character's Unicode name is its alphabet, which is as
    much as "do these look alike" needs and keeps no list of languages.
    """
    for char in unicodedata.normalize("NFC", text):
        if not char.isalpha():
            continue
        try:
            return unicodedata.name(char).split()[0]
        except ValueError:  # unnamed character
            return ""
    return ""


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


def _levels(scope: str) -> list[str]:
    """Which pools to draw from, in order. ``auto`` widens until it has enough."""
    if scope == "group":
        return ["group"]
    if scope == "file":
        return ["file"]
    if scope == "category":
        return ["category"]
    return ["group", "file", "category"]  # auto


def _in_level(card: Candidate, other: Candidate, level: str) -> bool:
    if other.direction != card.direction or other.note_id == card.note_id:
        return False
    if level == "group":
        return other.data_file_id == card.data_file_id and other.group_id == card.group_id
    if level == "file":
        return other.data_file_id == card.data_file_id
    return True  # category: the whole subtree the queue was built from


def distractors_for(
    card: Candidate,
    pool: list[Candidate],
    *,
    scope: str = "auto",
    count: int = CHOICE_OPTIONS - 1,
    excluded: list[str] | None = None,
    rng: random.Random | None = None,
) -> list[str]:
    """Up to ``count`` wrong answers for one card, best candidates first.

    "Best" means *hardest to rule out without knowing*: the same alphabet and a
    similar length, so a four-option question is not answered by elimination.
    Anything that means the same as the right answer (an accepted alternative)
    is never offered as wrong, and neither is anything that answers the same
    question.
    """
    rng = rng or random.Random()
    answer = _fold(card.answer)
    if not answer:
        return []
    banned = {answer, *(_fold(e) for e in excluded or [])}
    asked = _fold(card.prompt)
    script = _script(card.answer)
    length = len(card.answer)

    chosen: list[str] = []
    for level in _levels(scope):
        batch: list[tuple[tuple[int, int, float], str]] = []
        for other in pool:
            folded = _fold(other.answer)
            if not folded or folded in banned or not _in_level(card, other, level):
                continue
            banned.add(folded)  # one spelling of one meaning is enough
            if asked and _fold(other.prompt) == asked:
                # It answers this very question. Two notes glossed "that" would
                # otherwise offer each other, and the option marked wrong would
                # be as right as the one marked correct.
                continue
            key = (
                0 if _script(other.answer) == script else 1,
                abs(len(other.answer) - length),
                rng.random(),
            )
            batch.append((key, other.answer))
        batch.sort(key=lambda pair: pair[0])
        chosen.extend(text for _, text in batch[: count - len(chosen)])
        if len(chosen) >= count:
            break
    return chosen


def build_tiles(answer: str) -> tuple[int, str]:
    """Roughly how many tiles ``build`` would cut this answer into, and how.

    The client does the real cutting with ``Intl.Segmenter`` (PLAN 3.7: words,
    else grapheme clusters); this only has to agree about *whether* a card can
    be built at all, and NFC code points are close enough for that — one per
    Hangul syllable, one per Latin letter.
    """
    words = unicodedata.normalize("NFC", answer).split()
    if len(words) > 1:
        return len(words), "words"
    return (len(words[0]) if words else 0), "graphemes"


def buildable(answer: str) -> bool:
    count, how = build_tiles(answer)
    low, high = BUILD_WORDS if how == "words" else BUILD_GRAPHEMES
    return low <= count <= high


def suggest_mode(
    *,
    interval_days: float | None,
    answer: str,
    allowed: list[str],
    has_distractors: bool,
    adaptive: bool = True,
) -> str:
    """The mode this card asks for. ``interval_days`` is ``None`` for a new card.

    Ordered by what the card needs, then filtered by what is allowed — a
    category that turns `choice` off gets the next thing down, never nothing.
    """
    if not allowed:
        return "flip"
    if not adaptive:
        return allowed[0]

    wanted: list[str]
    if interval_days is None or interval_days < TYPED_AFTER_DAYS:
        # Not yet in memory to produce from: recognise it first.
        wanted = ["choice", "match", "typed", "flip"]
    elif interval_days < BUILD_AFTER_DAYS:
        wanted = ["typed", "build", "flip", "choice"]
    else:
        wanted = ["build", "typed", "flip", "choice"]

    for mode in wanted:
        if mode not in allowed:
            continue
        if mode in ("choice", "match") and not has_distractors:
            continue  # nothing to pick between
        if mode == "build" and not buildable(answer):
            continue
        return mode
    return allowed[0]
