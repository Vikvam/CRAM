"""What a word's mark is worth, once you take account of knowing it.

A test is coming, twenty words are on it, and they should dominate the next few
sessions — then stop dominating, without anyone going back to unmark them. So
the mark the person sets is only half of it: the other half is how well the card
is already known, which :func:`memo.overview.progress.standing` reads off the
review log and re-derives every time it is asked. That is what makes the damping
reversible for free. Points never decay, but the accuracy window takes a card
back down the moment it starts going wrong, and with it the push comes straight
back — nothing is stored, nothing has to expire, and the Progress screen and the
queue cannot disagree about whether a word is known.

The bucket is the **card's**, not the note's, so a word whose → is mastered keeps
its full push on ←. Knowing a word in one direction is not knowing it.
"""

from __future__ import annotations

from memo.models.datafile import NORMAL, Priority
from memo.overview.progress import KNOWN, LEARNING, MASTERED, NEW

#: The four levels as the control offers them, lowest first.
LEVELS = (Priority.LOW.value, NORMAL, Priority.HIGH.value, Priority.CRUCIAL.value)

#: What a mark is worth, by how well the card is already known.
#:
#: ``3`` asked ahead of everything and twice · ``2`` asked first and asked twice ·
#: ``1`` asked first · ``0`` nothing · ``-1`` asked last.
#:
#: A high mark loses its second ask at ``known`` and the rest at ``mastered``:
#: once a word is reliably right it stops taking two slots a session away from
#: the words that are not. It cannot be damped away by the session doing the
#: practising, because ``mastered`` is unreachable inside one sitting
#: (``MASTERY_SPREAD``) — which is the other half of why this is safe.
#:
#: ``crucial`` damps one step later and never all the way: still asked twice at
#: ``known``, and still asked first once ``mastered``. Those are the words that
#: must not be lost, so a mastered one keeps getting looked at.
#:
#: ``low`` is not damped. Damping withdraws a boost a word no longer needs; it
#: has no business overruling "I care about this one less".
PUSH: dict[tuple[str, str], int] = {
    (Priority.CRUCIAL, NEW): 3,
    (Priority.CRUCIAL, LEARNING): 3,
    (Priority.CRUCIAL, KNOWN): 2,
    (Priority.CRUCIAL, MASTERED): 1,
    (Priority.HIGH, NEW): 2,
    (Priority.HIGH, LEARNING): 2,
    (Priority.HIGH, KNOWN): 1,
    (Priority.HIGH, MASTERED): 0,
    (Priority.LOW, NEW): -1,
    (Priority.LOW, LEARNING): -1,
    (Priority.LOW, KNOWN): -1,
    (Priority.LOW, MASTERED): -1,
}

#: At this much push a card is asked a second time in the same sitting.
TWICE_AT = 2

#: What being on a focused list is worth, by how well the card is already known.
#:
#: **One, not two.** A push of :data:`TWICE_AT` or more asks the card twice, so
#: twenty focused words would be forty slots — a whole ordinary sitting. A list
#: does not need to buy its place that way: it is already guaranteed a share of
#: the sitting, which is what asking twice exists to make up for.
#:
#: **Nothing at mastered**, because a test needs the words you have not got. The
#: damping is read back off the log exactly as a mark's is, so a focused word
#: that starts going wrong has its push again without anyone asking.
FOCUS_PUSH: dict[str, int] = {NEW: 1, LEARNING: 1, KNOWN: 1, MASTERED: 0}


def push(priority: str | None, bucket: str, *, focused: bool = False) -> int:
    """How far up the queue this card goes: ``-1`` to ``3``.

    An unmarked word, and anything the table has nothing to say about, is ``0``
    — the queue then orders exactly as it did before there were marks.

    A word on a focused list takes **the better** of its mark and its focus, so
    the two compose rather than overruling one another: a ``crucial`` word on a
    test list keeps its second ask, and a ``low`` one stops being asked last for
    as long as the test is coming. Marks carry importance, lists carry urgency,
    and a focus never writes anything to the note.
    """
    marked = 0 if priority is None else PUSH.get((priority, bucket), 0)
    if not focused:
        return marked
    return max(marked, FOCUS_PUSH.get(bucket, 0))


def effective(priority: str | None, bucket: str) -> str:
    """The mark as it stands now — what the badge may honestly claim.

    A mastered word that was marked high reads ``normal``, because the push it
    had is gone and a badge saying otherwise would be describing the setting
    rather than the session. A mark with any push left reads as itself.

    A focus is deliberately **not** an argument here. It is not a mark and must
    not be able to read as one: a card carries the focused list's name instead,
    which says why it came up without claiming something about the note.
    """
    n = push(priority, bucket)
    if n > 0:
        return str(priority)
    if n < 0:
        return Priority.LOW.value
    return NORMAL
