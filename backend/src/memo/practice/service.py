"""The due queue and recording an answer.

The in-session loop (requeue until right twice) runs in the client, next to the
checker, so it keeps working offline later. The server owns what must be
shared and durable: which cards are due, and the append-only review log.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from memo.collection.categories import category_config
from memo.collection.lists import focus_names, focused, members
from memo.db.models import Card, Category, DataFileRow, Profile, ReviewLog
from memo.db.models import CardState as CardStateRow
from memo.db.models import Note as NoteRow
from memo.models.category import CategoryConfig, effective_distractor_scope, effective_modes
from memo.models.datafile import NORMAL, Direction
from memo.overview.progress import NEW, standings
from memo.practice.grading import grade_for, schedule_answer
from memo.practice.modes import CHOICE_OPTIONS, Candidate, distractors_for, suggest_mode
from memo.practice.priority import FOCUS_PUSH, TWICE_AT, effective, push
from memo.scheduling import CardState, Grade, get_scheduler
from memo.scheduling.registry import DEFAULT_SCHEDULER


@dataclass(slots=True)
class QueueCard:
    """Everything the client needs to show one card, oriented for its direction."""

    key: str
    note_id: str
    direction: str
    prompt: str
    answer: str
    accepted: list[str]
    prompt_lang: str | None
    answer_lang: str | None
    note: str | None
    fields: dict[str, Any] | None
    group: dict[str, str] | None
    data_file_id: str
    is_new: bool
    state: dict[str, Any] | None
    #: Brought forward: scheduled for later, offered because you asked for this scope.
    early: bool = False
    #: How often this word should come up, as it stands *now*: the mark the person
    #: set, damped by how well this card is already known (:mod:`.priority`).
    priority: str = NORMAL
    #: Asked a second time in the same sitting.
    twice: bool = False
    #: The name of the focused list that pushed this card up, if one did. A list
    #: is not a mark, so it says its own name rather than borrowing ``priority``.
    focus: str | None = None
    modes: list[str] | None = None
    #: Wrong answers for `choice`, best candidates first (PLAN 3.5).
    distractors: list[str] = field(default_factory=list)
    #: The mode this card's own state asks for; the session may override it.
    suggest: str = "typed"


@dataclass(slots=True)
class AnswerIn:
    card_key: str
    mode: str
    outcome: str | None = None
    #: The grade the user picked (flip) or chose over the checker (override).
    grade: int | None = None
    overridden: bool = False
    raw_answer: str | None = None
    duration_ms: int | None = None
    at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def subtree(session: Session, category_id: str | None):
    """Condition selecting data files in a category and everything under it."""
    if category_id is None:
        return None
    category = session.get(Category, category_id)
    if category is None:
        raise KeyError(f"no such category: {category_id}")
    ids = select(Category.id).where(
        or_(Category.path == category.path, Category.path.like(f"{category.path}/%"))
    )
    return DataFileRow.category_id.in_(ids)


def resolve_scheduler_name(
    session: Session, profile: Profile, category_id: str | None, requested: str | None = None
) -> str:
    """Session request → category setting → profile setting → default (PLAN 5)."""
    if requested:
        return requested
    if category_id:
        category = session.get(Category, category_id)
        if category is not None:
            config = category_config(session, category)
            if config.practice and config.practice.scheduler:
                return config.practice.scheduler
    return profile.scheduler or DEFAULT_SCHEDULER


#: prompt, answer, accepted answers, prompt language, answer language
Oriented = tuple[str, str, list[str], str | None, str | None]


def _orient(note: NoteRow, file: DataFileRow, direction: str) -> Oriented:
    accept = note.accept or {}
    front_lang = note.front_lang or file.front_lang
    back_lang = note.back_lang or file.back_lang
    if direction == Direction.REV:
        return note.back or "", note.front or "", list(accept.get("front") or []), back_lang, front_lang
    return note.front or "", note.back or "", list(accept.get("back") or []), front_lang, back_lang


def _mark(
    session: Session,
    profile: Profile,
    items: list[QueueCard],
    *,
    focus: Collection[str] = (),
    names: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """Turn each card's mark into what it is worth now, and say how far it moves.

    On the way in, ``item.priority`` is the mark as the person set it; on the way
    out it is what that mark is still worth, which is the damping
    (:mod:`memo.practice.priority`). The returned pushes are only the non-zero
    ones, so the sort keys below fall back to exactly their old behaviour.

    ``focus`` is the note ids on a list whose focus has not yet passed. A focus
    is **not** folded into ``item.priority``: the mark is a property of the note
    and a focus is not, so the card carries the list's name in ``item.focus``
    instead and the badge keeps telling the truth about the setting.

    ``standings`` is one pass over the whole review log, so it is not asked for
    at all until something in scope has actually been marked, or something is
    focused: an unmarked collection costs what it always did.
    """
    if not focus and all(item.priority == NORMAL for item in items):
        return {}
    names = names or {}
    where = standings(session, profile)
    pushes: dict[str, int] = {}
    for item in items:
        bucket = where.get(item.key, NEW)
        mark = item.priority
        on_list = item.note_id in focus
        item.priority = effective(mark, bucket)
        # Named only while the focus still has something to give. A mastered word
        # on a test list is pushed by nothing, and a label saying otherwise would
        # be describing the setting rather than the session — the same rule
        # ``effective`` keeps for marks. Independent of the mark, so a crucial
        # word on the list shows both: the mark, and which test it is on.
        item.focus = names.get(item.note_id) if on_list and FOCUS_PUSH.get(bucket, 0) else None
        moves = push(mark, bucket, focused=on_list)
        item.twice = moves >= TWICE_AT
        if moves:
            pushes[item.key] = moves
    return pushes


#: How many cards must sit between the two directions of the same note.
SIBLING_GAP = 4

#: Of a session that was given a size, the share held back for words not met yet.
#: A quarter: a backlog that owns the whole sitting is one you never get out from
#: under, because the lesson it came from never moves on.
NEW_SHARE = 0.25

#: Of a session that was given a size, the most of it a focused list may take.
#:
#: Half, for two reasons pulling opposite ways. A test's words are the ones you
#: most want asked, so left alone a focus would take the whole sitting and the
#: rest of the collection would go unanswered for the week before an exam — and
#: a backlog you have stopped touching is what makes a collection feel lost.
#: But the other half is also what makes a focus *win*: an unmarked focused word
#: pushes 1 and a word marked ``high`` pushes 2, so with no share held back the
#: words marked before some earlier test would still go first and the list would
#: never get a look in.
FOCUS_SHARE = 0.5


def _split(
    items: list[tuple[Any, QueueCard]], focus: Collection[str]
) -> tuple[list[tuple[Any, QueueCard]], list[tuple[Any, QueueCard]]]:
    """``(on a focused list, everything else)``, each keeping the order it had."""
    if not focus:
        return [], items
    held = [pair for pair in items if pair[1].note_id in focus]
    rest = [pair for pair in items if pair[1].note_id not in focus]
    return held, rest


def _shares(
    due: int, new: int, *, limit: int | None, new_limit: int | None, due_limit: int
) -> tuple[int, int]:
    """How many due and how many new cards one session takes.

    With no ``limit`` this is what it always was — every due card up to
    ``due_limit`` and every new one up to ``new_limit``. With one, the session is
    the size that was asked for and ``NEW_SHARE`` of it is held back for new
    cards. Whichever side is short, the other fills the room it left: a file with
    nothing due still gives a whole session of new words, and a day with no new
    words left gives a whole session of reviews.
    """
    wanted_new = new if new_limit is None else min(new, max(0, new_limit))
    if limit is None:
        return min(due, due_limit), wanted_new
    take_new = min(wanted_new, int(limit * NEW_SHARE))
    take_due = min(due, limit - take_new)
    return take_due, min(wanted_new, limit - take_due)


def _space_siblings(
    cards: list[QueueCard], gap: int = SIBLING_GAP, pushes: dict[str, int] | None = None
) -> list[QueueCard]:
    """Push a card back when its note was just asked the other way round.

    Answering ``러시아 → Russia`` and then ``Russia → 러시아`` teaches nothing: the
    second one comes straight out of short-term memory. Greedy and stable, so
    a card only moves when it has to, and the overall order is kept.

    A session filtered to one direction has no note with two cards in it, so
    this does nothing at all — which is right, and wants no case of its own.

    This pass reorders, so it would otherwise quietly undo the order a mark just
    bought; ``pushes`` is how a marked card wins the choice between two cards
    that are equally free to go next.
    """
    pushes = pushes or {}
    remaining = Counter(card.note_id for card in cards)
    out: list[QueueCard] = []
    pending = list(cards)
    while pending:
        # Ask for the full gap, and settle for less rather than for nothing:
        # a queue of two notes cannot keep four apart, but it can still avoid
        # putting a note's two directions next to each other.
        free: list[int] = []
        for window in range(gap, 0, -1):
            recent = {card.note_id for card in out[-window:]}
            free = [i for i, card in enumerate(pending) if card.note_id not in recent]
            if free:
                break
        # A marked card goes first. Then a note that still owes two cards, or it
        # is stranded at the end with nothing to separate its pair — which is
        # why that came first until a lesson practised both ways showed what it
        # costs: every note with two cards due outranked the one word that had
        # been asked for. The gap itself is not at stake either way, because
        # `free` is what enforces it. Ties keep the incoming order.
        index = max(
            free,
            key=lambda i: (pushes.get(pending[i].key, 0), remaining[pending[i].note_id]),
            default=0,
        )
        card = pending.pop(index)
        remaining[card.note_id] -= 1
        out.append(card)
    return out


@dataclass(slots=True)
class Queue:
    """A session's cards, and enough about the scope to say why they are these.

    The counts are what the scope *holds*, not what this queue took, which is
    what lets the screen tell "you are caught up" apart from "there is nothing
    here" — before, an empty list was the only thing the client was told, so it
    had to guess, and it guessed the same sentence every time.
    """

    scheduler: str
    cards: list[QueueCard]
    #: Available in scope, whether or not this queue took them.
    due_count: int = 0
    new_count: int = 0
    later_count: int = 0
    #: Of `later`, how many this queue brought forward.
    ahead_count: int = 0
    #: When the soonest card scheduled for later comes round.
    next_due: datetime | None = None
    #: Which way round this scope can be asked: direction → cards that exist in
    #: it. Counted over the whole scope *before* any direction filter, so the
    #: screen's numbers do not move as you change the choice, and one entry is
    #: how it says a scope has no choice to offer.
    ways: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        """Everything practisable in scope. Zero is the one real dead end."""
        return self.due_count + self.new_count + self.later_count


def due_queue(
    session: Session,
    profile: Profile,
    *,
    category_id: str | None = None,
    file_id: str | None = None,
    group: str | None = None,
    list_id: str | None = None,
    drill: bool = False,
    direction: str | None = None,
    scheduler: str | None = None,
    new_limit: int | None = None,
    limit: int | None = None,
    due_limit: int = 200,
    ahead: bool = True,
    ahead_to: int = 20,
    now: datetime | None = None,
    rng: random.Random | None = None,
    distractor_scope: str | None = None,
    modes: list[str] | None = None,
) -> Queue:
    """Due cards first (most overdue day first), then the new ones.

    Within a day the due cards are **shuffled**, and so are the new cards of
    this session, so you learn the cards rather than the sequence they happen
    to sit in. Which new cards are taken is still decided in page order — you
    work through the book from the front — only their order in the session is
    random. Pass ``rng`` to make a session reproducible.

    ``new_limit`` is a ceiling, not a policy: ``None`` means every unseen card
    in scope, because how much to take on in one sitting is the user's call.

    ``limit`` is that call made for the sitting as a whole, due cards included —
    without it a Start means the entire pile, which on a real collection is an
    hour nobody asked for. ``NEW_SHARE`` of it is kept for new cards so a lesson
    still moves while a backlog drains; see :func:`_shares`.

    ``ahead`` is what makes a scope you chose yourself never a dead end. Once
    the due and new cards run out, the soonest-scheduled are brought forward to
    fill ``ahead_to`` — marked ``early``, and answering one cannot shorten it
    (see ``schedule_answer``). You asked for this lesson; it is not for the app
    to say come back tomorrow.

    ``file_id`` and ``group`` narrow what is *asked* — one lesson, or one
    heading of it, started from its sheet. Distractors still come from the
    whole category, because five words are not four plausible wrong options.

    ``drill`` is **coverage**: everything in scope, due or not, instead of what
    the schedule asked for today. The words that were not due are marked
    ``early``, which is not merely a label — ``schedule_answer`` counts an early
    answer without rescheduling the card, so drilling a word you already know
    cannot cost you the interval you earned. It is the selection half of a
    drill; the other half is the client's own loop, which is where a drill stops
    asking a missed word three cards later (``session.ts``).

    ``list_id`` narrows the scope to one list's words and implies ``drill``,
    because the point of a list is that a test is coming and the schedule does
    not know.

    ``direction`` asks a two-sided note only one way round — ``"fwd"`` for its
    front, ``"rev"`` for its back. A note with one card is simply not in scope
    for the other way, so a one-way note is absent rather than asked backwards.
    Nothing here knows what either side holds; which of them is worth drilling
    is the collection's business. Distractors are unaffected: they come from the
    whole subtree, below, and half a pool is not four plausible wrong options.

    Otherwise a list that is *focused* leads this sitting up to ``FOCUS_SHARE``
    of it, and the rest of the session is filled exactly as it always was. A
    list changes which cards are asked and in what order; it is never written
    into a card's state, and the scheduler is resolved from the category as
    before, so a list cannot move a card to a different ``card_state`` row.
    """
    now = now or datetime.now(UTC)
    rng = rng or random.Random()
    name = resolve_scheduler_name(session, profile, category_id, scheduler)
    allowed, scope = resolve_practice(session, category_id)
    if modes is not None:
        allowed = [m for m in allowed if m in modes]
    scope = distractor_scope or scope

    # A drill is only the list; a focus is only outside one. Drilling list A
    # while list B is focused would be two answers to "what is this sitting
    # for", and the one you just pressed wins. A drill that is *not* a list has
    # no such competing answer, so a focus still leads it: the two are then
    # about different things, one choosing the cards and the other their order.
    on_list = list_id is not None
    drilling = drill or on_list
    wanted = set(members(session, profile, list_id)) if on_list else set()
    focus = set() if on_list else focused(session, profile, now=now)
    names = focus_names(session, profile, now=now) if focus else {}

    query = (
        select(Card, NoteRow, DataFileRow, CardStateRow)
        .join(NoteRow, Card.note_id == NoteRow.id)
        .join(DataFileRow, NoteRow.data_file_id == DataFileRow.id)
        .outerjoin(
            CardStateRow,
            (CardStateRow.card_key == Card.key)
            & (CardStateRow.profile_id == profile.id)
            & (CardStateRow.scheduler == name),
        )
        .where(
            or_(NoteRow.suspended.is_(None), NoteRow.suspended.is_(False)),
            NoteRow.archived_at.is_(None),
            DataFileRow.archived_at.is_(None),
        )
    )
    condition = subtree(session, category_id)
    if condition is not None:
        query = query.where(condition)

    due: list[tuple[datetime, QueueCard]] = []
    new: list[tuple[tuple[int, datetime, int, bool], QueueCard]] = []
    # Scheduled for later: not asked for unless the queue would otherwise end here.
    later: list[tuple[datetime, QueueCard]] = []
    # Every card in the subtree, due or not: a distractor is any other answer
    # of the same kind, not only the ones this session happens to ask about.
    pool: list[Candidate] = []
    accepted_of: dict[str, list[str]] = {}
    ways: dict[str, int] = {}
    for card, note, file, state in session.execute(query):
        prompt, answer, accepted, prompt_lang, answer_lang = _orient(note, file, card.direction)
        heading = note.group
        item = QueueCard(
            key=card.key,
            note_id=note.id,
            direction=card.direction,
            prompt=prompt,
            answer=answer,
            accepted=accepted,
            prompt_lang=prompt_lang,
            answer_lang=answer_lang,
            note=note.note,
            fields=note.fields,
            group=heading.label if heading else None,
            data_file_id=file.id,
            is_new=state is None,
            state=_state_dict(state) if state is not None else None,
            modes=note.modes,
            priority=note.priority or NORMAL,
        )
        pool.append(
            Candidate(
                answer=answer,
                prompt=prompt,
                direction=card.direction,
                note_id=note.id,
                group_id=note.group_id,
                data_file_id=file.id,
            )
        )
        accepted_of[card.key] = accepted
        if file_id is not None and file.id != file_id:
            continue
        if group is not None and (heading.key if heading else None) != group:
            continue
        if on_list and note.id not in wanted:
            continue
        # Counted before the direction filter and after every other one: it is
        # what *this scope* can be asked, which is what the screen offers.
        ways[card.direction] = ways.get(card.direction, 0) + 1
        if direction is not None and card.direction != direction:
            continue
        if state is None:
            # Page order, forward before reverse: it decides which new cards
            # this session takes, not the order they are asked in (shuffled below).
            # The file's own age breaks a tie, so one lesson is worked through
            # before the next instead of six being interleaved.
            new.append(
                (
                    (file.position, file.created_at, note.position, card.direction != Direction.FWD),
                    item,
                )
            )
        elif state.due is None or state.due <= now:
            due.append((state.due or now, item))
        else:
            later.append((state.due, item))

    pushes = _mark(session, profile, [item for _, item in (*due, *new, *later)], focus=focus, names=names)
    rng.shuffle(due)
    # A marked word goes ahead of a backlog, not merely ahead of the rest of
    # today: "first" is not much of a promise when forty cards are overdue.
    # Within one level the order is the old one exactly — most overdue day
    # first, shuffled inside the day by the stable sort above.
    due.sort(key=lambda pair: (-pushes.get(pair[1].key, 0), pair[0].date()))
    # Before page order, because here the mark decides which cards are *taken*
    # and not just when they are asked: a cap, or a batch packed for a journey,
    # should spend what it has on the words that were asked for.
    new.sort(key=lambda pair: (-pushes.get(pair[1].key, 0), pair[0]))
    # The focused list leads, up to its share of a sitting that has a size: its
    # due words first, then its words not met yet, and then — because a test on
    # Friday is not something the schedule knows about — its words that are not
    # wanted until next week, brought forward. With nothing focused all three
    # held lists are empty and every number below is the one it always was.
    held_due, plain_due = _split(due, focus)
    held_new, plain_new = _split(new, focus)
    held_later, plain_later = _split(later, focus)
    room = None if limit is None else int(limit * FOCUS_SHARE)
    lead_due = held_due if room is None else held_due[:room]
    left = None if room is None else room - len(lead_due)
    lead_new = held_new if left is None else held_new[:left]
    left = None if left is None else left - len(lead_new)
    held_later.sort(key=lambda pair: pair[0])
    lead_later = held_later if left is None else held_later[:left]
    for _, item in lead_later:
        # `early` is not merely a label: `schedule_answer` counts an answer given
        # this far ahead without rescheduling the card, so a test cannot cost you
        # the interval a word had already earned.
        item.early = True
    spent_new = len(lead_new)
    take_due, take_new = _shares(
        len(plain_due),
        len(plain_new),
        limit=None if limit is None else limit - len(lead_due) - spent_new - len(lead_later),
        new_limit=None if new_limit is None else max(0, new_limit - spent_new),
        due_limit=max(0, due_limit - len(lead_due)),
    )
    chosen_new = [c for _, c in (*lead_new, *plain_new[:take_new])]  # taken in that order...
    rng.shuffle(chosen_new)  # ...but not asked in it
    chosen_new.sort(key=lambda c: -pushes.get(c.key, 0))  # stable: shuffled within a level
    cards = _space_siblings(
        [c for _, c in (*lead_due, *lead_later, *plain_due[:take_due])], pushes=pushes
    ) + _space_siblings(chosen_new, pushes=pushes)

    brought: list[QueueCard] = []
    # A session with a size asked for is never filled past it: bringing cards
    # forward is there to rescue an empty scope, not to overrule the size.
    room = ahead_to if limit is None else min(ahead_to, limit)
    if drilling:
        # Not a backlog topped up to look busy: the whole scope, because a word
        # left out is a word you meet first in the exam. The size asked for is
        # still the size: `limit` caps a drill exactly as it caps a sitting.
        room = len(cards) + len(later) if limit is None else limit
    if (ahead or drilling) and len(cards) < room:
        # Soonest first, marks and all: bringing a card forward is a liberty
        # taken with the schedule, and the least disruptive one stays the
        # soonest one. A card brought forward still carries its own mark.
        plain_later.sort(key=lambda pair: pair[0])
        brought = [c for _, c in plain_later[: room - len(cards)]]
        for item in brought:
            item.early = True
        cards += _space_siblings(brought, pushes=pushes)

    _annotate(cards, pool, accepted_of, allowed=allowed, scope=scope, rng=rng)
    return Queue(
        scheduler=name,
        cards=cards,
        due_count=len(due),
        new_count=len(new),
        later_count=len(later),
        ahead_count=len(brought),
        next_due=min((at for at, _ in later), default=None),
        ways=ways,
    )


def _annotate(
    cards: list[QueueCard],
    pool: list[Candidate],
    accepted_of: dict[str, list[str]],
    *,
    allowed: list[str],
    scope: str,
    rng: random.Random,
) -> None:
    """Give each card its wrong options and the mode its state asks for."""
    for card in cards:
        card.distractors = distractors_for(
            _as_candidate(card, pool),
            pool,
            scope=scope,
            excluded=accepted_of.get(card.key, []),
            rng=rng,
        )
        interval = None if card.is_new else float((card.state or {}).get("interval_days") or 0.0)
        card.suggest = suggest_mode(
            interval_days=interval,
            answer=card.answer,
            allowed=[m for m in allowed if m in (card.modes or allowed)],
            has_distractors=len(card.distractors) >= CHOICE_OPTIONS - 1,
        )


def _as_candidate(card: QueueCard, pool: list[Candidate]) -> Candidate:
    """The pool entry for this very card — it knows which group the note is in."""
    for entry in pool:
        if entry.note_id == card.note_id and entry.direction == card.direction:
            return entry
    return Candidate(
        answer=card.answer,
        prompt=card.prompt,
        direction=card.direction,
        note_id=card.note_id,
        group_id=None,
        data_file_id=card.data_file_id,
    )


def resolve_practice(session: Session, category_id: str | None) -> tuple[list[str], str]:
    """Allowed modes and distractor scope for a subtree, inherited (PLAN 3.3).

    Practising *everything* spans every root at once, so the answer is what all
    of them agree on: a mode only one subject allows is not offered across the
    whole collection, and the scope falls back to ``auto`` where they differ.
    """
    if category_id:
        category = session.get(Category, category_id)
        config = category_config(session, category) if category is not None else CategoryConfig()
        return effective_modes(config), effective_distractor_scope(config)

    roots = session.scalars(select(Category).where(Category.parent_id.is_(None))).all()
    configs = [category_config(session, root) for root in roots]
    if not configs:
        return effective_modes(CategoryConfig()), "auto"
    shared = [m for m in effective_modes(configs[0]) if all(m in effective_modes(c) for c in configs)]
    scopes = {effective_distractor_scope(c) for c in configs}
    return shared or effective_modes(CategoryConfig()), scopes.pop() if len(scopes) == 1 else "auto"


def _state_dict(row: CardStateRow) -> dict[str, Any]:
    return CardState(
        due=row.due,
        state=row.state or "new",
        interval_days=row.interval_days or 0.0,
        reps=row.reps,
        lapses=row.lapses,
        last_review=row.last_review,
        data=row.data or {},
    ).dump()


def record_answer(
    session: Session,
    profile: Profile,
    answer: AnswerIn,
    *,
    scheduler: str,
) -> CardState:
    """Append to the log and update the cached state. The log is never rewritten."""
    card = session.get(Card, answer.card_key)
    if card is None:
        raise KeyError(f"no such card: {answer.card_key}")

    now = answer.at or datetime.now(UTC)
    impl = get_scheduler(scheduler)
    row = session.get(CardStateRow, (profile.id, card.key, impl.name))
    before = CardState.load(_state_dict(row)) if row is not None else impl.initial()

    grade = grade_for(answer.mode, answer.outcome, answer.grade)
    after = schedule_answer(impl, before, answer.mode, grade, now=now, overridden=answer.overridden)
    _store_state(session, profile, card.key, impl.name, after)

    session.add(
        ReviewLog(
            profile_id=profile.id,
            card_key=card.key,
            ts=now,
            mode=answer.mode,
            direction=card.direction,
            raw_answer=answer.raw_answer,
            outcome=answer.outcome,
            overridden=answer.overridden,
            final_grade=int(grade),
            duration_ms=answer.duration_ms,
            scheduler=impl.name,
            state_before=before.dump(),
            state_after=after.dump(),
        )
    )
    session.flush()
    return after


def _store_state(session: Session, profile: Profile, card_key: str, scheduler: str, state: CardState) -> None:
    """Write the cached state. It is only ever a cache — ``replay`` can rebuild it."""
    row = session.get(CardStateRow, (profile.id, card_key, scheduler))
    if row is None:
        row = CardStateRow(profile_id=profile.id, card_key=card_key, scheduler=scheduler)
        session.add(row)
    row.due = state.due
    row.state = str(state.state)
    row.interval_days = state.interval_days
    row.reps = state.reps
    row.lapses = state.lapses
    row.last_review = state.last_review
    row.data = state.data


def replay(session: Session, profile: Profile, card_key: str, scheduler: str) -> CardState:
    """Rebuild a card's state from the log alone — why the log is append-only (PLAN 5)."""
    impl = get_scheduler(scheduler)
    state = impl.initial()
    logs = session.scalars(
        select(ReviewLog)
        .where(ReviewLog.profile_id == profile.id, ReviewLog.card_key == card_key)
        .order_by(ReviewLog.ts, ReviewLog.id)
    )
    for log in logs:
        grade = Grade(log.final_grade or Grade.AGAIN)
        state = schedule_answer(impl, state, log.mode or "flip", grade, now=log.ts, overridden=log.overridden)
    return state


@dataclass(slots=True)
class AnswerRow:
    """One answer recorded away from the server, with its own id and its own clock.

    ``client_id`` is the client's, not ours: it is what lets the same batch be
    offered twice — once over the wire, once as a file carried by hand — without
    being counted twice.
    """

    client_id: str
    at: datetime
    card_key: str
    mode: str
    outcome: str | None = None
    grade: int | None = None
    overridden: bool = False
    raw_answer: str | None = None
    duration_ms: int | None = None
    scheduler: str | None = None


@dataclass(slots=True)
class Ingested:
    """What a batch did. ``unknown`` names cards that have since been deleted."""

    accepted: int = 0
    duplicates: int = 0
    unknown: list[str] = field(default_factory=list)
    #: Cards whose cached state had to be rebuilt from the log.
    rebuilt: int = 0
    #: Client ids of rows that could not be graded at all. Named rather than
    #: raised: a batch is one device's whole backlog, and refusing the lot for
    #: one bad row leaves the sender retrying it for ever with nowhere to go.
    rejected: list[str] = field(default_factory=list)


def ingest_answers(
    session: Session,
    profile: Profile,
    rows: Iterable[AnswerRow],
    *,
    scheduler: str,
) -> Ingested:
    """Take answers earned elsewhere into the log, then rebuild what they changed.

    These rows can be older than rows already here — a phone carried around for a
    week hands back a session from Tuesday — so the cached state is not nudged
    forward the way ``record_answer`` nudges it. It is replayed from the log, which
    is the whole reason the log is append-only (PLAN 5). ``state_before`` and
    ``state_after`` stay null on these rows: they were never scheduled live, and
    inventing them would mean writing a history that did not happen.

    A row that cannot be graded is named in ``rejected`` rather than raised. The
    sender has no way to mend it and no way to put it down, so refusing the whole
    batch for one of them wedges that device's outbox permanently.
    """
    report = Ingested()
    batch: dict[str, AnswerRow] = {}
    for row in sorted(rows, key=lambda r: r.at):
        if row.client_id in batch:
            report.duplicates += 1  # offered twice inside one batch
            continue
        batch[row.client_id] = row
    if not batch:
        return report

    already = set(
        session.scalars(
            select(ReviewLog.client_id).where(
                ReviewLog.profile_id == profile.id, ReviewLog.client_id.in_(batch)
            )
        )
    )
    touched: set[tuple[str, str]] = set()
    for row in batch.values():
        if row.client_id in already:
            report.duplicates += 1
            continue
        card = session.get(Card, row.card_key)
        if card is None:
            report.unknown.append(row.card_key)
            continue
        name = get_scheduler(row.scheduler or scheduler).name
        try:
            final_grade = int(grade_for(row.mode, row.outcome, row.grade))
        except ValueError:
            # No outcome and no grade: nothing to record but the fact of it.
            report.rejected.append(row.client_id)
            continue
        session.add(
            ReviewLog(
                profile_id=profile.id,
                card_key=card.key,
                ts=row.at,
                client_id=row.client_id,
                mode=row.mode,
                direction=card.direction,
                raw_answer=row.raw_answer,
                outcome=row.outcome,
                overridden=row.overridden,
                final_grade=final_grade,
                duration_ms=row.duration_ms,
                scheduler=name,
            )
        )
        report.accepted += 1
        touched.add((card.key, name))
    session.flush()

    # A card may be cached under both schedulers; whichever exists has to be honest.
    for card_key, name in sorted(touched):
        names = {name} | set(
            session.scalars(
                select(CardStateRow.scheduler).where(
                    CardStateRow.profile_id == profile.id, CardStateRow.card_key == card_key
                )
            )
        )
        for each in names:
            _store_state(session, profile, card_key, each, replay(session, profile, card_key, each))
        report.rebuilt += 1
    session.flush()
    return report
