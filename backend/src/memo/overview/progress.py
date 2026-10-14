"""What the log already says (PLAN 6, phase 4).

The practice side decides what to ask next; this is the other direction — what
is known, what keeps going wrong, and what was answered on a given day. Every
function here only reads, and none of them produces a score: a card sits in one
of four plain buckets, and the weak list is an order, not a mark out of ten.

Which bucket is read from the review log alone, so it is the same whichever
scheduler is running — what you know about a word does not depend on the
algorithm that scheduled it. The weak list and the activity grid do read
scheduler state (PLAN 5), so those still take the name of the one to look at.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import median

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from memo.db.models import Card, Category, DataFileRow, NoteGroup, Profile, ReviewLog
from memo.db.models import CardState as CardStateRow
from memo.db.models import Note as NoteRow
from memo.models.datafile import Priority

#: How far back "it keeps going wrong" looks.
WEAK_WINDOW_DAYS = 30
WEAK_LIMIT = 20
#: Half a year of days — enough to see a habit, few enough to fit a phone.
ACTIVITY_DAYS = 182

#: Timed answers the pace is read off: enough for a median rather than a mood.
PACE_ANSWERS = 200
#: Below this there is no pace to report, only a guess with a number on it.
PACE_MINIMUM = 20
#: How far back "how many answers does one card take" is measured.
PACE_DAYS = 14
#: And what that ratio is allowed to be. A sitting of four answers must not get
#: to claim a ratio, and no sitting really costs four answers a card.
PACE_REPEATS = (1.0, 3.0)

NEW = "new"
LEARNING = "learning"
KNOWN = "known"
MASTERED = "mastered"
#: Weakest first, which is the order :func:`weakest` compares in.
BUCKETS = (NEW, LEARNING, KNOWN, MASTERED)
#: Not a standing: a word left out of practice on purpose. It sits beside the
#: buckets because the lists on screen offer it beside them, and because nothing
#: else in the app could reach a suspended note at all.
SET_ASIDE = "set-aside"
#: What :func:`words` will answer to.
LISTABLE = (*BUCKETS, SET_ASIDE)

#: What one clean success is worth, by what it took to produce it.
#:
#: Laufer & Goldstein (2004) measured four degrees of knowing a word and found a
#: stable difficulty order: recognise the meaning, recognise the word, write the
#: meaning, write the word. Every review row already carries both halves of that
#: coordinate, so the ladder is read straight off the log. A matched pair is weak
#: evidence even when it is right — the options are on screen, elimination shrinks
#: every later choice in a round, and the last pair of a grid is given away.
POINTS: dict[tuple[str, str], int] = {
    # passive recognition: the word is shown, its meaning is picked
    ("choice", "fwd"): 1,
    ("match", "fwd"): 1,
    # active recognition: the meaning is shown, the word is picked
    ("choice", "rev"): 2,
    ("match", "rev"): 2,
    # recall — but marked by the same person who was doing the recalling
    ("flip", "fwd"): 2,
    ("flip", "rev"): 2,
    # passive recall, and production with the pieces handed over
    ("typed", "fwd"): 3,
    ("build", "fwd"): 3,
    ("build", "rev"): 3,
    # active recall: the meaning is shown and the word is written from nothing
    ("typed", "rev"): 4,
}

#: Points are earned for good and never decay; the accuracy window is what takes
#: a card back down, so a word you have started missing leaves ``known`` however
#: much credit it once earned. That split is the whole rule in two sentences.
KNOWN_POINTS = 6
MASTERED_POINTS = 10
#: How many of ``MASTERED_POINTS`` must have been earned by typing the answer.
#: `build` is production too, but with the answer already cut up in front of you,
#: so it counts towards the total and never towards this.
WRITING_POINTS = 3
WRITING_MODE = "typed"
#: Mastered needs time, not only answers. Everything else here can be satisfied
#: inside one sitting — an hour on one lesson clears the ladder and the accuracy
#: window the same evening — and a word you can still produce an hour later is not
#: a word you have kept. So the successes that earned the points have to span at
#: least this long, which no amount of practice in one evening can fake.
#:
#: Eight hours rather than a calendar day: morning and evening is two real
#: retrievals across a working memory that has been emptied in between, whereas
#: waiting for midnight would make the same two answers count differently
#: depending on what time the first one was given.
MASTERY_SPREAD = timedelta(hours=8)
#: Below this a rate is noise rather than a measurement.
MIN_REVIEWS = 4
RATE = 0.8
RATE_WINDOW = 8

#: ``HARD`` — which is what an ``almost`` becomes (:mod:`memo.practice.grading`) —
#: is neither: it earns nothing and is left out of the window altogether. Only
#: ``GOOD``/``EASY`` earn, and only ``AGAIN`` is held against a card.
SUCCESS_FROM = 3
MISS_AT = 1


def _bucket(
    *,
    answered: bool,
    points: int,
    written: int,
    counted: Sequence[bool],
    first: datetime | None,
    last: datetime | None,
) -> str:
    """The rule itself, over a card's totals so far. The whole of it is here."""
    if not answered:
        return NEW
    if len(counted) < MIN_REVIEWS:
        return LEARNING
    window = counted[-RATE_WINDOW:]
    if sum(window) / len(window) < RATE:
        return LEARNING  # it is going wrong now, whatever it has earned
    spread = last - first if first is not None and last is not None else timedelta()
    if points >= MASTERED_POINTS and written >= WRITING_POINTS and spread >= MASTERY_SPREAD:
        return MASTERED
    return KNOWN if points >= KNOWN_POINTS else LEARNING


def _count(cards: Iterable[tuple[str, bool]]) -> tuple[dict[str, int], int]:
    """One scope's bucket counts, and how many known low words were counted as done.

    A word marked low is one you care less about, so knowing it is enough —
    until nothing else in the scope is left to master, and then it has to be
    mastered like the rest. Only what a bar *counts* changes: the card's own
    bucket, the word lists and practice all still read :func:`standing`.

    ``cards`` is ``(bucket, is_low)`` for every card in the scope. The known low
    ones move from ``known`` to ``mastered`` while any other card is short of
    mastered; a scope of nothing but low words has nothing else to wait for.
    """
    counts = dict.fromkeys(BUCKETS, 0)
    low_known = 0
    others_done = True
    for bucket, low in cards:
        counts[bucket] += 1
        if low and bucket == KNOWN:
            low_known += 1
        elif not low and bucket != MASTERED:
            others_done = False
    settled = 0 if others_done else low_known
    counts[KNOWN] -= settled
    counts[MASTERED] += settled
    return counts, settled


def standing_since(
    reviews: Iterable[tuple[str | None, str | None, int | None, datetime]],
) -> tuple[str, datetime | None]:
    """The bucket one card is in, and when it last entered it, oldest review first.

    A review is ``(mode, direction, final_grade, ts)`` — everything the rule needs
    is on the log row, which is why the log is kept raw (PLAN 1): the rule can
    change and the whole history is simply re-read.

    The rule is applied after every review rather than only at the end, which
    costs nothing (the totals are running ones) and is what makes "recently
    mastered" a thing the app can say. A card that slipped back and climbed again
    dates from the climb, not from the first time: ``since`` is the start of the
    run it is in now.
    """
    answered = False
    points = 0
    written = 0
    #: One entry per review that counts: True for a success, False for a miss.
    counted: list[bool] = []
    #: When the first and the last point were earned, for ``MASTERY_SPREAD``.
    first: datetime | None = None
    last: datetime | None = None
    where = NEW
    since: datetime | None = None
    for mode, direction, grade, ts in reviews:
        answered = True
        if grade is not None:
            if grade >= SUCCESS_FROM:
                earned = POINTS.get((mode or "", direction or ""), 0)
                points += earned
                if mode == WRITING_MODE:
                    written += earned
                if earned:
                    first = first or ts
                    last = ts
                counted.append(True)
            elif grade <= MISS_AT:
                counted.append(False)
        now_in = _bucket(
            answered=answered,
            points=points,
            written=written,
            counted=counted,
            first=first,
            last=last,
        )
        if now_in != where:
            where, since = now_in, ts
    return where, since


def standing(reviews: Iterable[tuple[str | None, str | None, int | None, datetime]]) -> str:
    """Just the bucket. See :func:`standing_since`, which this is the half of."""
    return standing_since(reviews)[0]


def standings_since(session: Session, profile: Profile) -> dict[str, tuple[str, datetime | None]]:
    """``card key → (bucket, when it got there)`` for every card ever answered.

    One pass over the log, which is append-only and small. A card with no rows is
    absent from the result and so is ``new``. Nothing is cached: the rule is meant
    to be changeable, and a cache would be the thing that outlived it.
    """
    found: dict[str, list[tuple[str | None, str | None, int | None, datetime]]] = defaultdict(list)
    rows = session.execute(
        select(ReviewLog.card_key, ReviewLog.mode, ReviewLog.direction, ReviewLog.final_grade, ReviewLog.ts)
        .where(ReviewLog.profile_id == profile.id)
        .order_by(ReviewLog.card_key, ReviewLog.ts, ReviewLog.id)
    )
    for key, mode, direction, grade, ts in rows:
        found[key].append((mode, direction, grade, ts))
    return {key: standing_since(items) for key, items in found.items()}


def standings(session: Session, profile: Profile) -> dict[str, str]:
    """``card key → bucket``. The half of :func:`standings_since` most callers want."""
    return {key: where for key, (where, _) in standings_since(session, profile).items()}


def weakest(buckets: Iterable[str]) -> str:
    """A note is as known as its worst direction — the sheet marks the hole."""
    return min(buckets, key=BUCKETS.index, default=NEW)


@dataclass(slots=True)
class Mastery:
    """One category, counting itself and everything under it.

    Counts are of notes, not cards: a word asked both ways is one word, and it
    stands where its weaker direction does (:func:`weakest`).
    """

    category_id: str
    path: str
    label: dict[str, str] | None
    depth: int
    notes: int
    new: int
    learning: int
    known: int
    #: Mastered, plus the known low words :func:`_count` counted as done.
    mastered: int
    #: How many of ``mastered`` are those low words.
    settled: int


@dataclass(slots=True)
class FileMastery:
    """One data file — a lesson, which is the grain most collections live at."""

    data_file_id: str
    category_id: str
    title: str | None
    notes: int
    new: int
    learning: int
    known: int
    mastered: int
    settled: int


@dataclass(slots=True)
class GroupMastery:
    """One heading inside a lesson. ``key`` is null for the notes under none."""

    key: str | None
    label: dict[str, str] | None
    notes: int
    new: int
    learning: int
    known: int
    mastered: int
    settled: int


@dataclass(slots=True)
class WeakCard:
    """One card worth looking at again, and why it is on the list."""

    card_key: str
    note_id: str
    data_file_id: str
    file_title: str | None
    category_path: str
    group: dict[str, str] | None
    group_key: str | None
    direction: str
    prompt: str
    answer: str
    #: Times the scheduler was told "again" in the window, and over all time.
    wrong: int
    answers: int
    lapses: int
    last_wrong: datetime | None
    interval_days: float | None


@dataclass(slots=True)
class Word:
    """One note as a list of words shows it: the word, then what it means.

    A word asked both ways is one row, the way it is one count, so ``prompt`` is
    always the front. ``card_key`` and ``direction`` name the direction that holds
    the word in its bucket — the weaker one, when the two differ.
    """

    card_key: str
    note_id: str
    direction: str
    prompt: str
    answer: str
    data_file_id: str
    file_title: str | None
    group: dict[str, str] | None
    group_key: str | None
    #: When the note entered the bucket it is in. Null for one never answered.
    since: datetime | None


@dataclass(slots=True)
class Day:
    day: date
    reviews: int
    correct: int


def _practisable() -> Select:
    """Every card practice would consider: nothing suspended, nothing archived."""
    return (
        select(Card, NoteRow, DataFileRow)
        .join(NoteRow, Card.note_id == NoteRow.id)
        .join(DataFileRow, NoteRow.data_file_id == DataFileRow.id)
        .where(
            or_(NoteRow.suspended.is_(None), NoteRow.suspended.is_(False)),
            NoteRow.archived_at.is_(None),
            DataFileRow.archived_at.is_(None),
        )
    )


def _suspended() -> Select:
    """The cards :func:`_practisable` exists to hide — set aside, not thrown away."""
    return (
        select(Card, NoteRow, DataFileRow)
        .join(NoteRow, Card.note_id == NoteRow.id)
        .join(DataFileRow, NoteRow.data_file_id == DataFileRow.id)
        .where(
            NoteRow.suspended.is_(True),
            NoteRow.archived_at.is_(None),
            DataFileRow.archived_at.is_(None),
        )
    )


def _practised_cards(scheduler: str, profile: Profile) -> Select:
    """The same cards, with the scheduler state the weak list reads off them."""
    return _practisable().outerjoin(
        CardStateRow,
        (CardStateRow.card_key == Card.key)
        & (CardStateRow.profile_id == profile.id)
        & (CardStateRow.scheduler == scheduler),
    )


def _ancestors(path: str) -> list[str]:
    """``a/b/c`` → ``a``, ``a/b``, ``a/b/c``: the rows a card counts towards."""
    parts = path.split("/")
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _per_note(
    rows: Iterable[tuple[str, str, object]], where: dict[str, str]
) -> dict[str, tuple[str, object]]:
    """``(note id, card key, scope)`` rows → ``note id → (bucket, scope)``.

    The note takes its weakest direction, the rule the sheet's row marker already
    follows, so a count and the dots it summarises cannot disagree. ``scope`` is
    whatever the caller groups by, and is the same for every card of a note.
    """
    found: dict[str, list[str]] = defaultdict(list)
    scope: dict[str, object] = {}
    for note_id, card_key, mine in rows:
        found[note_id].append(where.get(card_key, NEW))
        scope[note_id] = mine
    return {note_id: (weakest(buckets), scope[note_id]) for note_id, buckets in found.items()}


def mastery(session: Session, profile: Profile) -> list[Mastery]:
    """The four buckets per category, rolled up the tree, counted in notes.

    A note counts for its own category and for every category above it, so a
    subject's row is the subject, not just the files that happen to sit loose
    at its top. Suspended and archived notes are left out — they are not what
    you are learning.
    """
    where = standings(session, profile)
    rows = session.execute(
        _practisable()
        .with_only_columns(NoteRow.id, Card.key, Category.path, NoteRow.priority)
        .join(Category, DataFileRow.category_id == Category.id)
    )
    notes = _per_note(((n, k, (path, prio)) for n, k, path, prio in rows), where)
    cards: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for bucket, (path, priority) in notes.values():  # type: ignore[misc]
        for ancestor in _ancestors(path):
            cards[ancestor].append((bucket, priority == Priority.LOW))

    out: list[Mastery] = []
    for category in session.scalars(select(Category).order_by(Category.path)):
        mine, settled = _count(cards.get(category.path, []))
        out.append(
            Mastery(
                category_id=category.id,
                path=category.path,
                label=category.label,
                depth=category.path.count("/"),
                notes=sum(mine.values()),
                new=mine[NEW],
                learning=mine[LEARNING],
                known=mine[KNOWN],
                mastered=mine[MASTERED],
                settled=settled,
            )
        )
    return out


def file_mastery(session: Session, profile: Profile, *, data_file_id: str | None = None) -> list[FileMastery]:
    """The same four buckets per data file, in the order the files are practised.

    A collection with one category and six lessons has one mastery bar and six
    useful ones, so the page shows both. ``data_file_id`` narrows it to one.
    """
    where = standings(session, profile)
    query = _practisable().with_only_columns(NoteRow.id, Card.key, DataFileRow.id, NoteRow.priority)
    if data_file_id is not None:
        query = query.where(DataFileRow.id == data_file_id)
    notes = _per_note(((n, k, (f, prio)) for n, k, f, prio in session.execute(query)), where)
    cards: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for bucket, (file_id, priority) in notes.values():  # type: ignore[misc]
        cards[file_id].append((bucket, priority == Priority.LOW))

    out: list[FileMastery] = []
    files = select(DataFileRow).where(DataFileRow.archived_at.is_(None))
    if data_file_id is not None:
        files = files.where(DataFileRow.id == data_file_id)
    for file in session.scalars(files.order_by(DataFileRow.position, DataFileRow.created_at)):
        if not cards.get(file.id):
            continue  # nothing practisable in it — an empty file is not a lesson yet
        mine, settled = _count(cards[file.id])
        out.append(
            FileMastery(
                data_file_id=file.id,
                category_id=file.category_id,
                title=file.title,
                notes=sum(mine.values()),
                new=mine[NEW],
                learning=mine[LEARNING],
                known=mine[KNOWN],
                mastered=mine[MASTERED],
                settled=settled,
            )
        )
    return out


def group_mastery(session: Session, profile: Profile, data_file_id: str) -> list[GroupMastery]:
    """The four buckets per heading of one lesson, in the lesson's own order.

    Notes under no heading come first, as one row with no key, which is where a
    sheet shows them. Each heading is its own scope for the low-word rule, the
    same way each file and each category is.
    """
    where = standings(session, profile)
    rows = session.execute(
        _practisable()
        .with_only_columns(NoteRow.id, Card.key, NoteRow.group_id, NoteRow.priority)
        .where(DataFileRow.id == data_file_id)
    )
    notes = _per_note(((n, k, (g, prio)) for n, k, g, prio in rows), where)
    cards: dict[str | None, list[tuple[str, bool]]] = defaultdict(list)
    for bucket, (group_id, priority) in notes.values():  # type: ignore[misc]
        cards[group_id].append((bucket, priority == Priority.LOW))

    headings: list[tuple[str | None, str | None, dict[str, str] | None]] = [(None, None, None)]
    headings += [
        (group.id, group.key, group.label)
        for group in session.scalars(
            select(NoteGroup).where(NoteGroup.data_file_id == data_file_id).order_by(NoteGroup.position)
        )
    ]
    out: list[GroupMastery] = []
    for group_id, key, label in headings:
        if not cards.get(group_id):
            continue
        mine, settled = _count(cards[group_id])
        out.append(
            GroupMastery(
                key=key,
                label=label,
                notes=sum(mine.values()),
                new=mine[NEW],
                learning=mine[LEARNING],
                known=mine[KNOWN],
                mastered=mine[MASTERED],
                settled=settled,
            )
        )
    return out


def note_buckets(session: Session, profile: Profile, note_ids: Sequence[str]) -> dict[str, str]:
    """``note id → bucket`` for a sheet's rows, weakest direction winning.

    Unlike :func:`mastery` this takes the notes it is given, suspended ones
    included: a sheet shows the lesson as it is written, markers and all.
    """
    if not note_ids:
        return {}
    rows = session.execute(
        select(Card.note_id, Card.key, Card.note_id).where(Card.note_id.in_(list(note_ids)))
    )
    return {note_id: bucket for note_id, (bucket, _) in _per_note(rows, standings(session, profile)).items()}


def words(
    session: Session,
    profile: Profile,
    bucket: str,
    *,
    limit: int | None = None,
    offset: int = 0,
    where: dict[str, tuple[str, datetime | None]] | None = None,
    data_file_id: str | None = None,
    category_path: str | None = None,
) -> tuple[list[Word], int]:
    """The notes in one bucket as a list of words, and how many there are in all.

    One row per note, which is what the counts beside every list count: a word
    asked both ways is one word, standing where its weaker direction does. So
    the row is always ``front back``, and ``card_key`` is the direction holding
    the word where it is.

    ``bucket`` is one of :data:`BUCKETS` or :data:`SET_ASIDE`. The last is not a
    standing at all and needs its own query, because leaving suspended notes out
    is the whole job of :func:`_practisable` — which is also why, until this
    existed, a word you set aside could not be found again except by opening the
    lesson it came from.

    ``known`` and ``mastered`` come back most recently reached first, because
    "what have I just got the hang of" is the question a list of them answers.
    The rest come back in the order of the collection: the book from the front.

    ``data_file_id`` keeps one lesson, ``category_path`` one category and
    everything under it.

    ``where`` is :func:`standings_since` already in hand. One page asks for
    several of these lists at once, and each one would otherwise re-read the
    whole log to learn the same thing.
    """
    if bucket not in LISTABLE:
        raise ValueError(f"no such bucket: {bucket!r}")
    aside = bucket == SET_ASIDE
    # Set aside is not a standing, so there is nothing to read the log for.
    where = {} if aside else (where if where is not None else standings_since(session, profile))
    query = (
        (_suspended() if aside else _practisable())
        .with_only_columns(Card, NoteRow, DataFileRow, NoteGroup.key, NoteGroup.label)
        .outerjoin(NoteGroup, NoteRow.group_id == NoteGroup.id)
        .order_by(DataFileRow.position, NoteRow.position, Card.direction)
    )
    if data_file_id is not None:
        query = query.where(DataFileRow.id == data_file_id)
    if category_path is not None:
        query = query.join(Category, DataFileRow.category_id == Category.id).where(
            or_(
                Category.path == category_path,
                Category.path.startswith(f"{category_path}/", autoescape=True),
            )
        )

    # Notes in the order of their first card, which is the order of the book.
    found_notes: dict[str, tuple[NoteRow, DataFileRow, str | None, dict[str, str] | None, list]] = {}
    for card, note, file, group_key, group in session.execute(query):
        entry = found_notes.setdefault(note.id, (note, file, group_key, group, []))
        entry[4].append((card, *where.get(card.key, (NEW, None))))

    found: list[Word] = []
    for note, file, group_key, group, cards in found_notes.values():
        standing_now = weakest(b for _, b, _ in cards)
        if not aside and standing_now != bucket:
            continue
        holding = [(card, since) for card, b, since in cards if b == standing_now]
        stamps = [since for _, since in holding if since is not None]
        found.append(
            Word(
                card_key=holding[0][0].key,
                note_id=note.id,
                direction=holding[0][0].direction,
                prompt=note.front or "",
                answer=note.back or "",
                data_file_id=file.id,
                file_title=file.title,
                group=group,
                group_key=group_key,
                # The note got here when its last direction did.
                since=max(stamps) if stamps else None,
            )
        )
    if bucket in (KNOWN, MASTERED):
        found.sort(key=lambda word: (-(word.since.timestamp() if word.since else 0.0), word.card_key))
    total = len(found)
    start = max(0, offset)
    return found[start : None if limit is None else start + limit], total


def weak_cards(
    session: Session,
    profile: Profile,
    scheduler: str,
    *,
    window_days: int = WEAK_WINDOW_DAYS,
    limit: int = WEAK_LIMIT,
    now: datetime | None = None,
) -> list[WeakCard]:
    """The cards that keep going wrong lately, worst first.

    "Wrong" is the scheduler being told *again* — which covers judging yourself
    wrong on a flip, where the checker never saw an answer. **Lately** is the
    whole of it: only misses inside ``window_days`` put a card here or order it,
    so a word that went badly in the spring and has been right ever since leaves
    the list instead of sitting on it for good.

    ``lapses`` is still reported, because it is true and a reader may want it —
    it just no longer decides anything. It could not be windowed in any case:
    spotting a lapse in the log needs ``state_before``, which is null on every
    row handed back from a phone.
    """
    now = now or datetime.now(UTC)
    since = now - timedelta(days=window_days)

    recent = {
        key: (answers, wrong)
        for key, answers, wrong in session.execute(
            select(
                ReviewLog.card_key,
                func.count(),
                func.sum(case((ReviewLog.final_grade == 1, 1), else_=0)),
            )
            .where(ReviewLog.profile_id == profile.id, ReviewLog.ts >= since)
            .group_by(ReviewLog.card_key)
        )
    }
    last_wrong = dict(
        session.execute(
            select(ReviewLog.card_key, func.max(ReviewLog.ts))
            .where(ReviewLog.profile_id == profile.id, ReviewLog.final_grade == 1)
            .group_by(ReviewLog.card_key)
        ).all()
    )

    found: list[tuple[tuple[float, float, str], WeakCard]] = []
    rows = session.execute(
        _practised_cards(scheduler, profile)
        .with_only_columns(
            Card, NoteRow, DataFileRow, CardStateRow, Category.path, NoteGroup.key, NoteGroup.label
        )
        .join(Category, DataFileRow.category_id == Category.id)
        .outerjoin(NoteGroup, NoteRow.group_id == NoteGroup.id)
    )
    for card, note, file, state, path, group_key, group in rows:
        answers, wrong = recent.get(card.key, (0, 0))
        lapses = state.lapses if state is not None else 0
        if not wrong:
            continue
        reverse = card.direction == "rev"
        when = last_wrong.get(card.key)
        found.append(
            (
                (-wrong, -(when.timestamp() if when else 0.0), card.key),
                WeakCard(
                    card_key=card.key,
                    note_id=note.id,
                    data_file_id=file.id,
                    file_title=file.title,
                    category_path=path,
                    group=group,
                    group_key=group_key,
                    direction=card.direction,
                    prompt=(note.back if reverse else note.front) or "",
                    answer=(note.front if reverse else note.back) or "",
                    wrong=wrong,
                    answers=answers,
                    lapses=lapses,
                    last_wrong=when,
                    interval_days=state.interval_days if state is not None else None,
                ),
            )
        )
    found.sort(key=lambda pair: pair[0])
    return [weak for _, weak in found[:limit]]


def activity(
    session: Session,
    profile: Profile,
    *,
    days: int = ACTIVITY_DAYS,
    tz_offset_minutes: int = 0,
    now: datetime | None = None,
) -> list[Day]:
    """Answers per day, newest day last, days with nothing left out.

    Days are the client's days: a session at 23:30 in Seoul belongs to that
    evening, not to the UTC afternoon it happens to fall in, so the caller
    passes its own offset from UTC and SQLite shifts the timestamps by it.
    """
    now = now or datetime.now(UTC)
    local_today = (now + timedelta(minutes=tz_offset_minutes)).date()
    since = now - timedelta(days=days)
    local_day = func.date(ReviewLog.ts, f"{tz_offset_minutes:+d} minutes")
    rows = session.execute(
        select(
            local_day,
            func.count(),
            func.sum(case((ReviewLog.final_grade >= 3, 1), else_=0)),
        )
        .where(ReviewLog.profile_id == profile.id, ReviewLog.ts >= since)
        .group_by(local_day)
        .order_by(local_day)
    )
    out = [
        Day(day=date.fromisoformat(day), reviews=reviews, correct=correct or 0)
        for day, reviews, correct in rows
        if day is not None
    ]
    # A grid is drawn up to today even when today is empty, so "nothing yet"
    # reads as an empty square rather than as a missing week.
    if not out or out[-1].day < local_today:
        out.append(Day(day=local_today, reviews=0, correct=0))
    return out


def pace(
    session: Session,
    profile: Profile,
    *,
    tz_offset_minutes: int = 0,
    now: datetime | None = None,
) -> float | None:
    """How many seconds one card costs in a sitting, off this profile's own log.

    Two measured things multiplied: how long an answer takes — the median of the
    last ``PACE_ANSWERS`` timed ones — and how many answers one card takes, which
    is answers over distinct cards within a day, summed over ``PACE_DAYS``. The
    second is why the median alone will not do: the in-session loop asks a missed
    card again until it is right twice, so a card costs well over one answer.

    Days are the client's days, as in :func:`activity`: an evening sitting that
    crosses UTC midnight is one sitting, and counting it as two would make a card
    look cheaper than it is.

    ``None`` when there is too little history to say. A caller showing an estimate
    of how long a session will take should then say nothing rather than guess,
    because a figure that is wrong by half is worse than no figure at all.
    """
    now = now or datetime.now(UTC)
    durations = list(
        session.scalars(
            select(ReviewLog.duration_ms)
            .where(ReviewLog.profile_id == profile.id, ReviewLog.duration_ms.is_not(None))
            .order_by(ReviewLog.id.desc())
            .limit(PACE_ANSWERS)
        )
    )
    if len(durations) < PACE_MINIMUM:
        return None
    day = func.date(ReviewLog.ts, f"{tz_offset_minutes:+d} minutes")
    rows = session.execute(
        select(func.count(), func.count(func.distinct(ReviewLog.card_key)))
        .where(
            ReviewLog.profile_id == profile.id,
            ReviewLog.ts >= now - timedelta(days=PACE_DAYS),
        )
        .group_by(day)
    ).all()
    answers = sum(count for count, _ in rows)
    cards = sum(seen for _, seen in rows)
    low, high = PACE_REPEATS
    repeats = min(high, max(low, answers / cards)) if cards else low
    return median(durations) / 1000 * repeats
