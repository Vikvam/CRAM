"""Request and response shapes. The frontend's types are generated from these via OpenAPI."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from memo.models.category import ALL_MODES


class LoginIn(BaseModel):
    password: str = ""


class AuthStatus(BaseModel):
    signed_in: bool
    gate_open: bool
    profile: str | None = None


class PracticeSet(BaseModel):
    """What a category says about practice itself. ``None`` means "ask my parent"."""

    modes: list[str] | None = None
    distractor_scope: str | None = None


class PracticeResolved(BaseModel):
    """And what that comes to once the tree above it has been applied."""

    modes: list[str]
    distractor_scope: str


class CategoryOut(BaseModel):
    id: str
    parent_id: str | None
    path: str
    slug: str
    label: dict[str, str] | None
    #: This category's own practice settings, and the inherited result.
    practice: PracticeSet = PracticeSet()
    practice_resolved: PracticeResolved = PracticeResolved(modes=list(ALL_MODES), distractor_scope="auto")
    #: Counts for this category's own data files; the client sums a subtree.
    notes: int = 0
    cards: int = 0
    due: int = 0
    new: int = 0


class CategoryIn(BaseModel):
    path: str = Field(min_length=1, description="e.g. korean/book1/02-introduction")
    label: dict[str, str] | None = None


class DataFileSummary(BaseModel):
    id: str
    category_id: str
    #: One plain line, whatever scripts it mixes — not a language map (PLAN 3.1).
    title: str | None
    notes: int
    created_at: datetime
    default_type: Literal["bidirectional", "directional"] | None = None
    front_lang: str | None = None
    back_lang: str | None = None
    archived: bool = False


class ImporterOut(BaseModel):
    name: str
    description: str
    #: ``builtin``, or ``local`` for one loaded from this machine's importer folder.
    origin: str = "builtin"
    #: What it reads: ``image``, ``pdf``, ``text``.
    kinds: list[str] = []


class ImportPageOut(BaseModel):
    id: str
    position: int
    path: str | None
    page_number: int | None
    status: str
    error: str | None


class ImportJobOut(BaseModel):
    id: str
    category_id: str | None
    importer: str | None
    status: str
    error: str | None
    router_reason: str | None = None
    pages: list[ImportPageOut]
    draft: dict[str, Any] | None
    target_data_file_id: str | None
    created_at: datetime


class ImportJobPatch(BaseModel):
    """Where a staged job is headed. Unset fields are left alone; an explicit
    ``target_data_file_id: null`` means "a new data file"."""

    category_id: str | None = None
    target_data_file_id: str | None = None


class QueueCardOut(BaseModel):
    key: str
    note_id: str
    direction: Literal["fwd", "rev"]
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
    #: Scheduled for later and brought forward because this scope was asked for.
    early: bool = False
    #: How often this word should come up, as it stands now: the mark that was
    #: set, damped by how well this card is already known. `normal` is the middle.
    priority: Literal["low", "normal", "high", "crucial"] = "normal"
    #: Asked a second time in the same sitting.
    twice: bool = False
    #: The focused list that pushed this card up, by name — "Friday test" rather
    #: than a mark, because a list is not a property of the note.
    focus: str | None = None
    modes: list[str] | None = None
    #: Wrong options for `choice`, best first; fewer than three means no choice.
    distractors: list[str] = []
    #: What this card's state asks to be practised as (PLAN 3.5).
    suggest: Literal["flip", "typed", "choice", "match", "build"] = "typed"


class QueueOut(BaseModel):
    scheduler: str
    #: The modes this subtree allows, in UI order — the session picks from these.
    modes: list[str]
    #: Where distractors came from: auto | group | file | category.
    distractor_scope: str
    cards: list[QueueCardOut]
    #: What the scope holds, so an empty queue can say which kind of empty it is.
    due_count: int = 0
    new_count: int = 0
    #: How many of `cards` were brought forward from later.
    ahead_count: int = 0
    #: Everything practisable in scope; zero is the only real dead end.
    total: int = 0
    #: When the soonest card scheduled for later comes round.
    next_due: datetime | None = None
    #: Which way round this scope can be asked — ``fwd``/``rev`` to how many cards
    #: exist in it, counted before any direction filter. One entry means the scope
    #: has no choice to offer and the control is not shown.
    ways: dict[str, int] = {}
    #: Seconds one card costs in a sitting, measured off this profile's own log —
    #: so the start screen can say how long a session of a given size will take.
    #: Null when there is too little history to say, which is shown as nothing.
    seconds_per_card: float | None = None


class AnswerBody(BaseModel):
    card_key: str
    mode: Literal["flip", "typed", "choice", "match", "build"]
    outcome: Literal["correct", "almost", "wrong"] | None = None
    grade: int | None = Field(default=None, ge=1, le=4, description="flip grade, or an override")
    overridden: bool = False
    raw_answer: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    scheduler: str | None = None


class AnswerOut(BaseModel):
    card_key: str
    scheduler: str
    state: dict[str, Any]


class AnswerRowIn(AnswerBody):
    """An answer earned with no server to tell: it brings its own id and its own clock."""

    #: The client's id for this answer. Unique per profile, so handing the same
    #: batch back twice — over the wire and as a file — still logs it once.
    client_id: str = Field(min_length=1, max_length=32)
    at: datetime


class AnswersBody(BaseModel):
    rows: list[AnswerRowIn] = Field(max_length=5000)


class AnswersOut(BaseModel):
    accepted: int
    duplicates: int
    #: Cards that no longer exist. Their answers are dropped; the rest still land.
    unknown: list[str]
    rebuilt: int
    #: Client ids of rows carrying neither an outcome nor a grade. Settled, not
    #: pending: the sender cannot mend them and must be able to stop offering them.
    rejected: list[str] = []


class AcceptIn(BaseModel):
    side: Literal["front", "back"]
    value: str = Field(min_length=1)


class AcceptOut(BaseModel):
    note_id: str
    side: str
    accepted: list[str]


class SettingsOut(BaseModel):
    profile: str
    scheduler: str
    schedulers: list[str]
    llm_configured: bool
    llm_model: str
    structured_output: str | None


class SettingsIn(BaseModel):
    scheduler: str | None = None


# --- editing (PLAN 6, phase 2) ----------------------------------------------


class CategoryPatch(BaseModel):
    """Any subset; ``parent_id`` is set to null to make the category a root."""

    slug: str | None = None
    label: dict[str, str] | None = None
    parent_id: str | None = None
    #: Unset keys are left alone; an explicit null goes back to inheriting.
    practice: PracticeSet | None = None


class DataFileIn(BaseModel):
    title: str | None = None
    default_type: Literal["bidirectional", "directional"] | None = None
    front_lang: str | None = None
    back_lang: str | None = None
    slug: str | None = None
    tags: list[str] | None = None


class DataFilePatch(DataFileIn):
    category_id: str | None = None


class GroupOut(BaseModel):
    key: str
    label: dict[str, str] | None
    note: str | None


class NoteOut(BaseModel):
    """A row of the grid editor. Mirrors the data-file note, plus what only the
    database knows: how many cards it has and whether it has been archived."""

    id: str
    data_file_id: str
    position: int
    type: Literal["bidirectional", "directional"] | None
    front: str | None
    back: str | None
    front_lang: str | None
    back_lang: str | None
    fields: dict[str, str | None] | None
    accept: dict[str, list[str]] | None
    modes: list[str] | None
    note: str | None
    group: str | None
    tags: list[str] | None
    status: str | None
    confidence: float | None
    suspended: bool | None
    #: low | high | crucial, and null for the ordinary middle (PLAN 3.2).
    priority: str | None
    page: int | None
    cards: int
    reviewed: int
    archived: bool
    #: new | learning | known — the weaker of the note's two directions (PLAN 6, phase 4).
    progress: Literal["new", "learning", "known", "mastered"] = "new"


class NotesOut(BaseModel):
    file: DataFileSummary
    groups: list[GroupOut]
    notes: list[NoteOut]


# --- overview (PLAN 6, phase 4) ---------------------------------------------


class MasteryRuleOut(BaseModel):
    """The thresholds the buckets are drawn at, so the page can say what it means.

    Sent rather than duplicated in the client, because these are the numbers a
    reader will ask about and there must be one answer to that question.
    """

    known_points: int
    mastered_points: int
    #: Of ``mastered_points``, how many must come from typing the answer.
    writing_points: int
    min_reviews: int
    rate_percent: int
    rate_window: int
    #: Hours the points must span before a card can be mastered: it cannot be
    #: done in one sitting, however consistently right the answers are.
    spread_hours: int


class MasteryOut(BaseModel):
    """One category of the mastery bars, counting everything under it."""

    category_id: str
    path: str
    label: dict[str, str] | None
    depth: int
    #: Notes, not cards: a word asked both ways is one, at its weaker direction.
    notes: int
    new: int
    learning: int
    known: int
    #: Mastered, plus known words marked low while anything else in scope is not.
    mastered: int
    #: How many of ``mastered`` are those low words.
    settled: int


class FileMasteryOut(BaseModel):
    """One lesson's four buckets, under the category it belongs to."""

    data_file_id: str
    category_id: str
    title: str | None
    notes: int
    new: int
    learning: int
    known: int
    #: Mastered, plus known words marked low while anything else in scope is not.
    mastered: int
    #: How many of ``mastered`` are those low words.
    settled: int


class GroupMasteryOut(BaseModel):
    """One heading of a lesson. ``key`` is null for the notes under no heading."""

    key: str | None
    label: dict[str, str] | None
    notes: int
    new: int
    learning: int
    known: int
    mastered: int
    settled: int


class WeakCardOut(BaseModel):
    """A card on the weak list, with the reason it is on it."""

    card_key: str
    note_id: str
    data_file_id: str
    file_title: str | None
    category_path: str
    group: dict[str, str] | None
    #: The heading's own key, which is what to show when it has no label.
    group_key: str | None
    direction: Literal["fwd", "rev"]
    prompt: str
    answer: str
    wrong: int
    answers: int
    lapses: int
    last_wrong: datetime | None
    interval_days: float | None


class DayOut(BaseModel):
    day: date
    reviews: int
    correct: int


class WordOut(BaseModel):
    """One note as a list of words shows it: ``prompt`` is the front.

    ``card_key`` and ``direction`` name the direction holding it in its bucket.
    """

    card_key: str
    note_id: str
    direction: Literal["fwd", "rev"]
    prompt: str
    answer: str
    data_file_id: str
    file_title: str | None
    group: dict[str, str] | None
    #: The heading's own key, which is what to show when it has no label.
    group_key: str | None
    #: When the note entered the bucket it is in. Null for one never answered.
    since: datetime | None


class WordsOut(BaseModel):
    bucket: str
    #: Everything in the bucket, not only this page of it.
    total: int
    words: list[WordOut]


class FileProgressOut(BaseModel):
    """One lesson in full: its counts, each heading's, and its words by bucket."""

    file: FileMasteryOut
    groups: list[GroupMasteryOut]
    #: ``mastered``, ``known``, ``learning`` and ``new``, each whole.
    words: dict[str, list[WordOut]]


class NoteHitOut(BaseModel):
    """One note as a search result lists it — a word, not a direction.

    Note-shaped on purpose: a card is one way round, and what you searched for
    was the word. ``forward`` and ``reverse`` are how well each direction is
    known, and are null only for a direction the note has no card for.
    """

    note_id: str
    front: str
    back: str
    accept: dict[str, list[str]] | None
    note: str | None
    #: The mark as it is *set*, ``normal`` for the absence of one. Not damped:
    #: damping is a property of a session, and this is the collection.
    priority: Literal["low", "normal", "high", "crucial"]
    suspended: bool
    archived: bool
    data_file_id: str
    file_title: str | None
    category_id: str
    category_path: str
    group: dict[str, str] | None
    group_key: str | None
    forward: Literal["new", "learning", "known", "mastered"] | None
    reverse: Literal["new", "learning", "known", "mastered"] | None
    #: Which field matched, and how much of it — enough for a row to explain
    #: itself when the word you typed is nowhere in what you can see. Both null
    #: for a word that was fetched by id rather than searched for.
    where: Literal["front", "back", "accept", "note", "group", "file"] | None = None
    how: Literal["exact", "prefix", "part"] | None = None


class SearchOut(BaseModel):
    #: Echoed back, so a late response can be told from the current query.
    q: str
    #: Everything matching, not only this page of it.
    total: int
    hits: list[NoteHitOut]


class ListOut(BaseModel):
    """A named set of words, and whether its focus is still running."""

    id: str
    name: str
    note: str | None
    #: While this is ahead, the list's words lead a sitting. Null is a list that
    #: simply exists; a date gone by is a list whose test has been.
    focus_until: datetime | None
    focused: bool
    #: How many words are on it.
    count: int
    created_at: datetime


class ListsOut(BaseModel):
    lists: list[ListOut]


class ListIn(BaseModel):
    name: str
    note: str | None = None
    focus_until: datetime | None = None


class ListPatchIn(BaseModel):
    """Every field optional, and null means *clear it* rather than *leave it*.

    Ending a focus is setting ``focus_until`` to null, so the two cannot be the
    same thing: which fields were actually sent is what tells them apart.
    """

    name: str | None = None
    note: str | None = None
    focus_until: datetime | None = None


class ListNotesIn(BaseModel):
    """Which words to add: these ones, or a whole lesson, or one heading of one.

    A heading is the bulk gesture this app has — it is how the textbook prints a
    set, and practice can already take one on its own.
    """

    note_ids: list[str] | None = None
    file_id: str | None = None
    group: str | None = None


class ListWordsOut(ListOut):
    """The list itself, and the words on it in the shape a search result has."""

    words: list[NoteHitOut]


class AuditNoteOut(BaseModel):
    note_id: str
    front: str | None
    back: str | None
    file_title: str | None
    data_file_id: str | None
    category_path: str


class AuditFindingOut(BaseModel):
    """Notes that belong together in a way nobody asked for."""

    #: The folded text they share — the gloss, or the word and gloss together.
    key: str
    notes: list[AuditNoteOut]


class AuditOut(BaseModel):
    """What is wrong with the collection as practice would meet it.

    ``clean`` is defined from the first three only. The last two are hints that
    the CLI has always printed and the API used to compute and throw away: a
    screen should not *interrupt* for them, but ``near`` is the same signal that
    answers "what else do I know that means this", so dropping it was a waste.
    """

    clean: bool
    #: Notes sharing a gloss, so that gloss is an unanswerable prompt.
    collisions: list[AuditFindingOut]
    #: Same word *and* same gloss: one note learned twice, its history split.
    duplicates: list[AuditFindingOut]
    #: A takes B's word as an answer but B does not take A's, so one way still fails.
    one_sided: list[AuditFindingOut]
    #: Sharing a gloss once a trailing ``(…)`` is dropped — a hint, not a fault.
    near: list[AuditFindingOut] = []
    #: Shared glosses that are fine, because every member accepts the others.
    resolved: list[AuditFindingOut] = []


class RelatedOut(BaseModel):
    """One other word in the collection, and what it has to do with this one.

    There are no antonyms here and cannot be: nothing in a note records that one
    word is the opposite of another. ``same-heading`` is what stands in for it,
    because a textbook prints 위 beside 밑 for exactly that reason.
    """

    note_id: str
    front: str | None
    back: str | None
    data_file_id: str
    file_title: str | None
    group: dict[str, str] | None
    group_key: str | None
    suspended: bool
    how: Literal["same-meaning", "near-meaning", "same-heading"]
    #: This word takes the other's spelling as an answer, and the other way about.
    #: One true and the other false is the case worth fixing.
    accepts: bool
    accepted_by: bool


class RelatedListOut(BaseModel):
    note_id: str
    related: list[RelatedOut]


class ProgressOut(BaseModel):
    scheduler: str
    #: What it takes to reach each bucket, so the client can say what it means.
    rule: MasteryRuleOut
    #: How far back the weak list looked.
    window_days: int
    mastery: list[MasteryOut]
    files: list[FileMasteryOut]
    weak: list[WeakCardOut]
    activity: list[DayOut]
    #: A few words from each list, for the strips on the page. The whole of any
    #: of them is behind ``GET /progress/words``.
    mastered: list[WordOut] = []
    unseen: list[WordOut] = []
    #: Words left out of practice on purpose. A count, because the strip for it
    #: only appears when there are any.
    set_aside: int = 0


class NoteIn(BaseModel):
    """A note as the editor sends it. Unset fields are left alone on a patch."""

    model_config = {"extra": "forbid"}

    type: Literal["bidirectional", "directional"] | None = None
    front: str | None = None
    back: str | None = None
    front_lang: str | None = None
    back_lang: str | None = None
    fields: dict[str, str | None] | None = None
    accept: dict[str, list[str]] | None = None
    modes: list[str] | None = None
    note: str | None = None
    group: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    confidence: float | None = None
    suspended: bool | None = None
    #: low | normal | high | crucial — `normal` clears the mark, since the control that
    #: sets one has three buttons and the middle of them is the absence.
    priority: Literal["low", "normal", "high", "crucial"] | None = None
    page: int | None = None


class NotesIn(BaseModel):
    notes: list[NoteIn] = Field(min_length=1, max_length=500)


class DuplicateOut(BaseModel):
    note_id: str
    front: str | None
    back: str | None
    data_file_id: str
    file_title: str | None
    category_id: str
    category_path: str
    same_back: bool
    #: Which side matched: the same prompt, or the same meaning on another word.
    by: Literal["front", "back"] = "front"


class DuplicateRow(BaseModel):
    """Duplicates found for one row of what was sent, by its index."""

    index: int
    matches: list[DuplicateOut]


class DuplicateCheckIn(BaseModel):
    pairs: list[tuple[str | None, str | None]] = Field(max_length=500)
    category_id: str | None = None
    exclude_note_ids: list[str] = Field(default_factory=list)


class DuplicateCheckOut(BaseModel):
    rows: list[DuplicateRow]


class NotesCreatedOut(BaseModel):
    notes: list[NoteOut]
    duplicates: list[DuplicateRow]


class ReorderIn(BaseModel):
    note_ids: list[str]


class ExportIn(BaseModel):
    """Empty exports the whole collection; a category exports that subtree."""

    category_id: str | None = None


class ExportedFileOut(BaseModel):
    data_file_id: str
    path: str
    notes: int


class ExportOut(BaseModel):
    root: str
    files: list[ExportedFileOut]
    categories: int
    photos: int
    notes: int
    #: JSON files in the tree this export did not write — nothing is ever deleted.
    unknown: list[str]
