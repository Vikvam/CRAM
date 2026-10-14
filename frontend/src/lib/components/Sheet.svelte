<script lang="ts">
	/**
	 * A data file read as a page (PLAN 6, phase 4).
	 *
	 * Reading is not practising: covering the answers logs nothing and the
	 * markers are only what the scheduler already knows. The one way out of here
	 * into a session is deliberate — a button, per file or per heading.
	 */
	import { api, type DataFileSummary, type Group, type Note } from '$lib/api/client';
	import { collecting } from '$lib/collecting.svelte';
	import { renderInline, render } from '$lib/markdown';
	import { ASKED, MARKS, PRIORITY_SHOWS, sections, tally, type Progress } from '$lib/sheet';
	import { labelBoth } from '$lib/tree';

	let {
		file,
		groups,
		notes,
		frontLang,
		backLang,
		landed = null
	}: {
		file: DataFileSummary;
		groups: Group[];
		notes: Note[];
		frontLang?: string;
		backLang?: string;
		/** The note a link arrived at, marked so the eye can find it. */
		landed?: string | null;
	} = $props();

	let covered = $state(false);
	/** Which rows have been tapped open while the answers are covered. */
	let shown = $state<Record<string, boolean>>({});

	/** Known first, the way the bars read. */
	const BUCKETS = ['mastered', 'known', 'learning', 'new'] as const;

	const parts = $derived(sections(notes, groups));
	const counts = $derived(tally(notes));
	const progressOf = (note: Note) => (note.progress ?? 'new') as Progress;

	function cover(on: boolean) {
		covered = on;
		shown = {};
	}

	/**
	 * A whole heading onto the list being filled, in one tap.
	 *
	 * The structural bulk gesture, and the only one this app has: a heading is
	 * already a set you think in, because it is how the page prints them and
	 * practice can take one on its own. Twenty words for a test are usually two
	 * or three headings, which is three taps rather than twenty.
	 */
	let added = $state<Record<string, boolean>>({});

	async function addGroup(key: string | null) {
		const into = collecting.into;
		if (!into) return;
		const which = key ?? '\u0000file';
		try {
			await api.addToList(into.id, { file_id: file.id, group: key ?? undefined });
			added = { ...added, [which]: true };
		} catch {
			// Nothing to reach, or signed out. The list page says what is on it.
		}
	}

	const practiseFile = $derived(`/practice/${file.category_id}?file=${file.id}`);
	const practiseGroup = (key: string) => `${practiseFile}&group=${encodeURIComponent(key)}`;
</script>

<div class="sheet stack">
	<div class="controls no-print">
		<label class="toggle" class:on={covered}>
			<input type="checkbox" checked={covered} onchange={(e) => cover(e.currentTarget.checked)} />
			Cover the answers
		</label>
		<div class="row">
			<button class="small" onclick={() => window.print()}>Print</button>
			<a class="button small primary" href={practiseFile}>Practise this file</a>
			{#if collecting.into}
				<button class="small no-print" disabled={added['\u0000file']} onclick={() => addGroup(null)}>
					{added['\u0000file'] ? 'added' : `+ ${collecting.into.name}`}
				</button>
			{/if}
		</div>
	</div>

	{#each parts as section (section.group?.key ?? '—')}
		<section class="group">
			{#if section.group}
				<div class="heading">
					<h2 lang={frontLang}>{labelBoth(section.group.label, section.group.key)}</h2>
					<a class="button small no-print" href={practiseGroup(section.group.key)}>Practise</a>
					{#if collecting.into}
						{@const key = section.group.key}
						<button
							class="small no-print"
							disabled={added[key]}
							onclick={() => addGroup(key)}
						>
							{added[key] ? 'added' : '+ list'}
						</button>
					{/if}
				</div>
				{#if section.group.note}
					<div class="muted small note">{@html render(section.group.note)}</div>
				{/if}
			{/if}
			<table>
				<tbody>
					{#each section.notes as note (note.id)}
						{@const open = !covered || shown[note.id]}
						<tr id="note-{note.id}" class:suspended={note.suspended} class:landed={landed === note.id}>
							<td class="front" lang={frontLang}>{@html renderInline(note.front)}</td>
							<td class="back" lang={backLang}>
								{#if open}
									{@html renderInline(note.back)}
								{:else}
									<button class="reveal" onclick={() => (shown[note.id] = true)}>
										<span class="sr-only">Show the answer for {note.front}</span>
									</button>
								{/if}
							</td>
							<td class="mark no-print">
								{#if note.priority}
									<span class="prio {note.priority}" title={ASKED[note.priority] ?? ''} aria-hidden="true">{PRIORITY_SHOWS[note.priority] ?? ''}</span>
									<span class="sr-only">{ASKED[note.priority] ?? ''}</span>
								{/if}
								<i class="dot {progressOf(note)}" title={MARKS[progressOf(note)]}></i>
								<span class="sr-only">{MARKS[progressOf(note)]}</span>
							</td>
						</tr>
						{#if note.note}
							<tr class="footnote">
								<td colspan="3" class="muted small">{note.note}</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</section>
	{/each}

	{#if !notes.length}
		<p class="muted">No notes yet.</p>
	{:else}
		<p class="muted small legend no-print">
			{#each BUCKETS as bucket (bucket)}
				<span><i class="dot {bucket}"></i> {counts[bucket]} {bucket}</span>
			{/each}
			· {notes.length} note{notes.length === 1 ? '' : 's'}
		</p>
	{/if}
</div>

<style>
	/* Arrived here from a link. A fading wash rather than a selection: it says
	   "this one" and then gets out of the way. */
	tr.landed > td {
		animation: landed 2.4s ease-out;
	}

	@keyframes landed {
		from {
			background: var(--accent-soft, var(--line-soft));
		}
		to {
			background: transparent;
		}
	}

	.sheet {
		--gap: var(--space-6);
	}

	.controls {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		flex-wrap: wrap;
	}

	.controls .row {
		margin-left: auto;
	}

	.toggle {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--tap-sm);
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: var(--label-tracking);
		text-transform: uppercase;
		color: var(--muted);
		cursor: pointer;
	}

	.toggle.on {
		color: var(--text);
	}

	.toggle:has(:focus-visible) {
		outline: var(--border-strong) solid var(--accent);
		outline-offset: 3px;
	}

	/* A heading with its rule, the way a lesson is set on paper. */
	.heading {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-4);
		border-bottom: var(--border-strong) solid var(--text);
		padding-bottom: var(--space-2);
	}

	.heading h2 {
		margin: 0;
		font-size: var(--text-lg);
		color: var(--text);
	}

	.note {
		margin: var(--space-3) 0 0;
	}

	table {
		width: 100%;
		border-collapse: collapse;
	}

	td {
		padding: var(--space-3) var(--space-3) var(--space-3) 0;
		vertical-align: baseline;
		border-bottom: var(--border) solid var(--line-soft);
	}

	tr:last-child td {
		border-bottom: 0;
	}

	/* The word being learned is the content of the page; the gloss explains it. */
	.front {
		width: 44%;
		font-size: var(--text-md);
		line-height: var(--leading-snug);
	}

	.back {
		font-size: var(--text-base);
		color: var(--text);
	}

	.reveal {
		display: block;
		width: 100%;
		min-height: 1.6rem;
		padding: 0;
		background: transparent;
		border: 0;
		border-bottom: var(--border) dashed var(--line);
		border-radius: 0;
	}

	.reveal:hover {
		border-bottom-color: var(--accent);
		background: transparent;
	}

	.mark {
		width: var(--space-6);
		white-space: nowrap;
		text-align: right;
	}

	/* The same number and colour the editor sets, so looking a lesson over
	   before a test shows what was marked the way it was marked. Read-only. */
	.prio {
		display: inline-block;
		margin-right: var(--space-1);
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		line-height: 1.5;
		vertical-align: middle;
	}

	.prio.low {
		background: var(--accent);
		color: var(--on-accent);
	}

	.prio.high {
		background: var(--almost);
		color: var(--on-almost);
	}

	.prio.crucial {
		background: var(--bad);
		color: var(--on-bad);
	}

	/* Drawn, not typed: ○ ◐ ● are missing from some of the fonts this runs in. */
	.dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		border: 1px solid var(--unseen);
		background: transparent;
	}

	.dot.learning {
		border-color: var(--learning);
		background: linear-gradient(90deg, var(--learning) 50%, transparent 50%);
	}

	.dot.known {
		border-color: var(--known);
		background: var(--known);
	}

	/* ◉ — filled, and ringed, because it is a step past the one below it. */
	.dot.mastered {
		border-color: var(--mastered);
		background: var(--mastered);
		box-shadow:
			0 0 0 1px var(--surface),
			0 0 0 2px var(--mastered);
	}

	tr.footnote td {
		padding-top: 0;
		font-size: var(--text-sm);
		color: var(--muted);
	}

	.suspended .front,
	.suspended .back {
		opacity: 0.45;
	}

	.legend {
		display: flex;
		align-items: center;
		gap: var(--space-4);
		flex-wrap: wrap;
		margin: 0;
		padding-top: var(--space-3);
		border-top: var(--border) solid var(--line);
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}

	.legend span {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
	}

	@media (max-width: 420px) {
		.front {
			width: 42%;
		}

		td {
			padding-right: var(--space-2);
		}
	}
</style>
