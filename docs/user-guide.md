# Using memo

memo is a flashcard app for your own material: photograph a page or bring a file, check what it
read, then practise. It schedules what to ask next from how you answered (FSRS or SM-2), and asks in
several ways, from picking the answer up to writing it from memory.

The words used here:

- **Collection**: everything you have, as a tree of **categories** (folders, e.g. *Korean › Book 1*).
- **Data file**, or **lesson**: one page's or chapter's worth of notes, inside a category.
- **Heading**: a section inside a data file, as printed in the source.
- **Note**: one item, a **front** and a **back**. A note asked *both ways* makes two cards
  (front → back and back → front), and each has its own schedule.

The navigation at the top is **Collection**, **Progress** and **Settings**.

## Setting up

Starting the server is in the [root README](../README.md#quick-start). Reaching it from a phone,
safely and with offline practice, is in [serving.md](serving.md). Everything below happens in the
browser.

## Getting material in

On **Collection**, make a category first if you need one (**Manage → New category**). A path such
as `korean/book1/03-daily-life` creates every level that is missing. Then press **Add pages** on its
row.

**From photos.** Use **Take a photo** or **Choose photos**. Drag across a photo to crop it, use **↻**
to rotate it and **↑ ↓** to reorder. *Anything the reader should know* is optional: say what to keep
or leave out, or which way to ask, as you would to a person (the page is read with the prompt in
[llm-prompt.md](llm-prompt.md)). If the server has importers of its own, *How to read these pages*
offers them, and can be left to the app. *Printed
number of the first page* is optional. Press **Read N pages**. You can leave while it reads: the
import waits on Collection under its category, marked *reading* and then *ready*. Photos need an LLM
provider configured on the server. Settings → *Reading pages* says whether one is.

**From a PDF.** Pick it with **Choose data files**; it is read the same way as photos, a few pages
at a time. *How to read the PDF* is either *Its text* (cheaper, and any model can do it) or *Its pages
as pictures* (for tables, layout, or a scan). A scanned PDF has no text, so it is sent as pictures
either way. Photos and PDFs can go in one import.

**From a file.** **Choose data files** also takes `.json`, `.csv`/`.tsv`, `.txt`/`.md` (one pair per
line), or an Anki deck (`.apkg`), which are read with no model. [format.md](format.md#importing-and-exporting)
says how each is read. Photos and PDFs are imported separately from these.

**From an LLM.** For lecture notes, a web page or anything else you would rather work on in a chat,
give any LLM the prompt in [llm-prompt.md](llm-prompt.md) along with the material, and upload the
`.json` it returns as a data file.

*Where these notes go* is either **A new data file** or **Add to** an existing one.

### Reviewing an import

Nothing reaches the collection until you commit it. The review screen shows every row, with pills
for what needs a look: *check this row* (the reader was unsure), *front is empty*/*back is empty*,
and *already in …*/*same meaning as … in …* when a row repeats something you already have. You can
edit either side, press **✕** to drop a row, use **+ note** to add an explanation, and add *Also
accept* answers (other spellings or meanings that should count as correct when typed). **Show
photos** puts the source beside the rows.

**Add N to …** commits. **Save draft** keeps it for later and **Discard import** throws it away.

## Looking after the collection

**A category's ⋯** renames it, gives it labels in other languages, moves it (*inside*), and sets how
its cards may be asked (*practice modes*) and where multiple-choice options are taken from (*options
come from*). Settings made here pass down to the categories inside, unless one sets its own. **New
data file** starts an empty lesson to type into. A category can only be deleted once it is empty.

**A data file** opens as a sheet to read. **Edit** turns it into a grid:

- Tab moves across, Enter adds a row, and rows save as you leave them.
- *priority* on each row: **−1** low (asked last), **0** normal, **+1** high (asked first, and
  twice), **+2** crucial (ahead of high, and still first once mastered). The boost fades as you come
  to know a word, so you never have to go back and unmark it.
- **⋯** on a row opens the rest: whether it is asked both ways, *also accept* answers, a note that
  is shown with the answer, *suspended* (kept, but left out of practice), and *Words beside this
  one*: words with the same or a similar meaning, or under the same heading.
- **✕** archives a row, and *archived notes* at the bottom brings it back. The file has **Archive
  file**, **Download JSON**, its title, its languages, which way its cards go, and *in* (moving it to
  another category).

Text supports Markdown and maths (`$…$`).

**Never fix a lesson by editing its JSON and uploading it again.** That makes a second copy with no
history. Edit in the grid. For a batch of changes, use `memo patch` on the server
(see [format.md](format.md#importing-and-exporting)).

### Worth a look

When the collection has a problem that makes a card unanswerable, a **Worth a look** card appears on
Collection:

- *The same word twice*: two notes for one word split its history, so keep one (archive or suspend
  the other).
- *Two words, one meaning*: asked for that meaning, either word is right, but only one is
  accepted. Either make each back say how the words differ (`this + 이 (subject)`), or let each
  accept the other.
- *Accepted one way only*: finish the pair.

Every finding links straight to the row.

### Finding a word

The search box on Collection searches both sides, accepted answers, notes, headings and lesson
titles, including words you set aside. Each result links to its row in its lesson.

## Practising

**Practise** next to *Collection* takes from everything. **Practise** on a category row, **Practise
this file** on a sheet, and **Practise** on a heading take from just that. Any lesson can be
practised at any time. If nothing in it is due, the soonest cards are brought forward, and answering
them early costs them nothing.

Before starting, these can be set:

| | |
|---|---|
| **How it runs** | **Practice** asks a missed card again until you get it; **Drill** is one pass, keep moving |
| **Which way** | both ways, front → back, or back → front |
| **How to answer** | *Let the card decide* (it moves from picking the answer to writing it as you learn it), or one mode for the whole sitting |
| **How much** | *Short* (20), *Normal* (40), *Long* (80) or *Everything*, each with an estimate from your own pace |
| **New cards** | a ceiling on how many unseen cards come in; empty means no ceiling |
| **Options from** | where multiple-choice options are drawn from |
| **Read questions aloud** | says each question as it comes up, for hearing how it sounds; offered where the device has a voice for the question's language |

The ways of being asked:

- **Pick the answer**: one of four.
- **Match pairs**: pair up a handful.
- **Type the answer**: differences are shown. If what you wrote is also right, **That's the same
  thing** accepts it from now on. **That's a typo** and **I didn't know it** correct the verdict.
- **Build from pieces**: tap the pieces in order.
- **Flip and judge yourself**: **Show answer**, then *Again*, *Hard*, *Good* or *Easy*.

**Not this session** puts a card away until next time. **End** stops at any point. The note and
extra fields are shown with the answer. A speaker reads a card aloud where the device has a voice
for its language; tap it to hear the question (or, after answering, the answer) again.

**The keyboard does everything.** `Enter` always continues. Arrows move between options and `1`–`4`
pick them. In a flip, `Space` reveals and `Enter` is *Good*.

### Before a test: lists

**Manage lists** (on Collection) → **New list**: give it a name and, optionally, a date for
*Leading sittings until*. To fill it, use **Add words** and then search and tap **+ list** on words,
or open a lesson and add a whole heading or file in one tap. Press **Done adding** when finished.

Until the date, the list's words lead every sitting (they take up to half of it), and the rest of the
collection keeps going. **Drill these N** practises every word on the list, due or not. After the
date the list stops leading by itself but is kept, so it can be drilled again. **Stop leading** ends
it early.

Use a list for anything with a date. Priority marks are for what matters permanently.

## Progress

**Progress** counts **words**, not cards. A word is placed by its weaker direction.

- **Not met yet** has never been asked.
- **Learning** has been asked but not yet answered well enough.
- **Known** has been answered right often enough.
- **Mastered** has been answered right often, including written from memory, over at least eight
  hours.

The counts come only from your answers. A word you start getting wrong drops back by itself. The
**?** on the page has the exact rule.

From there:

- Each category opens into its lessons, and a lesson opens into its headings and words.
- **Troublesome** lists what you have missed in the last 30 days, with **Set aside** for a word you
  want out of the way. **Set aside** lists those words and has **Bring back**.
- **When you practised** shows the calendar.

## On the phone

Opened over HTTPS (see [serving.md](serving.md)), the app installs to the home screen and works
with no signal. Cards are kept on the device whenever it is opened with the laptop reachable, and
answers are sent back when it is reachable again. **Settings → Cards on this device** shows what is
kept, and **Take more now** fetches more. **Answers on this device** shows what is waiting, with
**Send now**, and **Save to a file** for when the laptop is never reachable. That file is taken in
with `memo import-answers <file>`.

## Settings

The look, all kept per device so the phone and the laptop can differ:

- **Skin**: *Paper* or *Ink*
- **Theme**: *Auto*, *Light* or *Dark*
- **Size**: *Compact*, *Default*, *Large* or *Larger*

The **Scheduler** (FSRS or SM-2) applies to the whole collection; switching changes the intervals,
not what you know. **Sign out** appears when a password is set.

## Keeping your data

Every review lives in one file, `backend/var/memo.db`. There is no other copy. Back it up:

```sh
cd backend && uv run memo backup --to ~/backups/memo --keep 14
```

**Export** on Collection (or `memo export-tree`) writes the collection out as readable JSON under
`data/`. That is a copy of the notes, not of your progress.
