<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/state';
	import {
		api,
		type Category,
		type DataFileSummary,
		type Duplicate,
		type Group,
		type Note,
		type Related
	} from '$lib/api/client';
	import { ask } from '$lib/confirm.svelte';
	import { labelBoth } from '$lib/tree';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import Chips from '$lib/components/Chips.svelte';
	import Help from '$lib/components/Help.svelte';
	import Sheet from '$lib/components/Sheet.svelte';
	import CategoryPicker from '$lib/components/CategoryPicker.svelte';
	import { PRIORITY_SHOWS } from '$lib/sheet';
	import { blankRow, changes, dirty, isBlank, pair, toRow, type Row } from '$lib/editor/rows';

	let file = $state<DataFileSummary | null>(null);
	/** For the "in …" picker: a file in the wrong category is moved, not re-imported. */
	let categories = $state<Category[]>([]);
	let groups = $state<Group[]>([]);
	let rows = $state<Row[]>([]);
	let archived = $state<Note[]>([]);
	let duplicates = $state<Record<number, Duplicate[]>>({});
	let detail = $state<number | null>(null);
	let showArchived = $state(false);
	/** Reading is what a file is usually opened for; editing is asked for. */
	let editing = $state(false);
	let error = $state<string | null>(null);
	let busy = $state(false);

	//: Lowest first, which is the order the four segments read in. `normal` is
	//: sent as a word and stored as nothing — it is the absence of a mark.
	const LEVELS = ['low', 'normal', 'high', 'crucial'] as const;
	const SAYS: Record<(typeof LEVELS)[number], string> = {
		low: 'low — asked last',
		normal: 'normal',
		high: 'high — asked first, and twice',
		crucial: 'crucial — ahead of high, and never fades out'
	};

	const fileId = $derived(page.params.id!);
	const frontLang = $derived(file?.front_lang ?? undefined);
	const backLang = $derived(file?.back_lang ?? undefined);
	const saved = $derived(rows.filter((r) => r.note));

	/** Read the file and fold it into the rows on screen, never over what is
	 *  half-typed: a reload after a settings change must not swallow a row. */
	async function load() {
		try {
			const data = await api.notes(fileId, true);
			file = data.file;
			groups = data.groups;
			archived = data.notes.filter((n) => n.archived);
			const live = data.notes.filter((n) => !n.archived);
			const shown = new Map(rows.filter((r) => r.note).map((r) => [r.note!.id, r]));
			const merged: Row[] = [];
			for (const note of live) {
				const row = shown.get(note.id);
				if (!row) {
					merged.push(toRow(note));
					continue;
				}
				if (!dirty(row)) {
					row.front = note.front ?? '';
					row.back = note.back ?? '';
					row.group = note.group ?? '';
				}
				row.note = note;
				merged.push(row);
			}
			// Saved while this read was in flight: the row is newer than the answer, so keep it.
			const seen = new Set(data.notes.map((n) => n.id));
			merged.push(...rows.filter((r) => r.note && !seen.has(r.note.id)));
			merged.push(...rows.filter((r) => !r.note));
			if (!merged.some((r) => !r.note)) merged.push(blankRow(live.at(-1)?.group ?? ''));
			rows = merged;
			error = null;
		} catch (e) {
			error = message(e);
		}
	}

	const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

	/** One write at a time per row: tabbing across three fields is one note, not
	 *  three, and two answers can't come back in the wrong order. Each task reads
	 *  the row when its turn comes, so it sees the id the one before it got. */
	const queues = new Map<number, Promise<void>>();

	function enqueue(row: Row, task: () => Promise<void>): Promise<void> {
		const next = (queues.get(row.key) ?? Promise.resolve()).then(task).catch((e) => {
			row.error = message(e);
		});
		queues.set(row.key, next);
		return next;
	}

	const commit = (row: Row) => enqueue(row, () => save(row));

	/** Save one row: a patch if it exists, a new note if it does not. */
	async function save(row: Row) {
		const patch = changes(row);
		if (!Object.keys(patch).length) return;
		if (!row.note && isBlank(row)) return;
		row.saving = true;
		row.error = null;
		try {
			if (row.note) {
				row.note = await api.patchNote(row.note.id, patch);
				await recheck(row);
			} else {
				const created = await api.addNotes(fileId, [patch]);
				row.note = created.notes[0];
				duplicates[row.key] = created.duplicates[0]?.matches ?? [];
				if (rows.at(-1) === row) rows.push(blankRow(row.group));
				await syncOrder();
				await refreshGroups();
			}
			carryGroup(row);
		} catch (e) {
			row.error = message(e);
		} finally {
			row.saving = false;
		}
	}

	/** A heading usually covers several rows, so the row below inherits it. */
	function carryGroup(row: Row) {
		const next = rows[rows.indexOf(row) + 1];
		if (next && !next.note && !next.group) next.group = row.group;
	}

	/** Does this row's prompt already exist elsewhere? (PLAN 6: warn, never block.) */
	async function recheck(row: Row) {
		if (!row.front.trim()) {
			duplicates[row.key] = [];
			return;
		}
		const result = await api.checkDuplicates([pair(row)], {
			excludeNoteIds: row.note ? [row.note.id] : []
		});
		duplicates[row.key] = result.rows[0]?.matches ?? [];
	}

	/** Rows created at the end have to be put back where they are shown. */
	async function syncOrder() {
		const ids = saved.map((r) => r.note!.id);
		const positions = saved.map((r) => r.note!.position);
		const sorted = [...positions].sort((a, b) => a - b);
		if (positions.every((p, i) => p === sorted[i])) return;
		const data = await api.reorderNotes(fileId, ids);
		const byId = new Map(data.notes.map((n) => [n.id, n]));
		for (const row of rows) if (row.note) row.note = byId.get(row.note.id) ?? row.note;
	}

	async function refreshGroups() {
		groups = (await api.notes(fileId)).groups;
	}

	function keydown(event: KeyboardEvent, index: number) {
		if (event.key !== 'Enter') return;
		event.preventDefault();
		const row = rows[index];
		commit(row);
		if (index === rows.length - 1) {
			if (!isBlank(row)) rows.push(blankRow(row.group));
		} else {
			rows.splice(index + 1, 0, blankRow(row.group));
		}
		focusRow(index + 1);
	}

	function focusRow(index: number) {
		requestAnimationFrame(() => {
			const input = document.querySelector<HTMLInputElement>(`#front-${rows[index]?.key}`);
			input?.focus();
		});
	}

	async function archive(row: Row) {
		if (row.note) {
			const reviews = row.note.reviewed;
			const label = row.front || row.back || 'this note';
			const ok = await ask({
				title: `Archive ${label}?`,
				detail: reviews
					? `It has ${reviews} answer${reviews === 1 ? '' : 's'} behind it. The history is kept and you can restore the note.`
					: 'It leaves practice. The note is kept and you can restore it.',
				confirm: 'Archive'
			});
			if (!ok) return;
			const note = await api.archiveNote(row.note.id);
			archived = [...archived, note];
		}
		rows = rows.filter((r) => r !== row);
		if (detail === row.key) detail = null;
		if (!rows.length) rows = [blankRow()];
	}

	async function restore(note: Note) {
		const back = await api.archiveNote(note.id, true);
		archived = archived.filter((n) => n.id !== note.id);
		rows = [...rows.filter((r) => !isBlank(r) || r.note), toRow(back), blankRow()];
	}

	/** The detail panel writes the rarer fields straight through. */
	function patchDetail(row: Row, patch: Parameters<typeof api.patchNote>[1]) {
		return enqueue(row, async () => {
			if (!row.note) await save(row);
			if (!row.note) return;
			busy = true;
			try {
				row.note = await api.patchNote(row.note.id, patch);
			} finally {
				busy = false;
			}
		});
	}

	/** The title is one plain line — what you type is the whole name of the file. */
	async function retitle(event: Event) {
		const value = (event.target as HTMLInputElement).value.trim();
		file = await api.patchFile(fileId, { title: value || null });
	}

	/** The file's own settings. Changing the default type restates every note's
	 *  cards on the server, so the rows are reloaded to show the new counts. */
	async function patchFile(patch: Parameters<typeof api.patchFile>[1]) {
		busy = true;
		try {
			file = await api.patchFile(fileId, patch);
			if ('default_type' in patch) await load();
		} catch (e) {
			error = message(e);
		} finally {
			busy = false;
		}
	}

	async function archiveFile() {
		const ok = await ask({
			title: 'Archive this whole file?',
			detail: 'Every note in it leaves practice. Nothing is deleted, and the file can be restored.',
			confirm: 'Archive the file'
		});
		if (!ok) return;
		file = await api.archiveFile(fileId);
	}

	function download() {
		api.file(fileId).then((data) => {
			const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' });
			const a = document.createElement('a');
			a.href = URL.createObjectURL(blob);
			a.download = `${data.id ?? 'datafile'}.json`;
			a.click();
			URL.revokeObjectURL(a.href);
		});
	}

	const accept = (row: Row, side: 'front' | 'back') => row.note?.accept?.[side] ?? [];

	function setAccept(row: Row, side: 'front' | 'back', values: string[]) {
		const other = side === 'front' ? 'back' : 'front';
		const rest = row.note?.accept?.[other] ?? [];
		patchDetail(row, { accept: { [side]: values, ...(rest.length ? { [other]: rest } : {}) } });
	}

	/**
	 * Landing on one row rather than on a fifty-six-row grid.
	 *
	 * Every link into a lesson used to arrive at the top of it, so acting on an
	 * audit finding or a search result meant reading the whole sheet by eye to
	 * find the word again. `?note=` is the id to scroll to; the mark fades,
	 * because it is a "here" and not a selection.
	 */
	/**
	 * Other words in the collection beside the one whose panel is open.
	 *
	 * Out of what is already written down — words that mean the same or nearly
	 * the same thing, and whether the two already accept each other, which is the
	 * thing worth fixing when they do not. Not antonyms: nothing in a note
	 * records that one word is the opposite of another, so the heading stands in
	 * for it, which is where a textbook puts a pair anyway.
	 */
	let beside = $state<Record<string, Related[]>>({});

	async function lookBeside(noteId: string) {
		if (beside[noteId]) return;
		try {
			beside = { ...beside, [noteId]: (await api.related(noteId)).related };
		} catch {
			beside = { ...beside, [noteId]: [] }; // offline, or the note has gone
		}
	}

	const wanted = $derived(page.url.searchParams.get('note'));
	let landed = $state<string | null>(null);

	async function land() {
		if (!wanted || landed === wanted) return;
		await tick();
		const row = document.getElementById(`note-${wanted}`);
		if (!row) return;
		landed = wanted;
		row.scrollIntoView({ block: 'center', behavior: 'smooth' });
	}

	$effect(() => {
		// Depends on both: the row does not exist until the notes have arrived,
		// and the grid and the sheet render different elements for it.
		if (wanted && rows.length) void land();
	});

	onMount(() => {
		load();
		api.categories().then((all) => (categories = all));
	});
</script>

<svelte:head><title>{file?.title || 'Data file'} · CRAM</title></svelte:head>

<section class="stack">
	<a class="back no-print" href="/">← Collection</a>
	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if file}
		<div class="head">
			<div class="grow">
				{#if editing}
					<input
						class="title"
						value={file.title ?? ''}
						placeholder="Untitled file"
						aria-label="File title"
						onchange={retitle}
					/>
				{:else}
					<h1 class="title read">{file.title || 'Untitled file'}</h1>
				{/if}
				<div class="row settings">
					<span class="muted small">{saved.length} note{saved.length === 1 ? '' : 's'}</span>
					{#if editing}
					<label class="muted small">
						languages
						<input
							class="lang"
							value={file.front_lang ?? ''}
							placeholder="front"
							aria-label="Front language"
							disabled={busy}
							onchange={(e) => patchFile({ front_lang: e.currentTarget.value.trim() || null })}
						/>
						→
						<input
							class="lang"
							value={file.back_lang ?? ''}
							placeholder="back"
							aria-label="Back language"
							disabled={busy}
							onchange={(e) => patchFile({ back_lang: e.currentTarget.value.trim() || null })}
						/>
					</label>
					<label class="muted small">
						cards
						<select
							value={file.default_type ?? ''}
							aria-label="Default note type"
							disabled={busy}
							onchange={(e) =>
								patchFile({
									default_type: (e.currentTarget.value || null) as 'bidirectional' | 'directional' | null
								})}
						>
							<option value="">front → back (default)</option>
							<option value="bidirectional">both ways</option>
							<option value="directional">front → back</option>
						</select>
					</label>
					<label class="muted small category">
						in
						<CategoryPicker
							value={file.category_id}
							bind:categories
							disabled={busy}
							onpick={(id) => patchFile({ category_id: id })}
						/>
					</label>
					{/if}
					{#if file.archived}<span class="pill bad">archived</span>{/if}
				</div>
			</div>
			<div class="row">
				<button class="small" aria-pressed={editing} onclick={() => (editing = !editing)}>
					{editing ? 'Read' : 'Edit'}
				</button>
				{#if editing}
					<button class="small" onclick={download}>Download JSON</button>
					{#if file.archived}
						<button class="small" onclick={async () => (file = await api.archiveFile(fileId, true))}>Restore</button>
					{:else}
						<button class="small" onclick={archiveFile}>Archive file</button>
					{/if}
				{/if}
			</div>
		</div>

		{#if !editing}
			<div class="card">
				<Sheet
					{file}
					{groups}
					{landed}
					notes={saved.map((r) => r.note!)}
					frontLang={frontLang}
					backLang={backLang}
				/>
			</div>
		{:else}
		<div class="card grid-card">
			<table>
				<thead>
					<tr>
						<th class="num" scope="col"><span class="sr-only">Row</span></th>
						<th scope="col">front {#if frontLang}<span class="muted">({frontLang})</span>{/if}</th>
						<th scope="col">back {#if backLang}<span class="muted">({backLang})</span>{/if}</th>
						<th scope="col" class="group-col">group</th>
						<th scope="col" class="prio-col" title="How often it comes up">priority</th>
						<th scope="col"><span class="sr-only">Row actions</span></th>
					</tr>
				</thead>
				<tbody>
					{#each rows as row, index (row.key)}
						<tr
							id={row.note ? `note-${row.note.id}` : undefined}
							class:pending={!row.note}
							class:open={detail === row.key}
							class:landed={!!row.note && landed === row.note.id}
						>
							<td class="num">{row.note ? index + 1 : '+'}</td>
							<td>
								<input
									id="front-{row.key}"
									bind:value={row.front}
									lang={frontLang}
									placeholder={row.note ? '' : 'new note'}
									aria-label="Front of row {index + 1}"
									onblur={() => commit(row)}
									onkeydown={(e) => keydown(e, index)}
								/>
							</td>
							<td>
								<input
									bind:value={row.back}
									lang={backLang}
									aria-label="Back of row {index + 1}"
									onblur={() => commit(row)}
									onkeydown={(e) => keydown(e, index)}
								/>
							</td>
							<td class="group-col">
								<input
									bind:value={row.group}
									list="groups"
									aria-label="Group of row {index + 1}"
									onblur={() => commit(row)}
									onkeydown={(e) => keydown(e, index)}
								/>
							</td>
							<td class="prio-col">
								<span class="levels" role="radiogroup" aria-label="How often row {index + 1} comes up">
									{#each LEVELS as level (level)}
										<label class="step {level}" title="How often it comes up — {SAYS[level]}">
											<input
												type="radio"
												class="sr-only"
												name="priority-{row.key}"
												aria-label={SAYS[level]}
												checked={(row.note?.priority ?? 'normal') === level}
												disabled={busy}
												onchange={() => patchDetail(row, { priority: level })}
											/>
											<span>{PRIORITY_SHOWS[level]}</span>
										</label>
									{/each}
								</span>
							</td>
							<td class="row-actions">
								{#if row.saving}<span class="muted small" aria-live="polite">saving…</span>{/if}
								<button
									class="ghost"
									aria-label="More fields for row {index + 1}"
									aria-expanded={detail === row.key}
									onclick={() => (detail = detail === row.key ? null : row.key)}>⋯</button
								>
								<button class="ghost" aria-label="Archive row {index + 1}" onclick={() => archive(row)}>✕</button>
							</td>
						</tr>
						{#if row.error}
							<tr class="note-row"><td></td><td colspan="5" class="error small">{row.error}</td></tr>
						{/if}
						{#if duplicates[row.key]?.length}
							<tr class="note-row">
								<td></td>
								<td colspan="5" class="dup small">
									{#each duplicates[row.key] as match (match.note_id)}
										<span>
											{#if match.by === 'back'}
												<!-- The gloss is the prompt going the other way, so two words
													 sharing one is a question with two right answers. -->
												Same meaning as <span lang={frontLang}>{match.front}</span> in
											{:else}
												{match.same_back ? 'Already in' : 'Same prompt, different meaning in'}
											{/if}
											<a href="/files/{match.data_file_id}">{match.category_path}</a>
											{#if match.by === 'front' && !match.same_back}
												<span class="muted">({match.back})</span>
											{/if}
										</span>
									{/each}
									<button class="ghost" onclick={() => (duplicates[row.key] = [])}>Keep both</button>
								</td>
							</tr>
						{/if}
						{#if detail === row.key}
							<tr class="note-row">
								<td></td>
								<td colspan="5">
									<div class="detail stack" aria-label="More fields">
										<label>
											type
											<select
												value={row.note?.type ?? ''}
												disabled={busy}
												onchange={(e) =>
													patchDetail(row, {
														type: (e.currentTarget.value || null) as 'bidirectional' | 'directional' | null
													})}
											>
												<option value="">file default{file.default_type ? ` (${file.default_type})` : ''}</option>
												<option value="bidirectional">bidirectional — both ways</option>
												<option value="directional">directional — front to back only</option>
											</select>
										</label>
										<Chips
											values={accept(row, 'back')}
											label="also accept as back"
											lang={backLang}
											onchange={(values: string[]) => setAccept(row, 'back', values)}
										/>
										<Chips
											values={accept(row, 'front')}
											label="also accept as front"
											lang={frontLang}
											onchange={(values: string[]) => setAccept(row, 'front', values)}
										/>
										<label>
											note
											<input
												value={row.note?.note ?? ''}
												placeholder="shown with the answer"
												disabled={busy}
												onchange={(e) => patchDetail(row, { note: e.currentTarget.value || null })}
											/>
										</label>
										<label class="inline">
											<input
												type="checkbox"
												checked={row.note?.suspended ?? false}
												disabled={busy}
												onchange={(e) => patchDetail(row, { suspended: e.currentTarget.checked })}
											/>
											suspended — keep the note, leave it out of practice
										</label>
										{#if row.note}
											{@const near = beside[row.note.id]}
											<div class="beside">
												{#if near === undefined}
													<button class="ghost" onclick={() => lookBeside(row.note!.id)}>
														Words beside this one
													</button>
												{:else if near.length === 0}
													<p class="muted small">Nothing else in the collection is close to it.</p>
												{:else}
													<ul class="muted small">
														{#each near as other (other.note_id)}
															<li>
																<a href="/files/{other.data_file_id}?note={other.note_id}" lang={frontLang}>
																	{other.front}
																</a>
																<span>{other.back}</span>
																<span class="why">
																	{#if other.how === 'same-meaning'}same meaning
																	{:else if other.how === 'near-meaning'}nearly the same
																	{:else}same heading{/if}
																</span>
																{#if other.how !== 'same-heading'}
																	{#if other.accepts && other.accepted_by}
																		<span class="ok">accepted both ways</span>
																	{:else if other.accepts || other.accepted_by}
																		<!-- The audit's one-sided finding, where you can act on it. -->
																		<button
																			class="ghost"
																			disabled={busy}
																			onclick={() =>
																				other.accepted_by
																					? setAccept(row, 'front', [...accept(row, 'front'), other.front ?? ''])
																					: void api
																							.accept(other.note_id, 'front', row.front ?? '')
																							.then(() => lookBeside(row.note!.id))}
																		>
																			accepted one way only — fix
																		</button>
																	{/if}
																{/if}
																{#if other.suspended}<span class="why">set aside</span>{/if}
															</li>
														{/each}
													</ul>
												{/if}
											</div>
											<p class="muted small">
												{row.note.cards} card{row.note.cards === 1 ? '' : 's'} ·
												{row.note.reviewed} answer{row.note.reviewed === 1 ? '' : 's'}
												{#if row.note.status}· {row.note.status}{/if}
												{#if row.note.page}· page {row.note.page}{/if}
											</p>
										{/if}
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
			<datalist id="groups">
				{#each groups as group (group.key)}<option value={group.key}>{labelBoth(group.label, group.key)}</option>{/each}
			</datalist>
			<p class="muted small hint">
				<Help label="How the grid behaves">
					Tab moves across, Enter adds a row below, and rows save as you leave them.
				</Help>
			</p>
		</div>
		{/if}

		{#if archived.length}
			<div class="card stack">
				<button class="ghost left" onclick={() => (showArchived = !showArchived)} aria-expanded={showArchived}>
					{showArchived ? '▾' : '▸'} {archived.length} archived note{archived.length === 1 ? '' : 's'}
				</button>
				{#if showArchived}
					<ul class="archived">
						{#each archived as note (note.id)}
							<li class="spread">
								<span><span lang={frontLang}>{note.front}</span> · <span lang={backLang}>{note.back}</span></span>
								<button class="small" onclick={() => restore(note)}>Restore</button>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		{/if}
	{:else if !error}
		<div class="card"><Skeleton lines={6} height="var(--space-5)" label="Loading the data file" /></div>
	{/if}
</section>

<style>
	.beside ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.beside li {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: var(--space-2);
		padding: var(--space-1) 0;
	}

	.beside .why {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--muted);
	}

	.beside .ok {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--good);
	}

	/* Arrived here from a link — a search result, or something the audit found. */
	tr.landed > td {
		animation: landed 2.4s ease-out;
	}

	@keyframes landed {
		from {
			background: var(--line-soft);
		}
		to {
			background: transparent;
		}
	}

	.head {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		flex-wrap: wrap;
	}

	.grow {
		flex: 1;
		min-width: 12rem;
	}

	.title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		width: 100%;
		padding: var(--space-1) var(--space-2);
	}

	/* Reading, it is the page's heading and wraps like one; editing, it is
	   plainly a field, so a long title that scrolls inside it is no surprise. */
	.title.read {
		margin: 0;
		padding: var(--space-1) 0;
		overflow-wrap: anywhere;
	}

	input.title {
		border-color: var(--line-soft);
		background: var(--surface);
	}

	input.title:hover,
	input.title:focus {
		border-color: var(--line);
	}

	.settings {
		align-items: center;
		gap: var(--space-2) var(--space-4);
		margin: var(--space-2) 0 var(--space-1);
	}

	.settings label {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
	}

	.settings .category {
		min-width: 0;
	}

	.settings .category :global(select) {
		max-width: 16rem;
	}

	.settings .lang {
		width: 4rem;
	}

	.settings .lang,
	.settings select {
		min-height: var(--space-6);
		padding: 0 var(--space-2);
		font-size: var(--text-sm);
	}

	.grid-card {
		/* Positioned so the screen-reader-only text inside scrolls with the
		   table instead of widening the page on a phone. */
		position: relative;
		padding: var(--space-2);
		overflow-x: auto;
	}

	table {
		width: 100%;
		min-width: 30rem;
		border-collapse: collapse;
	}

	th {
		text-align: left;
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		color: var(--muted);
		padding: 0 var(--space-1) var(--space-1);
	}

	td {
		padding: 1px;
		border-top: var(--border) solid var(--line);
		vertical-align: middle;
	}

	.note-row td {
		border-top: 0;
		padding-bottom: var(--space-2);
	}

	td input {
		width: 100%;
		min-height: calc(var(--tap) - var(--space-2));
		padding: var(--space-1) var(--space-2);
		border-color: transparent;
		background: transparent;
	}

	td input:hover,
	td input:focus {
		border-color: var(--line);
		background: var(--surface);
	}

	/* Whatever is being learned is bigger than the gloss beside it, in any
	   script (PLAN 3.7) — the editor is read as much as it is typed into. */
	td input[lang]:not([lang|='en']) {
		font-size: var(--text-md);
	}

	.num {
		width: var(--space-6);
		color: var(--muted);
		font-size: var(--text-xs);
		text-align: right;
		padding-right: var(--space-2);
	}

	.pending .num {
		color: var(--accent);
	}

	.group-col {
		width: 22%;
	}

	.row-actions {
		width: 6rem;
		white-space: nowrap;
		text-align: right;
	}

	.prio-col {
		width: 10.5rem;
		white-space: nowrap;
	}

	/* Four joined segments, −1 to +2: how often this word comes up. Every level
	   is always on show and the chosen one fills with its colour — cool for
	   less, warm for more, and a plain grey for normal so it still reads as a
	   choice rather than an absence. */
	.levels {
		display: inline-flex;
		vertical-align: middle;
		border: var(--border) solid var(--line);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.step {
		--c: var(--muted);
		--on: var(--bg);
		--hover: var(--text);
		/* Anchors the hidden radio; without it the input sits against some far
		   ancestor and widens the whole page. */
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		min-width: var(--tap-sm);
		min-height: var(--tap-sm);
		padding: 0 var(--space-2);
		font-size: var(--text-sm);
		font-variant-numeric: tabular-nums;
		color: var(--muted);
		cursor: pointer;
	}

	.step + .step {
		border-left: 1px solid var(--line-soft);
	}

	.step.low {
		--c: var(--accent);
		--on: var(--on-accent);
		--hover: var(--accent);
	}

	.step.high {
		--c: var(--almost);
		--on: var(--on-almost);
		--hover: var(--almost);
	}

	.step.crucial {
		--c: var(--bad);
		--on: var(--on-bad);
		--hover: var(--bad);
	}

	.step:hover {
		color: var(--hover);
	}

	.step:has(input:checked) {
		background: var(--c);
		color: var(--on);
		font-weight: 600;
	}

	.step:has(input:focus-visible) {
		outline: 2px solid var(--accent);
		outline-offset: -3px;
	}

	.row-actions button {
		min-width: var(--tap-sm);
		min-height: var(--tap-sm);
		padding: 0;
		color: var(--muted);
	}

	.row-actions button:hover {
		color: var(--text);
	}

	.open td {
		background: var(--sunken);
	}

	.detail {
		--gap: var(--space-3);
		padding: var(--space-2) var(--space-1) var(--space-3);
	}

	.detail label {
		display: grid;
		gap: var(--space-1);
		font-size: var(--text-sm);
		color: var(--muted);
	}

	.detail label.inline {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	/* The panel sits inside a cell, so undo the borderless look the grid gives inputs. */
	.detail input {
		border-color: var(--line);
		background: var(--surface);
	}

	.detail input[type='checkbox'] {
		width: auto;
		flex: 0 0 auto;
		min-height: 0;
	}

	.dup {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
		color: var(--almost);
	}

	.hint {
		margin: var(--space-2) var(--space-1) 0;
	}

	.archived {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.archived li {
		min-height: var(--tap);
	}

	.archived li + li {
		border-top: var(--border) solid var(--line-soft);
	}

	.left {
		justify-content: flex-start;
		padding: 0;
	}

	@media (max-width: 640px) {
		.group-col {
			display: none;
		}

		/* The row number is decoration; the two columns being read are not. It
		   collapses rather than disappearing, so the table keeps its columns. */
		.num {
			width: 0;
			padding: 0;
			font-size: 0;
		}

		table {
			min-width: 41rem;
		}

		.row-actions {
			width: 5.5rem;
		}
	}
</style>
