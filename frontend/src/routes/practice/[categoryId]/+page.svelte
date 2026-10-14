<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';
	import { page } from '$app/state';
	import { check, type CheckResult, type Outcome } from '@memo/answer-check';
	import { api, type Category, type QueueCard } from '$lib/api/client';
	import { immersion } from '$lib/chrome.svelte';
	import { forPage } from '$lib/keys';
	import { plain as plainText, renderInline, render } from '$lib/markdown';
	import { foreign, speech } from '$lib/speech.svelte';
	import { sync as outbox } from '$lib/offline/sync.svelte';
	import { remaining, save, saved, scopeOf, sized, widest } from '$lib/offline/batch';
	import { pack } from '$lib/offline/pack';
	import { diff } from '$lib/practice/diff';
	import { DRILL, Session, type Item } from '$lib/practice/session';
	import {
		FORCEABLE,
		LABELS,
		MATCH_MINIMUM,
		matchRound,
		modeFor,
		type Answering
	} from '$lib/practice/modes';
	import Choice from '$lib/components/practice/Choice.svelte';
	import Build from '$lib/components/practice/Build.svelte';
	import Match from '$lib/components/practice/Match.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import Help from '$lib/components/Help.svelte';
	import Speak from '$lib/components/Speak.svelte';
	import { labelBoth, labelText } from '$lib/tree';

	type Phase = 'setup' | 'asking' | 'judged' | 'matching' | 'done';

	/** What the scope holds — the queue alone cannot say why it is the length it is. */
	type Counts = {
		due_count: number;
		new_count: number;
		ahead_count: number;
		total: number;
		next_due: string | null;
	};

	/** The third of the four flip buttons, and what Enter means on a revealed card. */
	const GOOD = 3;

	//: Renamed from `memo.practice.mode`, which could only hold typed or flip —
	//: an old preference would have pinned the session to one of those two.
	const MODE_KEY = 'memo.practice.answering';
	//: v2 because the old key holds a 20 that used to be the default, and a cap
	//: nobody chose should not survive the decision to stop capping (PLAN 3.5).
	const NEW_KEY = 'memo.practice.newLimit.v2';
	const SCOPE_KEY = 'memo.practice.distractors';
	//: Like the size: whether you are covering or learning is a property of what
	//: you sat down to do, so the screen remembers which you last chose.
	const DRILL_KEY = 'memo.practice.drill';
	//: '' = both ways. Remembered beside the rest, and only ever offered where the
	//: scope has two sides to choose between.
	const DIRECTION_KEY = 'memo.practice.direction';
	//: Per device, like the skin and the text size: how much practice this screen
	//: is on is a property of where you are, not of the collection.
	const SIZE_KEY = 'memo.practice.size';
	//: Per device too: whether each question is said aloud as it comes up. Off
	//: unless asked for, because nothing else in the app ever speaks on its own.
	const SPEAK_KEY = 'memo.practice.speak';

	/**
	 * How much one sitting is. Four named steps rather than a number, for the same
	 * reason the text size has four: a number invites you to tune it and then to
	 * wonder whether you tuned it right.
	 *
	 * `null` is everything there is. It carries no count and no estimate on
	 * purpose — both would be the size of the pile, which is the one thing this
	 * screen does not say (PLAN 3.5).
	 */
	const SIZES: { key: string; title: string; cards: number | null }[] = [
		{ key: 'short', title: 'Short', cards: 20 },
		{ key: 'normal', title: 'Normal', cards: 40 },
		{ key: 'long', title: 'Long', cards: 80 },
		{ key: 'all', title: 'Everything', cards: null }
	];

	/** What a card costs before this device has watched you answer any (`pace`). */
	const ASSUMED_SECONDS = 15;

	/** Single answers between one match round and the next, so a session mixes. */
	const MATCH_GAP = 8;

	const param = $derived(page.params.categoryId);
	const categoryId = $derived(param === 'all' ? undefined : param);
	/** Started from a sheet: one data file, or one heading of it (PLAN 6, phase 4). */
	const within = $derived({
		fileId: page.url.searchParams.get('file') ?? undefined,
		group: page.url.searchParams.get('group') ?? undefined
	});
	/**
	 * Drilling one list: every word on it, due or not, because a test next week is
	 * not something the schedule knows about. Not part of `within`, which is the
	 * shape the offline pack is keyed by — a drill is a thing you ask for at the
	 * laptop before a test, not a batch to carry around.
	 */
	const listId = $derived(page.url.searchParams.get('list') ?? undefined);

	let category = $state<Category | null>(null);
	let queue = $state<QueueCard[] | null>(null);
	let scheduler = $state('');
	let allowed = $state<string[]>([]);
	/** What the queue actually used, for the "as this category says" label. */
	let usedScope = $state('auto');
	/** The name of the file a sheet sent us from, for the heading. */
	let fileTitle = $state<string | null>(null);
	/** The name of the list being drilled, for the same reason. */
	let listName = $state<string | null>(null);
	let error = $state<string | null>(null);
	/** Practising cards taken along, because the server could not be reached. */
	let offline = $state(false);
	/** When the batch being practised was fetched, so the page can say how old it is. */
	let takenAt = $state<string | null>(null);
	/** Practising a batch kept for a wider scope, because this one has none. */
	let wider = $state(false);
	/** What the scope holds, so an empty queue can say which kind of empty it is. */
	let counts = $state<Counts | null>(null);
	/**
	 * Which way round this scope can be asked: direction → how many cards exist.
	 *
	 * Counted by the server over the whole scope *before* the direction filter, so
	 * the numbers beside the radio do not move as you change it. Fewer than two
	 * entries means there is no choice here and the control is not shown at all.
	 */
	let ways = $state<Record<string, number>>({});

	let mode = $state<Answering>(readPref(MODE_KEY, 'auto') as Answering);
	/** '' = leave it to the category; anything else overrides it for this session. */
	let scope = $state(readPref(SCOPE_KEY, ''));
	/** '' = all of them. How much to take on in one sitting is the user's call. */
	let newLimit = $state(readPref(NEW_KEY, ''));
	/** Which of `SIZES`. `normal` by default: Start must not mean the whole pile. */
	let size = $state(readPref(SIZE_KEY, 'normal'));
	/**
	 * Drill rather than practise: cover the scope instead of learning what you miss.
	 *
	 * Two halves, and both are needed for it to feel like one thing. The server
	 * sends **everything in scope, due or not** (still capped by the size), and
	 * the client runs the queue by `DRILL` — one correct retires a word, and a
	 * missed one comes back at the end rather than three cards later.
	 *
	 * Not a scheduler, despite being a choice about a sitting: `card_state` is
	 * keyed by scheduler name, so a third name there would give every card a
	 * second, empty history. Same scheduler, same log, same due dates.
	 *
	 * `?drill=1` preselects it, which is all a Drill button anywhere else has to
	 * do; arriving with `?list=` is already one, since a list exists for a test.
	 */
	let drill = $state(
		page.url.searchParams.get('drill') === '1' ||
			page.url.searchParams.get('list') !== null ||
			readPref(DRILL_KEY, '') === '1'
	);
	/**
	 * Ask a two-sided note one way round: '' both, 'fwd' its front, 'rev' its back.
	 *
	 * A note is a question and its answer, and this chooses which of the two you
	 * are shown. It knows nothing about what either side holds — which of them is
	 * worth drilling is the collection's business, not this screen's. A one-way
	 * note has no other side, so it is simply absent from the one it lacks.
	 */
	let direction = $state(readPref(DIRECTION_KEY, ''));
	/** Read each question aloud as it comes up — for learning how it sounds, not only what it means. */
	let aloud = $state(readPref(SPEAK_KEY, '') === '1');
	const sayable = (card: QueueCard) => foreign(card.prompt_lang) && speech.can(card.prompt_lang);
	/** Only offered where some question here can be said on this device at all. */
	const speakable = $derived((queue ?? []).some(sayable));
	/** Seconds a card costs you, measured from your own answers; null until it can be. */
	let secondsPerCard = $state<number | null>(null);

	let session = $state<Session<QueueCard> | null>(null);
	let phase = $state<Phase>('setup');
	let typed = $state('');
	let result = $state<CheckResult | null>(null);
	let revealed = $state(false);
	let shownAt = 0;
	let input = $state<HTMLInputElement | null>(null);
	let sending = $state(false);
	/** Whatever Enter would press: the verdict's Continue, or a flip's Good. */
	let onwards = $state<HTMLButtonElement | null>(null);
	let good = $state<HTMLButtonElement | null>(null);
	let acceptedNow = $state(false);
	/** The cards of a `match` round, off the queue until it is finished. */
	let round = $state<Item<QueueCard>[] | null>(null);
	let sinceMatch = $state(MATCH_GAP);
	let built = $state('');
	let picked = $state<string | null>(null);
	/** What the session is showing now. The `Session` is a plain class, so the
	 *  page mirrors the parts it renders and refreshes them with `sync()` after
	 *  every answer — a counter read for its side effect was quietly dropped in
	 *  the production build, and the progress bar sat at 0 all session. */
	let current = $state<QueueCard | undefined>(undefined);
	let done = $state(0);
	let total = $state(0);

	const cardMode = $derived(current ? modeFor(current, mode, allowed) : 'typed');
	/** Only a scope holding both sides of something has a way round to choose. */
	const sided = $derived(Object.keys(ways).length > 1);
	const bothWays = $derived(Object.values(ways).reduce((a, b) => a + b, 0));
	/** The cap this screen is asking for, or null for everything there is. */
	const cap = $derived(SIZES.find((step) => step.key === size)?.cards ?? null);
	/** What this session covers, in the words of whatever sent us here. */
	const practising = $derived(
		listId
			? (listName ?? 'a list')
			: within.group
			? labelBoth(queue?.[0]?.group ?? null, within.group)
			: within.fileId
				? (fileTitle ?? 'this file')
				: category
					? labelText(category.label, category.path)
					: 'everything'
	);
	/** How the session went, for the screen that ends it. A session is not
	 *  scored, so this counts what happened and nothing else: what was asked,
	 *  what was right at the first attempt, and what is coming back another day. */
	const summary = $derived.by(() => {
		const items = session?.items ?? [];
		const asked = items.filter((i) => i.attempts > 0);
		return {
			asked: asked.length,
			first: asked.filter((i) => i.outcomes[0] === 'correct').length,
			left: items.filter((i) => !i.done).length
		};
	});
	/** What the start screen can offer here — a category may allow fewer. */
	const choosable = $derived<Answering[]>(['auto', ...FORCEABLE.filter((m) => allowed.includes(m))]);

	/**
	 * The session's own item for a card. Anything held in `$state` is a deep
	 * proxy, and writing through one does not reach the object the `Session`
	 * keeps — so an answer has to be recorded against the item the session
	 * itself holds, found by the card's key.
	 */
	function itemOf(key: string): Item<QueueCard> | undefined {
		return session?.items.find((i) => i.card.key === key);
	}

	function sync() {
		current = session?.current?.card;
		done = session?.doneCount ?? 0;
		total = session?.items.length ?? 0;
	}

	function readPref(key: string, fallback: string): string {
		try {
			return localStorage.getItem(key) ?? fallback;
		} catch {
			return fallback;
		}
	}

	function writePref(key: string, value: string) {
		try {
			localStorage.setItem(key, value);
		} catch {
			/* private mode — preferences just aren't remembered */
		}
	}

	async function load() {
		const scopeKey = scopeOf(categoryId, within);
		const ask = (side: string) =>
			api.queue({
				listId,
				categoryId,
				newLimit: newLimit === '' ? undefined : Number(newLimit),
				limit: cap ?? undefined,
				distractorScope: scope || undefined,
				drill,
				direction: side === 'fwd' || side === 'rev' ? side : undefined,
				within
			});
		try {
			let [q, categories] = await Promise.all([ask(direction), api.categories()]);
			// The way round is remembered per device, but only offered where a scope
			// goes both ways. Where it does not, the radio is hidden, so a remembered
			// side must not quietly empty it: a one-way file asked "back → front" has
			// no cards at all, and nothing on screen to say why or to change it.
			const side = direction && Object.values(q.ways ?? {}).filter((n) => n > 0).length < 2 ? '' : direction;
			if (side !== direction) q = await ask(side);
			queue = q.cards;
			scheduler = q.scheduler;
			allowed = q.modes;
			usedScope = q.distractor_scope;
			counts = {
				due_count: q.due_count,
				new_count: q.new_count,
				ahead_count: q.ahead_count,
				total: q.total,
				next_due: q.next_due ?? null
			};
			ways = q.ways ?? {};
			secondsPerCard = q.seconds_per_card ?? null;
			category = categoryId ? (categories.find((c) => c.id === categoryId) ?? null) : null;
			if (within.fileId && categoryId) {
				const files = await api.files(categoryId);
				fileTitle = files.find((f) => f.id === within.fileId)?.title ?? null;
			}
			if (listId) {
				// Only for the heading, so a list that has gone missing must not
				// take the session down with it.
				listName = await api
					.list(listId)
					.then((found) => found.name)
					.catch(() => null);
			}
			error = null;
			offline = false;
			wider = false;
			// Keep it: the next session may be the one with no signal. Never a
			// drill, though — it holds cards that are not due for a fortnight,
			// and the phone would practise those believing they were today's.
			// Nor half a collection: a batch kept while one side was chosen would
			// leave the phone unable to ask the other.
			if (!drill && !listId && !side) void save(scopeKey, q);
			void topUp();
		} catch (e) {
			// Nothing to reach. The last queue fetched is still good enough to
			// practise — minus whatever has been answered since. Failing a batch
			// for this exact scope, the widest one there is covers more than this
			// scope rather than less, which beats a dead end.
			const exact = await saved(scopeKey);
			const kept = exact ?? (await widest());
			if (!kept) {
				error = e instanceof Error ? e.message : String(e);
				return;
			}
			// The batch is bigger than a sitting on purpose, so the size asked for
			// has to be applied here too — there is nobody to ask for it.
			const left = sized(remaining(kept.queue, await outbox.answered()), cap);
			queue = left.cards;
			scheduler = left.scheduler;
			allowed = left.modes;
			usedScope = left.distractor_scope;
			takenAt = kept.at;
			offline = true;
			counts = null;
			// Nothing can be re-asked of a server that is not there, so the choice
			// is not offered over a batch kept on the device.
			ways = {};
			wider = kept !== exact;
			error = left.cards.length ? null : 'Everything taken along has been practised.';
		}
	}

	/**
	 * Quietly keep more than a session's worth on this device.
	 *
	 * The phone can only practise what it has already been handed, and whether
	 * it will have signal later is not something to have to have thought about
	 * in advance. So after every ordinary load, if what is kept is missing, too
	 * small to last, or yesterday's, fetch a bigger one. It is one more GET
	 * against a server on the same desk.
	 */
	async function topUp() {
		await pack(categoryId, within, scope || undefined);
	}

	/** How long ago the batch being practised was fetched, in words. */
	const taken = $derived.by(() => {
		if (!takenAt) return '';
		const hours = (Date.now() - new Date(takenAt).getTime()) / 3_600_000;
		if (hours < 1) return 'just now';
		if (hours < 24) return `${Math.round(hours)}h ago`;
		return `${Math.round(hours / 24)}d ago`;
	});

	/**
	 * How long a sitting of this many cards will take, in words.
	 *
	 * At the pace the server measured from your own answers — both how long one
	 * answer takes and how many answers a card takes, since a missed card is
	 * asked again until it is right twice. Rounded coarsely above ten minutes: it
	 * is an estimate, and a number ending in a 7 would be claiming otherwise.
	 */
	function howLong(cards: number): string {
		const minutes = ((secondsPerCard ?? ASSUMED_SECONDS) * cards) / 60;
		if (minutes < 10) return `about ${Math.max(1, Math.round(minutes))} min`;
		if (minutes < 60) return `about ${Math.round(minutes / 5) * 5} min`;
		return minutes < 90 ? 'over an hour' : `about ${Math.round(minutes / 30) / 2} hours`;
	}

	/** When a card scheduled for later comes round, in words. Local, not UTC. */
	function when(iso: string) {
		const at = new Date(iso);
		const hours = (at.getTime() - Date.now()) / 3_600_000;
		if (hours < 1) return 'any minute';
		if (hours < 12) return at.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
		if (hours < 36) return 'tomorrow';
		if (hours < 24 * 7) return `in ${Math.round(hours / 24)} days`;
		return at.toLocaleDateString(undefined, { day: 'numeric', month: 'long' });
	}

	async function start() {
		writePref(MODE_KEY, mode);
		writePref(NEW_KEY, newLimit);
		writePref(SCOPE_KEY, scope);
		writePref(SIZE_KEY, size);
		writePref(DRILL_KEY, drill ? '1' : '');
		writePref(DIRECTION_KEY, direction);
		writePref(SPEAK_KEY, aloud ? '1' : '');
		await load();
		if (!queue?.length) return;
		session = new Session(queue, {
			...(drill ? DRILL : {}),
			twice: (card) => card.twice
		});
		sinceMatch = MATCH_GAP;
		sync();
		await ask();
	}

	async function ask() {
		speech.stop();
		typed = '';
		result = null;
		revealed = false;
		acceptedNow = false;
		picked = null;
		built = '';
		sync();
		if (session?.finished) {
			phase = 'done';
			return;
		}
		const pairs = nextRound();
		if (pairs) {
			round = pairs;
			phase = 'matching';
			shownAt = performance.now();
			sync(); // the round is off the queue, so the next single card has changed
			return;
		}
		round = null;
		phase = 'asking';
		shownAt = performance.now();
		await tick();
		input?.focus();
		// The same words the speaker button says, so it shows this as playing and a tap stops it.
		if (aloud && current && sayable(current)) speech.speak(plainText(current.prompt), current.prompt_lang);
	}

	/**
	 * A matching round, when the queue has enough fresh cards from one group and
	 * enough single cards have gone by since the last one — recognition is how a
	 * new word starts, not the whole session.
	 */
	function nextRound(): Item<QueueCard>[] | null {
		if (!session || mode !== 'auto' || !allowed.includes('match')) return null;
		if (sinceMatch < MATCH_GAP) return null;
		const wanted = matchRound(session.pending);
		if (wanted.length < MATCH_MINIMUM) return null;
		sinceMatch = 0;
		return session.take(wanted.length, (item) => wanted.includes(item));
	}

	/** One pair of a match round: logged for its own card, like any other answer. */
	async function pairAnswered(card: QueueCard, outcome: Outcome) {
		const item = itemOf(card.key);
		if (!session || !item) return;
		// How long this pair took: since the grid appeared, or since the pair
		// before it was placed. A match pair used to log no duration at all, which
		// left a third of the review log untimed — and the estimate of how long a
		// session will take is read off exactly that (`pace`).
		const at = performance.now();
		const spent = Math.round(at - shownAt);
		shownAt = at;
		await outbox.record({
			card_key: card.key,
			mode: 'match',
			outcome,
			grade: null,
			overridden: false,
			raw_answer: null,
			duration_ms: spent,
			scheduler
		});
		session.recordItem(item, outcome);
		sync();
	}

	async function roundFinished() {
		round = null;
		await ask();
	}

	/** A pick or an assembled answer becomes the same verdict a typed one gets. */
	function judge(outcome: Outcome, closest = current?.answer ?? '') {
		result = { outcome, closest, distance: outcome === 'correct' ? 0 : Infinity };
		phase = 'judged';
	}

	function checkBuilt(text: string) {
		if (!current) return;
		result = text.trim() ? check(text, current.answer, current.accepted) : null;
		if (!result) judge('wrong');
		else phase = 'judged';
	}

	function submitTyped(event?: SubmitEvent) {
		event?.preventDefault();
		if (!current || phase !== 'asking') return;
		result = check(typed, current.answer, current.accepted);
		phase = 'judged';
	}

	/**
	 * Write the final judgement down, then move the session on.
	 *
	 * The answer goes to this device's disk, not to the server: whether the laptop
	 * can be reached is none of this card's business (`offline/sync.svelte.ts`).
	 * It is also what keeps a card from waiting on a round-trip.
	 */
	async function finish(
		outcome: Outcome,
		opts: { grade?: number; overridden?: boolean; setAside?: boolean } = {}
	) {
		if (!current || !session || sending) return;
		sending = true;
		try {
			await outbox.record({
				card_key: current.key,
				mode: cardMode,
				outcome: cardMode === 'flip' ? null : outcome,
				grade: opts.grade ?? null,
				overridden: opts.overridden ?? false,
				raw_answer: cardMode === 'typed' ? typed : null,
				duration_ms: Math.round(performance.now() - shownAt),
				scheduler
			});
			// "End" may have been pressed while this was in flight. The answer is
			// written down either way; an ended session just isn't moved on.
			if (session.finished) return;
			if (opts.setAside) session.setAside();
			else session.record(outcome);
			sinceMatch += 1;
			sync();
			await ask();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			sending = false;
		}
	}

	/** "That's the same thing" (PLAN 3.5): add it to the note, and count it as right. */
	async function acceptTyped() {
		if (!current || !typed.trim()) return;
		const side = current.direction === 'rev' ? 'front' : 'back';
		try {
			const res = await api.accept(current.note_id, side, typed.trim());
			current.accepted = res.accepted;
			// Also on the card the session kept, so it still counts if this one comes back.
			const held = itemOf(current.key);
			if (held) held.card.accepted = res.accepted;
			acceptedNow = true;
			await finish('correct', { grade: 3, overridden: true });
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	function flipGrade(grade: number) {
		finish(grade === 1 ? 'wrong' : 'correct', { grade });
	}

	/**
	 * "Not this session": a miss like any other, but the card leaves the session
	 * instead of coming back later in it — three cards later in practice, at the
	 * end of the queue in a drill. An "almost" counted as wrong is overruling the
	 * checker, so it is marked as such.
	 */
	function setAside() {
		const judged = result?.outcome;
		finish('wrong', { grade: 1, overridden: judged != null && judged !== 'wrong', setAside: true });
	}

	function keydown(event: KeyboardEvent) {
		// Bare keys only, and never the ones being typed into the answer box
		// (keys.ts); holding Enter must not rocket through a run of cards either.
		if (!forPage(event) || (event.repeat && event.key === 'Enter')) return;
		if (phase === 'judged' && event.key === 'Enter') {
			// Suppressing the default also stops the focused Continue being
			// activated a second time by the same press.
			event.preventDefault();
			finish(result!.outcome);
		} else if (phase === 'asking' && cardMode === 'flip') {
			if (!revealed && (event.key === ' ' || event.key === 'Enter')) {
				event.preventDefault();
				revealed = true;
			} else if (revealed && event.key === 'Enter') {
				event.preventDefault();
				flipGrade(GOOD); // so Enter means "on you go" in every mode alike
			} else if (revealed && ['1', '2', '3', '4'].includes(event.key)) {
				flipGrade(Number(event.key));
			}
		}
	}

	/**
	 * The key you are about to press should be the one wearing the focus ring.
	 *
	 * Answering disables the options, which drops the focus, so each verdict hands
	 * it to Continue and each revealed flip hands it to Good — the two things
	 * Enter does. Nothing moves while a question is still open.
	 */
	$effect(() => {
		const land = phase === 'judged' ? onwards : revealed ? good : null;
		if (land) tick().then(() => land.focus());
	});

	function stop() {
		speech.stop();
		session?.stop();
		sync();
		phase = 'done';
	}

	// Answering wants the whole screen; setting up and finishing do not.
	$effect(() => {
		immersion.on = phase === 'asking' || phase === 'judged' || phase === 'matching';
	});

	onMount(load);
	onDestroy(() => {
		immersion.on = false;
		speech.stop();
	});
</script>

<svelte:head><title>{phase === 'setup' ? `Practise ${practising}` : `${done}/${total} · practising`} · CRAM</title></svelte:head>

<svelte:window onkeydown={keydown} />

{#if error}<p class="error" role="alert">{error}</p>{/if}

{#if phase === 'setup'}
	<section class="stack">
		<a class="back" href="/">← Collection</a>
		<h1>Practise {practising}</h1>
		{#if listId}
			<p class="muted small">
				Every word on the list, whether or not it is due. Answering one you already know keeps the
				interval it earned.
			</p>
		{:else if within.fileId}
			<p class="muted small">
				{within.group ? 'One heading of' : 'One file of'}
				{category ? labelText(category.label, category.path) : 'the collection'}
			</p>
		{/if}
		{#if queue === null}
			<div class="card"><Skeleton lines={4} height="var(--tap)" label="Looking for cards that are due" /></div>
		{:else if queue.length === 0}
			<div class="card stack">
				{#if counts && counts.total === 0}
					<h2>There is nothing here to practise</h2>
					<p class="muted">
						This {within.group ? 'heading' : within.fileId ? 'file' : 'collection'} has no cards —
						they may all be suspended, or it may be empty.
					</p>
				{:else}
					<h2>Nothing to practise right now</h2>
					<p class="muted">
						{#if counts?.next_due}Everything here is scheduled, the first for {when(
								counts.next_due
							)}.{:else}Everything here is scheduled for later.{/if}
					</p>
				{/if}
				<p><a class="button" href="/">← Back to the collection</a></p>
			</div>
		{:else}
			{#if counts && counts.ahead_count > 0}
				<p class="muted small">
					{#if counts.due_count + counts.new_count === 0}
						{`Nothing is due here${counts.next_due ? ` until ${when(counts.next_due)}` : ''}, so `}
						{counts.ahead_count === 1 ? 'one card is' : `${counts.ahead_count} cards are`} brought
						forward.
					{:else}
						{counts.ahead_count === 1 ? 'One card is' : `${counts.ahead_count} are`} brought forward to
						fill the session.
					{/if}
					They count towards mastery, and answering one early will not shorten it.
				</p>
			{/if}
			<div class="card stack">
				<fieldset class="stack tight">
					<legend>
						How it runs
						<Help label="What practice and a drill each do">
							<span class="hintline">
								<strong>Practice.</strong> What the schedule asked for today. A word you
								miss comes back a few cards later and has to be right twice in a row
								before it leaves, so the sitting spends itself on what you do not know.
							</span>
							<span class="hintline">
								<strong>Drill.</strong> Everything here, due or not, each asked once. A
								word you miss comes back at the end instead, and one correct answer
								retires it — so you get through the whole lot rather than stuck on one.
								A near miss keeps you moving too, though it is still recorded as one.
							</span>
							<span class="hintline">
								Both use the same scheduler and write the same answers. Answering a word
								early cannot shorten the interval it has already earned.
							</span>
						</Help>
					</legend>
					<label class="choice">
						<input type="radio" bind:group={drill} value={false} onchange={load} />
						<span>Practice <span class="muted small">— learn what you miss</span></span>
					</label>
					<label class="choice">
						<input type="radio" bind:group={drill} value={true} onchange={load} />
						<span>Drill <span class="muted small">— one pass, keep moving</span></span>
					</label>
				</fieldset>
			</div>

			{#if sided}
				<div class="card stack">
					<fieldset class="stack tight">
						<legend>
							Which way
							<Help label="What front and back mean here">
								<span class="hintline">
									A note is a question and its answer — its <strong>front</strong> and its
									<strong>back</strong>, the two columns you type into when you edit a file.
									Asking it both ways round makes two cards of it, and they are rarely
									equally hard: recognising an answer is not the same as producing one.
								</span>
								<span class="hintline">
									Pick a way round to practise only that one. A note written one-way has
									no other side, so it is left out of the side it does not have rather
									than asked backwards.
								</span>
							</Help>
						</legend>
						<label class="choice">
							<input type="radio" bind:group={direction} value="" onchange={load} />
							<span>Both ways <span class="muted small">— {bothWays} cards</span></span>
						</label>
						<label class="choice">
							<input type="radio" bind:group={direction} value="fwd" onchange={load} />
							<span>Front → back <span class="muted small">— {ways.fwd ?? 0} cards</span></span>
						</label>
						<label class="choice">
							<input type="radio" bind:group={direction} value="rev" onchange={load} />
							<span>Back → front <span class="muted small">— {ways.rev ?? 0} cards</span></span>
						</label>
					</fieldset>
				</div>
			{/if}

			<div class="card stack">
				<fieldset class="stack tight">
					<legend>
						How to answer
						<Help label="What each way of answering does">
							{#each choosable as option (option)}
								<span class="hintline"><strong>{LABELS[option].title}.</strong> {LABELS[option].hint}</span>
							{/each}
						</Help>
					</legend>
					{#each choosable as option (option)}
						<label class="choice">
							<input type="radio" bind:group={mode} value={option} />
							<span>{LABELS[option].title}</span>
						</label>
					{/each}
				</fieldset>
			</div>

			<div class="card stack">
				<fieldset class="stack tight">
					<legend>
						How much
						<Help label="What one sitting is">
							<span class="hintline">
								A sitting is the size you pick, reviews included. Whatever you are not
								asked stays due and comes back next time — nothing is lost by choosing
								a short one.
							</span>
							<span class="hintline">
								A quarter of it is kept for words you have not met yet, so a lesson
								still moves on while a backlog drains.
							</span>
						</Help>
					</legend>
					{#each SIZES as step (step.key)}
						<label class="choice">
							<input type="radio" bind:group={size} value={step.key} onchange={load} />
							<span>
								{step.title}
								{#if step.cards}
									<span class="muted small">— up to {step.cards} cards · {howLong(step.cards)}</span>
								{/if}
							</span>
						</label>
					{/each}
				</fieldset>
				<label class="field">
					<span class="what">New cards</span>
					<input
						class="narrow"
						type="number"
						min="0"
						max="500"
						placeholder="all"
						bind:value={newLimit}
						onchange={load}
						aria-describedby="new-all"
					/>
				</label>
				<p id="new-all" class="muted small">
					A ceiling on the share above, not a target. Leave it empty for all of them.
				</p>
				{#if speakable}
					<label class="choice">
						<input type="checkbox" bind:checked={aloud} />
						<span>Read questions aloud <span class="muted small">— as each card comes up</span></span>
					</label>
				{/if}
				{#if allowed.includes('choice') || allowed.includes('match')}
					<label class="field">
						<span class="what">Options from</span>
						<select bind:value={scope} onchange={load} aria-label="Where distractors come from">
							<option value="">this category's setting — {usedScope}</option>
							<option value="auto">nearest words</option>
							<option value="group">this heading</option>
							<option value="file">this file</option>
							<option value="category">this category</option>
						</select>
					</label>
				{/if}
			</div>

			{#if offline}
				<p class="muted small" role="status">
					Practising {queue.length}
					{queue.length === 1 ? 'card' : 'cards'} kept on this device{taken ? ` ${taken}` : ''}{wider
						? ', from across the collection rather than just here'
						: ''}. Answers are kept here and sent when the laptop is back.
				</p>
			{/if}

			<button class="primary wide big-go" onclick={start}>Start</button>

		{/if}
	</section>
{:else if phase === 'done'}
	<section class="stack center">
		<h1>Done</h1>
		{#if summary.asked}
			<p class="tally">
				<strong>{summary.asked}</strong> asked · <strong>{summary.first}</strong> right first time
			</p>
			<p class="muted small">
				{#if summary.left}
					{summary.left} card{summary.left === 1 ? '' : 's'} stayed due — they come back next time.
				{:else}
					Everything you were asked is settled for now.
				{/if}
			</p>
		{/if}
		<div class="row centered">
			<a class="button" href="/">Collection</a>
			<button class="primary" onclick={() => { phase = 'setup'; session = null; load(); }}>Another round</button>
		</div>
	</section>
{:else if phase === 'matching' && round}
	<section class="session">
		<div class="top">
			<button class="small ghost" onclick={stop}>End</button>
			<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax={total} aria-valuenow={done}>
				<span style="width: {total ? (100 * done) / total : 0}%"></span>
			</div>
			<span class="counter">{done}/{total}</span>
		</div>
		<div class="body round">
			<Match cards={round.map((i) => i.card)} onresolved={pairAnswered} oncomplete={roundFinished} />
		</div>
	</section>
{:else if current}
	<section class="session">
		<div class="top">
			<button class="small ghost" onclick={stop}>End</button>
			<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax={total} aria-valuenow={done}>
				<span style="width: {total ? (100 * done) / total : 0}%"></span>
			</div>
			<span class="counter">{done}/{total}</span>
		</div>

		<div class="body">
		<div class="face">
			<p class="label group">
				{#if current.group}{labelBoth(current.group)}{/if}{#if current.is_new}<span class="isnew">new</span>{/if}{#if current.early}<span class="isnew">early</span>{/if}{#if current.priority === 'high'}<span class="isnew" title="Marked to come up more often">marked</span>{:else if current.priority === 'crucial'}<span class="isnew" title="Marked crucial">crucial</span>{/if}{#if current.focus}<span class="isnew" title="On a list that is leading sittings">{current.focus}</span>{/if}
			</p>
			<p class="prompt" lang={current.prompt_lang ?? undefined}>{@html renderInline(current.prompt)}</p>
			<Speak text={current.prompt} lang={current.prompt_lang} what="the question" />
		</div>

		{#if cardMode === 'typed'}
			<form class="answer" onsubmit={submitTyped}>
				<input
					bind:this={input}
					type="text"
					bind:value={typed}
					lang={current.answer_lang ?? undefined}
					autocomplete="off"
					autocapitalize="off"
					spellcheck="false"
					readonly={phase === 'judged'}
					aria-label="Your answer"
					placeholder={current.answer_lang ? `in ${current.answer_lang}` : 'the answer'}
				/>
				{#if phase === 'asking'}
					<div class="row split">
						<button type="button" class="ghost" onclick={() => judge('wrong')}>I don't know</button>
						<button class="primary" type="submit" disabled={!typed.trim()}>Check</button>
					</div>
					<p class="keys muted small">
						<kbd>Enter</kbd> checks, and again to go on
					</p>
				{/if}
			</form>

			{#if phase === 'judged' && result}
				<div class="card verdict {result.outcome}" role="status">
					{#if result.outcome === 'correct'}
						<p class="headline">Right</p>
						{#if result.closest !== current.answer}
							<p class="muted">Shown as <span lang={current.answer_lang ?? undefined}>{current.answer}</span></p>
						{/if}
					{:else if result.outcome === 'almost'}
						<p class="headline">Almost</p>
						<p class="diff" lang={current.answer_lang ?? undefined}>
							{#each diff(typed, result.closest) as seg}<span class={seg.kind}>{seg.text}</span>{/each}
						</p>
						<p>Answer: <strong lang={current.answer_lang ?? undefined}>{current.answer}</strong></p>
					{:else}
						<p class="headline">{typed.trim() ? 'Not quite' : 'The answer'}</p>
						<p class="big" lang={current.answer_lang ?? undefined}>{@html renderInline(current.answer)}</p>
						{#if typed.trim()}<p class="muted">You wrote <s lang={current.answer_lang ?? undefined}>{typed}</s></p>{/if}
					{/if}
					{@render extras()}
					<div class="row split">
						{#if result.outcome !== 'correct'}
							{#if typed.trim()}
								<span class="row tight overrides">
									<button onclick={acceptTyped} disabled={sending}>That's the same thing</button>
									<!-- Right this once, and the note left as it is: a slip of the
									     fingers is not another way of saying the word. -->
									<button onclick={() => finish('correct', { grade: GOOD, overridden: true })} disabled={sending}>
										That's a typo
									</button>
								</span>
							{:else}
								<span></span>
							{/if}
						{:else}
							<button class="ghost" onclick={() => finish('wrong', { grade: 1, overridden: true })} disabled={sending}>
								I didn't know it
							</button>
						{/if}
						<span class="row tight onwards">
							{#if result.outcome !== 'correct'}{@render later()}{/if}
							<button
								bind:this={onwards}
								class="primary"
								aria-keyshortcuts="Enter"
								onclick={() => finish(result!.outcome)}
								disabled={sending}
							>
								Continue
							</button>
						</span>
					</div>
				</div>
			{/if}
		{:else if cardMode === 'choice'}
			<Choice
				card={current}
				bind:picked
				disabled={phase === 'judged'}
				onpick={(_chosen, correct) => judge(correct ? 'correct' : 'wrong')}
			/>
			{#if phase === 'judged' && result}
				{@render plain(result.outcome === 'correct' ? 'Right' : 'Not quite')}
			{/if}
		{:else if cardMode === 'build'}
			<Build card={current} bind:assembled={built} disabled={phase === 'judged'} oncheck={checkBuilt} />
			{#if phase === 'judged' && result}
				{@render plain(
					result.outcome === 'correct' ? 'Right' : result.outcome === 'almost' ? 'Almost' : built.trim() ? 'Not quite' : 'The answer'
				)}
			{/if}
		{:else}
			{#if !revealed}
				<button class="primary wide" aria-keyshortcuts="Space" onclick={() => (revealed = true)}>Show answer</button>
				<p class="keys muted small"><kbd>Space</kbd> shows it</p>
			{:else}
				<div class="card verdict">
					<p class="big" lang={current.answer_lang ?? undefined}>{@html renderInline(current.answer)}</p>
					{@render extras()}
				</div>
				<div class="grades">
					<button aria-keyshortcuts="1" onclick={() => flipGrade(1)} disabled={sending}>Again<small>1</small></button>
					<button aria-keyshortcuts="2" onclick={() => flipGrade(2)} disabled={sending}>Hard<small>2</small></button>
					<button
						bind:this={good}
						class="primary"
						aria-keyshortcuts="3 Enter"
						onclick={() => flipGrade(GOOD)}
						disabled={sending}
					>
						Good<small>3</small>
					</button>
					<button aria-keyshortcuts="4" onclick={() => flipGrade(4)} disabled={sending}>Easy<small>4</small></button>
				</div>
				<div class="row aside">{@render later()}</div>
				<p class="keys muted small"><kbd>1</kbd>–<kbd>4</kbd> grade it · <kbd>Enter</kbd> is Good</p>
			{/if}
		{/if}
		</div>
	</section>
{/if}

{#snippet plain(headline: string)}
	{#if current && result}
		{@const verdict = result}
		<div class="card verdict {verdict.outcome}" role="status">
			<p class="headline">{headline}</p>
			{#if verdict.outcome !== 'correct'}
				<p class="big" lang={current.answer_lang ?? undefined}>{@html renderInline(current.answer)}</p>
			{/if}
			{@render extras()}
			<div class="row split">
				{#if verdict.outcome === 'correct'}
					<button class="ghost" onclick={() => finish('wrong', { grade: 1, overridden: true })} disabled={sending}>
						I didn't know it
					</button>
				{:else}
					<span></span>
				{/if}
				<span class="row tight onwards">
					{#if verdict.outcome !== 'correct'}{@render later()}{/if}
					<button
						bind:this={onwards}
						class="primary"
						aria-keyshortcuts="Enter"
						onclick={() => finish(verdict.outcome)}
						disabled={sending}>Continue</button
					>
				</span>
			</div>
		</div>
	{/if}
{/snippet}

<!-- Wrong, and done with it for this session: it stays due, so it comes back
     next time rather than three cards from now. -->
{#snippet later()}
	<button class="ghost" onclick={setAside} disabled={sending}>Not this session</button>
{/snippet}

{#snippet extras()}
	{#if current}<Speak text={current.answer} lang={current.answer_lang} what="the answer" />{/if}
	{#if current?.accepted?.length}
		<p class="muted small">Also accepted: {current.accepted.join(', ')}</p>
	{/if}
	{#if current?.note}<div class="note">{@html render(current.note)}</div>{/if}
	{#if current?.fields}
		<dl class="fields">
			{#each Object.entries(current.fields).filter(([, v]) => v != null && v !== '') as [key, value]}
				<dt>{key}</dt>
				<dd>{@html renderInline(String(value))}</dd>
			{/each}
		</dl>
	{/if}
	{#if acceptedNow}<p class="muted small">Added to accepted answers.</p>{/if}
{/snippet}

<style>
	.narrow {
		width: 5rem;
		flex: 0 0 auto;
	}

	fieldset {
		border: 0;
		padding: 0;
		margin: 0;
	}

	legend {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.hintline {
		display: block;
	}

	.hintline + .hintline {
		margin-top: var(--space-1);
	}

	.field {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		min-height: var(--tap);
		flex-wrap: wrap;
	}

	.what {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: var(--label-tracking);
		text-transform: uppercase;
		color: var(--muted);
	}

	.field select {
		width: auto;
		flex: 0 1 16rem;
	}

	.big-go {
		min-height: var(--space-8);
		font-size: var(--text-md);
	}

	.center {
		text-align: center;
		padding-top: var(--space-6);
	}

	.centered {
		justify-content: center;
	}

	.tally {
		font-size: var(--text-xl);
	}

	.session {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		min-height: calc(100dvh - var(--space-7));
	}

	/* Where you are stays at the top; the question sits a little above the
	   middle, which is where the eye goes first. */
	.body {
		flex: 1;
		display: flex;
		flex-direction: column;
		justify-content: safe center;
		padding-bottom: 7vh;
		gap: var(--space-6);
	}

	.body.round {
		justify-content: flex-start;
		padding-top: var(--space-2);
		padding-bottom: var(--space-4);
	}

	.top {
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding-bottom: var(--space-3);
		border-bottom: var(--border) solid var(--line-soft);
	}

	.bar {
		flex: 1;
		height: var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--line-soft);
		overflow: hidden;
	}

	.bar span {
		display: block;
		height: 100%;
		background: var(--text);
		transition: width var(--dur-slow) var(--ease-out);
	}

	.counter {
		font-family: var(--font-ui);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: var(--label-tracking);
		color: var(--muted);
	}

	/* The question is typeset on the page. There is nothing around it. */
	.face {
		text-align: center;
	}

	.group {
		margin: 0;
		min-height: 1.2em;
	}

	.isnew {
		margin-left: var(--space-2);
		color: var(--accent-ink);
	}

	.prompt {
		font-size: var(--text-display);
		font-weight: var(--heading-weight);
		letter-spacing: var(--heading-tracking);
		margin: var(--space-3) 0 0;
		line-height: var(--leading-tight);
	}

	.answer input {
		font-family: var(--font-read);
		font-size: var(--text-xl);
		min-height: var(--space-8);
		text-align: center;
	}

	.split {
		justify-content: space-between;
		margin-top: var(--space-4);
	}

	.aside {
		justify-content: center;
		margin-top: var(--space-2);
	}

	@media (max-width: 440px) {
		.split {
			flex-direction: column-reverse;
			align-items: stretch;
		}

		.split button {
			width: 100%;
		}

		.overrides {
			flex-direction: column;
			align-items: stretch;
		}

		/* Continue on top, where the thumb already is; the way out under it. */
		.onwards {
			flex-direction: column-reverse;
			align-items: stretch;
		}
	}

	.keys {
		margin: var(--space-3) 0 0;
		text-align: center;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.keys kbd {
		font: inherit;
		border-bottom: var(--border) solid var(--line);
	}

	@media (hover: none) {
		.keys {
			display: none;
		}
	}

	/* A verdict is a mark in the margin and a word, not a coloured panel. */
	.verdict {
		border: 0;
		border-left: var(--border-strong) solid var(--line);
		border-radius: 0;
		background: transparent;
		padding: 0 0 0 var(--space-4);
	}

	/* Everything in a verdict is flush with the rule; the speaker is a round
	   target with its glyph centred, so it needs pulling back to look flush too. */
	.verdict :global(.speak) {
		margin-left: calc(-1 * var(--space-3));
	}

	.verdict.correct {
		border-left-color: var(--good);
	}

	.verdict.almost {
		border-left-color: var(--almost);
	}

	.verdict.wrong {
		border-left-color: var(--bad);
	}

	.headline {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: var(--label-tracking);
		text-transform: uppercase;
		margin: 0 0 var(--space-2);
	}

	.verdict.correct .headline {
		color: var(--good);
	}

	.verdict.almost .headline {
		color: var(--almost);
	}

	.verdict.wrong .headline {
		color: var(--bad);
	}

	.big {
		font-size: var(--text-2xl);
		font-weight: var(--heading-weight);
		letter-spacing: var(--heading-tracking);
		margin: 0 0 var(--space-3);
		line-height: var(--leading-snug);
	}

	.diff {
		font-size: var(--text-xl);
		margin: 0 0 var(--space-3);
	}

	.diff .extra {
		color: var(--bad);
		text-decoration: line-through;
	}

	.diff .missing {
		color: var(--good);
		text-decoration: underline;
		text-underline-offset: 4px;
	}

	.note {
		font-size: var(--text-sm);
		border-top: var(--border) solid var(--line-soft);
		padding-top: var(--space-3);
		margin-top: var(--space-3);
	}

	.fields {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-1) var(--space-3);
		font-size: var(--text-sm);
	}

	.fields dt {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: var(--label-tracking);
		text-transform: uppercase;
		color: var(--muted);
	}

	.fields dd {
		margin: 0;
	}

	/* Four blocks under a thumb; the number that works is on each one. */
	.grades {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--space-2);
	}

	.grades button {
		flex-direction: column;
		gap: 0;
		min-height: 68px;
		padding: 0 var(--space-2);
	}

	.grades small {
		font-size: var(--text-xs);
		color: var(--muted);
	}

	@media (min-width: 480px) {
		.grades {
			grid-template-columns: repeat(4, 1fr);
		}
	}
</style>
