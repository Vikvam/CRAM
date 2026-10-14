# memo — frontend

SvelteKit, built to static files and served by the backend (PLAN 5). Types come from the
backend's OpenAPI document, so run `uv run memo openapi` in `../backend` and then
`npm run types` whenever an API shape changes.

Start at the [root README](../README.md). What each screen does for the person using it is in
[`../docs/user-guide.md`](../docs/user-guide.md); below the layout, each section is one decision and
the reasoning behind it.

**Contents:** [Layout](#layout) · [Looks](#looks) · [How often a word comes up](#how-often-a-word-comes-up) · [How much one sitting is](#how-much-one-sitting-is) · [Progress is about words](#progress-is-about-words) · [Finding a word](#finding-a-word) · [A list for a test](#a-list-for-a-test) · [When a row is already somewhere else](#when-a-row-is-already-somewhere-else) · [Copying and hearing](#copying-and-hearing) · [Keyboard](#keyboard) · [With no network](#with-no-network)

```sh
npm install
npm run build     # → build/, served by `memo serve`
npm run dev       # hot reload; proxies /api to memo serve on :8000
npm test          # answer-checker spec vectors + unit tests
npm run check     # svelte-check / TypeScript
```

## Layout

```
packages/answer-check/  the one answer checker — spec in ../spec/answer-check.md   PLAN 3.5, 3.7
src/lib/practice/       in-session learning loop, grapheme diff, which mode a card is shown in
src/lib/sheet.ts        a data file read as a page: sections, markers              PLAN 6, phase 4
src/lib/progress.ts     mastery bars, activity grid, streak                        PLAN 6, phase 4
src/lib/theme.svelte.ts skin, light or dark, and the size — all per device       PLAN 6, phase 4
src/lib/speech.svelte.ts  saying a card aloud in the device's own voice — on a tap, or each question
src/lib/selection.ts    whether a click was really someone copying the text
src/lib/keys.ts         whether a key press was the page's or belongs to a text box
src/lib/roving.ts       where the arrow keys move the focus next
src/lib/offline/        db.ts IndexedDB · outbox.ts the rules · batch.ts cards taken along ·
                        collection.ts the tree this device last saw · pack.ts fetching a batch ·
                        sync.svelte.ts the one owner of the outbox                 PLAN 5
src/service-worker.ts   caches the app so it opens with no network; never caches /api/
src/lib/api/            typed client; schema.d.ts is generated
src/routes/             collection · upload · imports/[id] review · practice · files · progress · lists · settings
                        files/[id] is both faces of a lesson: the sheet to read, the grid to edit
```

## Looks

`src/app.css` is the token layer and the only place a value is invented. Structure — the 4px
space scale, the type scale, targets, timings, layers, the page frame — is shared and never
varies. What a **skin** changes is colour, type and edge:

| | |
|---|---|
| `paper` | cream ground, Noto Serif for what you read, hairline rules, light weights, one indigo |
| `ink`   | flat ground, one heavy sans, 2px rules, 800 weights, a cobalt used generously |

Both are chosen in Settings, alongside light/dark and the **size**, and all three are stored per
device. `app.html` resolves `data-skin`, `data-theme` and the size before the first paint, so
nothing flashes; the colours in `app.html`, `src/lib/theme.svelte.ts` and
`static/manifest.webmanifest` must be kept in step, and so must the percentages.

The size is four named steps — compact 90% · default 100% · large 115% · larger 130% — and it moves
the **root font size**, not `--type-scale`. Spacing is all in rem, but rem is anchored to the root,
which `--type-scale` does not touch, so scaling only the text would grow the words inside padding
that stayed put. It is set as a *percentage* so the device's own accessibility text size still
multiplies in rather than being overridden. `--tap`, `--tap-sm` and `--nav-h` are in rem for the
same reason, with `max()` floors so nothing is ever harder to hit than 44px at Compact.

The whole type scale hangs off one multiplier, `--type-scale`, so a screen wider than full HD
(> 1920 CSS px, which includes this laptop's 4608×2880 panel at 200%) gets every size an eighth
larger in proportion. Only the type: the space scale and the 820px column stay put, so a line holds
fewer words rather than running longer. The sizes are `rem`, so **never set a font-size on `html`** —
that redefines `rem` and the scale applies twice. `body` carries it instead.

**Neither skin has cards.** `.card` is kept as the class every screen already uses, but it draws a
rule above the section and nothing else — a section is a rule, a small uppercase label and air.
Anything genuinely raised off the page uses `.panel`.

Also global, because they appear on more than one screen: `.label` (the small tracked eyebrow),
`.figure` (a numeral meant to be read at a distance), `.pill`, `.choice`, `.segmented`, `a.back`,
`.skeleton`, `.stack` / `.row` / `.spread` (each with a `.tight` variant), and `dialog`.

Two bugs of the same shape have already been caused by a component class that is also a global
utility — the component wins only on the properties it sets, and every other global property still
lands on it. `Sheet.svelte`'s gloss column `.back` collided with the back-link (fixed by scoping
that rule to `a.back`), and `TreeNode.svelte`'s `.label` collided with the eyebrow (fixed by
renaming it `.named`). **Before adding a global class, check no component already styles that
name.**

The app no longer explains itself on every screen: 521 words of standing explanation became ~175
on screen, with the rules that are genuinely load-bearing behind `src/lib/components/Help.svelte`
— a native `<details>` rendered as a small `?` beside the heading it belongs to.

## How often a word comes up

Each row of the grid editor carries a segmented **−1 · 0 · +1 · +2** under its own `priority` column
— low, normal, high, crucial — and only one is on. It is a `radiogroup` of `sr-only` radios behind drawn marks, the same shape
Settings uses for skin and theme, and it writes through the row's existing `patchDetail`, which saves
a never-saved row first so a brand-new row can be marked. The marks are drawn in CSS for the reason
the sheet's progress dot is: ▁▄█ is not in every font. Each step keeps the full `--tap-sm` height, so
it is exactly as easy to hit as the `⋯` and `✕` beside it, and only its *width* is below that floor —
three 44px targets would cost 8rem of a four-column grid. The same ticks appear read-only in the
sheet next to the progress dot, because looking a lesson over before a test is the moment you want to
see what you marked.

What a mark is worth is the server's business (it depends on how well the card is already known), so
a card arrives carrying `priority` — the mark *as it stands* — and `twice`. The page badges `high`
and `crucial`,
and `Session` is handed `{ twice }` as a predicate: a marked card is done only after two clean
answers, so it comes back once at the confirmation gap instead of leaving on the first. That is the
only thing that asks for a card again when nothing has gone wrong. The server's order arrives intact
because the session never sorts, only requeues — with one known exception: a `match` round pulls up
to five same-group cards out of the middle and ignores the mark. It can only take cards still being
recognised, so a marked word that is already known is no longer among them.

## How much one sitting is

*"Sometimes I wish to just press Practice but I do not want to do all 190 cards."* The start screen now
asks **How much** before **New cards**: four named steps, remembered per device the way the skin and
the text size are, and `normal` (40) rather than everything is what Start means by default. The step
sends `limit` with the queue, so the sizing happens where the queue is built; the progress bar's
denominator is the sitting, which is the whole felt difference — it reaches the end now.

Each step says how long it will take, from `seconds_per_card`, which the server measures from your own
answers. *Everything* deliberately carries neither a count nor an estimate: both would be the size of
the pile, and the screen does not tell you that — the counts came out of the UI in phase 3 and the
request here was for a shorter session, not for a number to feel behind on. The wording is **"up to"**
for the same reason, so a lesson of twelve cards just ends sooner instead of the label leaking that
there are twelve.

Offline the same rule has to be applied here, in `offline/batch.ts:sized`: the batch kept on the device
is several sittings' worth on purpose, and there is nobody to ask. It mirrors the server's quarter-share
for new cards, stated in both places the way the mode rules are.

One thing it fixed on the way: a `match` round used to claim any card, including words long since
learned, and a matched answer can never push a card past a one-day interval. So they came back daily
for ever — 72 of the 98 cards never once answered wrong. `matchRound` now takes only cards whose own
`suggest` is still a recognition mode.

## Progress is about words

The page used to be four numbers, a heatmap and two links, and the heatmap was twenty-six columns
wide for a fortnight of answers. It now carries three strips of **real words** — *Know well*,
*Troublesome*, *Not met yet*, plus *Set aside* when there are any — each a glimpse of a list that is
one tap away (`/progress/words/[bucket]`, one page for all of them). The scheduler's name is gone
from it: which algorithm is running is not something the person practising has any use for.

A row is one word: what is asked, then what answers it, then where it came from. **Which way round
the card is, is which side leads** — `옆 next to` is the Korean being asked, `next to 옆` is the
English — so no row carries the word "reverse", and none carries a count. *Going wrong* was six
lines a row and is now two, with a **Set aside** button, which is the first thing that list could
ever *do* about a word that keeps failing.

`spanWeeks` (`lib/progress.ts`) narrows the heatmap to the history it has, never below eight weeks.
`heatmap()` already took the width as an option; nothing else changed.

## Finding a word

A search box at the top of Collection, and while there is a query in it the results **stand in for
the tree** — two lists of the same collection on one screen would be a puzzle about which one you are
looking at. The query lives in the URL (`?q=`, by `replaceState` so a keystroke is not a navigation),
so back and forward work and a result can be sent to yourself. Each search is numbered, because a
slow answer must not overwrite a newer one.

A row is the same shape as a Progress row — what is asked, then what answers it, then where it came
from, no counts — with one difference: a result is the **word**, not one direction of it, so the
Korean always leads and the two standings are shown instead. `weakest()` takes the worse of them,
because a word you can read but cannot write is not a word you know and the row should mark the hole.

The lesson link carries `?note=`, and the file page scrolls that row into view and lets a wash fade
off it. Every link into a lesson used to arrive at the top of a fifty-six-row grid, so acting on a
search result — or on something the audit found — meant reading the sheet by eye to find the word
again. The audit card, the Progress word lists and the weak list all point at the note now.

## A list for a test

`/lists` makes one and gives it a date; `/lists/{id}` shows its words, drills them, or stops the
focus. A list also appears on Collection, focused ones first.

**Filling it is the interesting part, because this app has no multi-select and did not want one.**
Turn a list on from its own page and `collecting` remembers it in `localStorage`; until you turn it
off, every search result and every sheet heading grows a `+`. One tap per word after one search,
against twenty clicks across three lessons found by memory. A heading or a whole lesson goes on in
*one* tap, which is the structural bulk gesture — a heading is already a set you think in, because it
is how the page prints them and practice can take one on its own.

It survives navigation because filling a list *is* navigation: you search, you open a lesson, you go
back and search again. Storage is wrapped, since a private window can refuse it; collecting then
lasts as long as the page does, which is most of the way there.

During practice a pushed card shows the **list's name** rather than a priority chip, because a list
is not a property of the word — and the name is the more useful thing to read. `/practice/all?list=`
is the drill, and it says in a line that answering a word you already know keeps the interval it
earned, which is true of any card answered well ahead of its date.

## When a row is already somewhere else

Typing a row checks it against the whole tree as you go (`recheck`, non-blocking, *Keep both* dismisses it), and the
banner now has three things to say rather than two. A match on the **front** is the same prompt — *Already in* when
the back agrees, *Same prompt, different meaning in* when it does not. A match on the **back** is new: *Same meaning
as 그것 in …*, because a note's back is the answer one way round and the *prompt* the other, so two words sharing one
gloss is a question with two right answers. It is the flag that would have caught 그것/그게/그건 at import, which is why
the same case appears as a pill in the import review. It is not shown when the existing note already accepts the
front being typed, since the two are then deliberate alternatives — 뭐 and 무엇 share "what" on purpose.

## Copying and hearing

Study text has to be copyable, including the text inside a tap target — `choice` options, `match`
tiles and `build` pieces are `<button>`s, and a button's text cannot be selected unless the style
asks for `user-select: text`. It is asked for, the numeral and the ✓/✕ ask for `none` so a paste is
clean, and because a drag that selects **still fires `click`**, every one of those taps goes through
`selecting()` first — without it, copying an option would answer the card.

`Speak.svelte` is one tap and the device's own voice (Web Speech API; nothing is downloaded or
generated on the server). It draws nothing unless `speech.can(lang)`, so a machine with no voices —
this laptop, until something provides `libspeechd.so.2` — simply has no button rather than a dead
one. Only a language memo is not written in gets a speaker, since the phone has an English voice
too. Nothing speaks on its own, unless a sitting was started with *Read questions aloud*, which
says each question as `ask()` puts it up. The pitfalls are commented in `speech.svelte.ts`: the voice
list arrives late and more than once, `cancel()` then `speak()` in one tick drops the utterance,
`speaking` gets stuck true, and a collected utterance goes silent.

## Keyboard

A whole session can be answered without the mouse, and `Enter` always means "on you go".

| | |
|---|---|
| any verdict | `Enter` continues |
| `choice` | arrows move the focus, `Enter` picks, `1`–`4` still pick directly |
| `typed` | type, `Enter` checks, `Enter` continues |
| `flip` | `Space` reveals, `1`–`4` grade, **`Enter` is Good** |
| `build` | arrows walk the pool, `Enter` places, `Backspace` undoes; the last piece hands over to Check |
| `match` | ↑↓ walk a column, ←→ cross between them, `Enter` picks the tile under the cursor |

Two rules make that safe. Every handler goes through `forPage()` (`keys.ts`) first, so a bare key
typed into the answer box is text and not a shortcut — a **readonly** box is deliberately *not*
excluded, because the answer field keeps the focus while the verdict is up. And the arrows move the
**real focus** rather than painting a highlight (`roving.ts`), so the one `:focus-visible` ring, the
hover styles and every screen reader come along for nothing. Answering disables the options, which
drops the focus on the floor, so a verdict hands it to Continue and a revealed flip hands it to
Good: the key you are about to press is the one wearing the ring.

Navigation is a **sticky header at every width** — full-width and opaque, with the centred row
inside it, and at ≤640px the `memo` brand gives way so the three links can spread across the
screen at `--tap` tall. It was a fixed bar at the bottom under 641px for a day, until the first
real phone session: Chrome's own chrome occupies that strip, and no safe-area inset helps with
being underneath the browser rather than the page. A running session hides the header —
`src/lib/chrome.svelte.ts` is how the session says so, which is why setting one up and
finishing one keep their navigation. Asking before something is taken away goes through
`src/lib/confirm.svelte.ts` and the one `<Confirm />` in the layout, never `window.confirm`.

## With no network

A session needs nothing but this device. The service worker caches the app itself, so it opens
with no signal at all; a batch of cards sits in IndexedDB, put there by every queue that is
fetched and topped up — deliberately bigger than one session — **whenever the app is opened** with
the laptop reachable, if what is kept is missing, too small to last or a day old. Nobody has to
have thought about it in advance, which is why the **Take cards with me** button it replaced is
gone; *Settings → Cards on this device* is there to check before leaving.

**The collection is kept as well, and that is not a nicety.** Every route into a session is a link
in the category tree; the tree comes from `/api/`, which the worker never caches. Without it the
app opened on "Can't reach the laptop" with no practice link anywhere and a full batch on the
device — found on a real phone, because the browser harnesses reached `/practice/all` by URL, which
a phone cannot do. `collection.ts` keeps the last tree and the last file list per category, so the
home screen behaves normally and only what needs the laptop is disabled.

**Nothing waits for a machine that is asleep.** An asleep laptop swallows packets instead of
refusing them, so an unbounded `fetch` waits out the operating system — minutes — and the app that
had everything it needed on disk looks broken. So the service worker gives the network 1.5s before
answering from the cache, `client.ts` gives a read 2.5s (long jobs are exempt) and then short-circuits
for ten seconds rather than paying the wait once per request, and the sign-in gate and the collection
both render from what this device already knows before the network is asked. Being properly offline
fails in milliseconds and always did, which is why this only showed up on a real phone.

A mark survives being away for nothing, because the batch is the whole `Queue` stored verbatim — but
a mark *set* while the laptop is unreachable never reaches a batch already on the device, and the
editor is online-only anyway.

Anything written to IndexedDB from Svelte state must be made plain first: state is a `Proxy`, and
structured clone throws `DataCloneError` on one — which `db.ts` turns into a silent `null`, so the
symptom is an empty store and no error anywhere. An incidental save never replaces a
batch put aside on purpose, or opening the page at home would quietly undo packing for the train.
Offline with no batch for the exact scope, the widest one there is covers more than this scope
rather than less, and the screen says the cards came from wider than here.

Every answer goes to the outbox first — online or not. One path, so the offline one is not a
special case that runs for the first time when it is too late to notice it is broken; it also
takes a round-trip out from between two cards. Each answer gets a ULID and the moment it was
answered, and `sync.svelte.ts` hands them over whenever the laptop is reachable, with
**Settings → Answers on this device → Save to a file** for when it never is. Neither way can
double-count: the id is unique per profile on the server.

Two consequences worth knowing. A batch is a photograph, so after a long stretch away the mode a
card suggests is behind what it now deserves — the grading and the replay are unaffected. And
being out of range must not look like being signed out: `auth.svelte.ts` remembers the last good
status, because `/auth/status` answers 200 either way and only a real 401 means anything.

None of this runs over plain `http://` on the LAN: a service worker is refused outside a secure
context. See [`../docs/serving.md`](../docs/serving.md).

It also **installs**: `static/manifest.webmanifest` is `display: standalone` with 192/512 PNG icons,
a maskable 512 drawn inside its own safe zone, and a 180px `apple-touch-icon` — iOS reads none of
the manifest's icons and would otherwise synthesise a screenshot. All of them come from
`static/icon.svg` via `rsvg-convert`, so there is one source to change. Installed, the app has no
browser chrome of its own, which is the other half of why navigation sits at the top.
