# Making cards with an LLM

memo reads photos and PDFs itself (**Add pages**), and it does so with the prompt below, word for
word. For anything else, such as lecture notes, a web page or a list you typed, or when you would
rather talk it over with the model, you can have any LLM write the cards. Give it the same prompt and your material, and it
returns a data file that memo imports as it is.

1. Copy everything inside the block below into a new chat with the LLM of your choice.
2. Attach or paste your material.
3. Under the last line, `--- My instructions ---`, write what you want, if anything: which way the
   cards should be asked, how many, what to leave out, how to split the material into files. You
   can leave it empty.
4. The reply is one or more ```json blocks. Save each block as its own file ending in `.json`
   (e.g. `ohms-law.json`).
5. In memo, press **Add pages** on the category the cards belong in, then **Choose data files**
   and pick the file. Choose whether it becomes *A new data file* or is added to an existing one,
   press **Import**, look the draft over and press **Add N to …**. Nothing reaches the collection
   before you have looked at it. Files picked together become one draft, so pick one at a time if
   you want them as separate lessons.

Things worth knowing:

- **Uploading always makes new notes.** Uploading a corrected version of a file you already
  committed gives you a second copy with no history, not an update. Fix committed cards in the grid
  editor, or in bulk with `memo patch` (see [`../backend/README.md`](../backend/README.md), *A gloss
  read backwards*).
- The LLM can only be as right as your material. Read the draft before committing, especially rows
  marked *check this row*.
- After committing, the Collection page shows a **Worth a look** card if the new words clash with
  ones you already have (two words with the same meaning, for example). See
  [user-guide.md](user-guide.md#worth-a-look).
- [format.md](format.md) is the full reference for the format. The prompt contains everything the
  LLM needs, so you do not have to give it that file.
- When memo reads a photo, it fills in `--- My instructions ---` itself: which photo it is, its printed
  page if you gave one, the category and its languages, then whatever you typed in *Anything the reader
  should know*. The copy the app sends is `backend/src/memo/importers/prompts/general.md`; a test keeps
  it identical to the block below, so change both or neither.

## The prompt

````text
You are turning study material into flashcard data for a spaced-repetition app. The material is
attached or pasted below; my own instructions, if any, come after the line "--- My instructions ---"
at the very end, and they override every default here.

# What to produce

Reply with one or more JSON objects in the format described below, each in its own ```json code
block, and nothing else: no introduction, no summary, no comments inside the JSON. Make one object
per natural unit of the material (a chapter, lesson, page or section), or a single object if the
material is short or I ask for one. Every object must be complete, valid JSON on its own.

# How the app uses the data

Each item is a *note* with a `front` and a `back`.

- A `directional` note is asked one way: the app shows the front, I answer with the back.
- A `bidirectional` note is asked both ways: front → back, and separately back → front. So in a
  bidirectional file the **back is also a question**, and it must point to exactly one front. If two
  notes in a file would share the same back, that reverse question has two right answers and cannot
  be answered. Fix it with one of the two methods under "Writing good notes".
- I answer either by typing (checked against the text), by picking from options (the app takes the
  wrong options from other notes in the same group and file), by matching pairs, by assembling the
  answer from shuffled pieces, or by revealing the answer and grading myself. So an answer should be
  short, exact and typeable, and the notes in a group should be the same kind of thing, so that they
  make believable wrong options for each other.
- After an answer, the app shows the note's `note` and `fields` as extra information.

Use bidirectional for things learned in both directions, such as vocabulary and term ↔ definition
pairs where both sides are short. Use directional for questions and answers, facts, problems,
formulas, and anything whose back is too long to work as a question.

# The format

Top level of each object:

| key            | required | meaning |
|----------------|----------|---------|
| `format`       | yes | always the string `"memo.datafile"` |
| `version`      | yes | always the number `1` |
| `title`        | yes | one plain line naming this unit, e.g. `"3 · Electric circuits — Ohm's law"`. Use the title printed closest above the notes (the section heading, if there is one), after the number of the unit it belongs to. Every level above it (book, chapter, lesson) goes in `source.context`. If the title is printed in two languages, use both, original first, joined with ` · ` |
| `default_type` | yes | `"bidirectional"` or `"directional"`, applies to every note that does not set its own `type` |
| `front_lang`   | yes | language of the front side, as a BCP-47 code (`en`, `de`, `ja`, `pt-BR`…). Used for the voice and fonts. Set it to the language the text is written in even when the content is not about language |
| `back_lang`    | yes | the same for the back side |
| `source`       | no  | where it came from: `{"kind": "pdf" \| "image" \| "text" \| "manual", "files": ["chapter3.pdf"], "page": 12, "context": {…}}`. `kind` is `text` for pasted text, and `files` holds bare file names (leave it out when nothing was attached). `context` is free-form, e.g. `{"chapter": {"number": "3", "title": "Electric circuits"}}` |
| `groups`       | no  | the headings the notes sit under: `[{"id": "short-key", "label": {"en": "Heading text"}}]`. `id` is a short lowercase key you make up, unique in the file. `label` maps a language code to the heading as printed; give every language the heading is printed in. A group can carry a `note` of its own (an explanation that applies to the whole section) |
| `notes`        | yes | the list of notes |

Each note:

| key      | required | meaning |
|----------|----------|---------|
| `front`  | yes | the prompt side |
| `back`   | yes | the answer side |
| `group`  | no  | the `id` of one of the file's `groups` |
| `type`   | no  | `"bidirectional"` or `"directional"`, only when this note differs from `default_type` |
| `accept` | no  | other answers that also count as correct when typed: `{"front": [...], "back": [...]}`. `accept.back` is checked when the back is the answer, `accept.front` when the front is. They are never shown as a question, so they cannot make one ambiguous. Nothing is ever split or guessed automatically, so list every alternative that should count; see rule 7 for what belongs here |
| `note`   | no  | a short explanation, usage hint or example, shown after answering. Markdown |
| `fields` | no  | extra facts as `{"name": "value"}` pairs, shown after answering (e.g. `{"pronunciation": "…", "plural": "…"}`). Use it for extra columns the material has, never for the answer itself |
| `modes`  | no  | restricts how the note may be asked; see "Modes". Leave it out in most cases |
| `tags`   | no  | a list of short free-text tags, only if the material or I suggest some |
| `page`   | no  | the page of the material this came from |
| `confidence` | no | a number from 0 to 1. Set it below 0.7 only on a note you are unsure about (illegible source, ambiguous meaning) so it gets a second look in review; leave it out otherwise |
| `priority` | no | `"low"`, `"high"` or `"crucial"`, only if I ask for priorities. Leave it out for normal |

Do not include `id`, `status`, `suspended` or `source.import`. The app manages them, and an `id`
you invent would be thrown away.

Text in `front`, `back`, `note` and `fields` may use Markdown (`**bold**`, `*italic*`) and LaTeX
maths between `$…$` (inline) or `$$…$$` (display). Do not use HTML or images. In JSON, a backslash
must be doubled: write `"$\\frac{V}{R}$"`.

# Modes

The ways a note can be asked are `"flip"` (reveal and self-grade), `"typed"`, `"choice"`, `"match"`
and `"build"` (assemble the answer from shuffled pieces). By default the app picks a suitable one
itself and quietly skips any that cannot work (for example, `build` needs an answer of 2–6 words,
or a single word of 2–12 characters). Only set `modes` when a way of asking would be unfair even
though it technically works:

- a long or free-form answer (a sentence of explanation, a list): `["flip", "choice"]`
- a formula or anything with more than one correct way to write it: `["flip", "choice"]`
- a sentence where word order is the point: keep `"build"`, e.g. `["typed", "build", "flip"]`

# Writing good notes

When the material already pairs things (a vocabulary list, a glossary, a table, a list of questions
with answers), **transcribe it**: every pair, character for character (punctuation and dashes
included), without correcting, completing, or translating it. Keep the printed order, reading a table
**row by row, left to right**: when a row holds two or more pairs side by side, take them left to
right before moving down. Turn the material's headings into `groups` as printed, even when a heading
mixes kinds of item. Footnotes and usage remarks go into `note`, without the footnote marker.

When the material is prose, **write questions** that the material itself answers, covering its
main facts, definitions, causes, steps and numbers. Unless I say otherwise, write them in the
material's language, and never add a fact the material does not state. Using the standard name
for something the material describes is fine (the material says water "condenses"; the answer may
be "condensation").

Either way:

1. **One fact per note.** If an answer would be a list of several things, make several notes,
   unless the material itself treats the list as one fact ("the four forms of precipitation"). Then
   keep one note, restrict its `modes` to `["flip", "choice"]`, and do not accept part of the list.
2. **The front must stand alone.** It is shown with no material beside it, so give enough context
   to make it unambiguous ("In the Calvin cycle, what does RuBisCO fix?" rather than "What does it
   fix?"). Never write "according to the text".
3. **The back is short.** Aim for a word, a term, a number with its unit, or a short phrase. Put
   the explanation in `note`.
4. **Avoid yes/no and true/false questions.** Ask for the thing itself.
5. **Several meanings, one note.** Keep the back as printed (`"to go, to drive"`) and list each
   meaning that should count on its own in `accept.back` (`["to go", "to drive"]`).
6. **Two notes that would share a back** in a bidirectional file must be told apart, in one of two
   ways:
   - If they really are different, make each back say how: `"to go (on foot)"` and
     `"to go (by vehicle)"`. Then put the bare meaning (`"to go"`) in `accept.back` of both, so
     answering front → back does not get harder.
   - If they really are interchangeable (true synonyms), keep the shared back and list each
     note's front in the other's `accept.front`, so either answer counts both ways.
7. **`accept` holds the same answer written differently**: with or without an article, singular
   or plural, a variant spelling, an abbreviation or symbol, a number with or without its unit, and
   each separate meaning of a multi-meaning back (rule 5). It never holds a part of the answer
   ("rivers" for "rivers and lakes"), a vaguer answer, or a paraphrase the material does not
   support. An accepted meaning may equal another note's back ("what" accepted for "what,
   which" while another note means just "what"): `accept` is never asked, so it cannot clash. Spellings of a front go in `accept.front`, those of a back in `accept.back`.
8. **Groups.** When transcribing, use the material's own headings. When writing questions, group
   by topic, and put answers of the same kind together where you can (all terms, all numbers), at
   least three to a group: the wrong options in multiple choice come from the same group, and a
   group of mixed kinds lets their form give the answer away. One group, or none, is fine for short
   material.
9. **Mark doubt, do not hide it.** If you cannot read an item, or the material is ambiguous, still
   include the note with your best reading and a `confidence` below 0.7. If one side is entirely
   missing, set it to `null`: the app keeps the note and flags it for me to complete.

# Example 1: a two-language vocabulary list (bidirectional)

```json
{
  "format": "memo.datafile",
  "version": 1,
  "title": "Lektion 4 · Unterwegs · On the move",
  "default_type": "bidirectional",
  "front_lang": "de",
  "back_lang": "en",
  "source": {
    "kind": "pdf",
    "files": ["deutsch-a1-kapitel-4.pdf"],
    "page": 52,
    "context": { "lesson": { "number": "4", "de": "Unterwegs", "en": "On the move" } }
  },
  "groups": [
    { "id": "verbs", "label": { "de": "Verben", "en": "Verbs" } },
    { "id": "transport", "label": { "de": "Verkehrsmittel", "en": "Transport" } }
  ],
  "notes": [
    {
      "group": "verbs",
      "front": "gehen",
      "back": "to go (on foot), to walk",
      "accept": { "back": ["to go", "to walk", "go", "walk"] },
      "fields": { "past participle": "gegangen" }
    },
    {
      "group": "verbs",
      "front": "fahren",
      "back": "to go (by vehicle), to drive",
      "accept": { "back": ["to go", "to drive", "go", "drive"] },
      "note": "Also *to ride*, for a bike or a train.",
      "fields": { "past participle": "gefahren" }
    },
    {
      "group": "verbs",
      "front": "ankommen",
      "back": "to arrive",
      "accept": { "back": ["arrive"] },
      "note": "Separable: *Der Zug **kommt** um acht **an**.*"
    },
    {
      "group": "transport",
      "front": "der Zug",
      "back": "train",
      "accept": { "front": ["Zug"], "back": ["the train"] },
      "fields": { "plural": "die Züge" }
    },
    {
      "group": "transport",
      "front": "das Fahrrad",
      "back": "bicycle",
      "accept": { "front": ["Fahrrad", "das Rad", "Rad"], "back": ["bike", "the bicycle"] },
      "fields": { "plural": "die Fahrräder" }
    },
    {
      "group": "transport",
      "front": "die U-Bahn",
      "back": "underground, subway",
      "accept": { "front": ["U-Bahn"], "back": ["underground", "subway", "metro"] }
    }
  ]
}
```

# Example 2: questions written from a page of prose (directional)

```json
{
  "format": "memo.datafile",
  "version": 1,
  "title": "3 · Electric circuits — Ohm's law",
  "default_type": "directional",
  "front_lang": "en",
  "back_lang": "en",
  "source": {
    "kind": "text",
    "files": ["physics-notes-ch3.md"],
    "context": { "chapter": { "number": "3", "title": "Electric circuits" } }
  },
  "groups": [
    { "id": "ohm", "label": { "en": "Ohm's law" } },
    { "id": "units", "label": { "en": "Units" } }
  ],
  "notes": [
    {
      "group": "ohm",
      "front": "State Ohm's law as a formula for voltage.",
      "back": "$V = IR$",
      "modes": ["flip", "choice"],
      "note": "Voltage $V$ in volts, current $I$ in amperes, resistance $R$ in ohms."
    },
    {
      "group": "ohm",
      "front": "By Ohm's law, what current flows through a 10 Ω resistor with 5 V across it?",
      "back": "0.5 A",
      "accept": { "back": ["0.5", "0.5A", "500 mA", "1/2 A"] },
      "note": "$I = \\frac{V}{R} = \\frac{5}{10}$"
    },
    {
      "group": "ohm",
      "front": "In Ohm's law, how does the current change when the resistance doubles at a fixed voltage?",
      "back": "it halves",
      "accept": { "back": ["halves", "half", "it is halved"] }
    },
    {
      "group": "units",
      "front": "What is the SI unit of electrical resistance?",
      "back": "ohm",
      "accept": { "back": ["the ohm", "Ω", "ohms"] },
      "fields": { "symbol": "Ω" }
    },
    {
      "group": "units",
      "front": "What is the SI unit of electric current?",
      "back": "ampere",
      "accept": { "back": ["amp", "amps", "amperes", "A"] },
      "fields": { "symbol": "A" }
    },
    {
      "group": "units",
      "front": "What is the SI unit of electric potential difference?",
      "back": "volt",
      "accept": { "back": ["volts", "V"] },
      "fields": { "symbol": "V" }
    }
  ]
}
```

# Before you answer, check

- Each object is valid JSON: double quotes, no trailing commas, no comments, backslashes doubled.
- `format`, `version`, `title`, `default_type`, `front_lang`, `back_lang` and `notes` are present.
- Every `group` a note names is defined in that file's `groups`.
- No `id`, `status` or `suspended` anywhere.
- In a bidirectional file, no two notes have the same `back` unless each accepts the other's front.
- Nothing is invented: every note is printed in, or stated by, the material.
- If transcribing, every pair in the material is there, in order (rows left to right, then down).
- Your reply contains only the ```json blocks.

--- My instructions ---
````
