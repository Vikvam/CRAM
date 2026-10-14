<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { replaceState } from '$app/navigation';
	import {
		api,
		type Audit,
		type AuditFinding,
		type AuditNote,
		type Category,
		type ExportReport,
		type ImportJob,
		type NoteHit,
		type WordList
	} from '$lib/api/client';
	import { collecting } from '$lib/collecting.svelte';
	import WordRow from '$lib/components/WordRow.svelte';
	import { keepCategories, keptCategories } from '$lib/offline/collection';
	import { sync } from '$lib/offline/sync.svelte';
	import { buildTree, labelText } from '$lib/tree';
	import Help from '$lib/components/Help.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import TreeNode from '$lib/components/TreeNode.svelte';

	let categories = $state<Category[] | null>(null);
	let imports = $state<ImportJob[]>([]);
	let error = $state<string | null>(null);
	let open = $state<Record<string, boolean>>({});
	let newPath = $state('');
	let creating = $state(false);
	let exporting = $state(false);
	let report = $state<ExportReport | null>(null);
	/** What is wrong with the collection, if anything. Null until asked, or offline. */
	let looked = $state<Audit | null>(null);

	/**
	 * Finding a word.
	 *
	 * The query lives in the URL, so back and forward work and a result can be
	 * sent to yourself. While there is one, the results stand in for the tree:
	 * two lists of the same collection on one screen would be a puzzle about
	 * which one you are looking at.
	 */
	let typed = $state(page.url.searchParams.get('q') ?? '');
	let found = $state<NoteHit[] | null>(null);
	let total = $state(0);
	let searching = $state(false);
	/**
	 * The search could not be asked, as against asked and answered with nothing.
	 * "Nothing matches" would be a lie about the collection when the truth is that
	 * this build of the page is newer than the server it is talking to — which is
	 * the ordinary state of things for as long as it takes to restart it.
	 */
	let unasked = $state(false);
	let lists = $state<WordList[]>([]);
	/** Which search this is, so a slow answer cannot overwrite a newer one. */
	let latest = 0;

	const STRIP = 50;
	const query = $derived(typed.trim());

	$effect(() => {
		const wanted = query;
		if (!wanted) {
			found = null;
			total = 0;
			return;
		}
		const mine = ++latest;
		searching = true;
		api
			.search(wanted, { limit: STRIP })
			.then((result) => {
				if (mine !== latest) return; // a newer query has been typed since
				found = result.hits;
				total = result.total;
				unasked = false;
			})
			.catch(() => {
				if (mine !== latest) return;
				found = [];
				unasked = true;
			})
			.finally(() => {
				if (mine === latest) searching = false;
			});
	});

	/** Keep the URL in step without a navigation for every keystroke. */
	$effect(() => {
		const url = new URL(page.url);
		if (query) url.searchParams.set('q', query);
		else url.searchParams.delete('q');
		if (url.href !== page.url.href) replaceState(url, {});
	});

	async function addToList(word: NoteHit) {
		const into = collecting.into;
		if (!into) return;
		try {
			await api.addToList(into.id, { note_ids: [word.note_id] });
			collecting.note(word.note_id);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	/**
	 * Every finding worth interrupting for, each with the sentence that says what
	 * it is. The three kinds mean different things and want different fixes, so
	 * one undifferentiated list would be a puzzle rather than a prompt.
	 */
	const wrong = $derived.by(() => {
		if (!looked || looked.clean) return [];
		const words = (f: AuditFinding) =>
			[...new Set(f.notes.map((n: AuditNote) => n.front ?? '—'))].join(' · ');
		const where = (f: AuditFinding) =>
			[...new Map(f.notes.map((n: AuditNote) => [n.data_file_id, n])).values()];
		return [
			...looked.duplicates.map((f) => ({
				key: `dup:${f.key}`,
				says: 'The same word twice',
				what: `${words(f)} · ${f.notes[0].back ?? '—'}`,
				fix: 'Two notes for one word split its history. Keep one.',
				where: where(f)
			})),
			...looked.collisions.map((f) => ({
				key: `clash:${f.key}`,
				says: 'Two words, one meaning',
				what: `${words(f)} · ${f.key}`,
				fix: `Asked for "${f.key}", either is right, so one of them is marked wrong. Let each accept the other.`,
				where: where(f)
			})),
			...looked.one_sided.map((f) => ({
				key: `half:${f.key}`,
				says: 'Accepted one way only',
				what: `${words(f)} · ${f.key}`,
				fix: 'One of them takes the other as an answer; the other does not.',
				where: where(f)
			}))
		];
	});

	const tree = $derived(categories ? buildTree(categories) : []);
	const cards = $derived(tree.reduce((n, node) => n + node.totals.cards, 0));
	const pending = $derived(imports.filter((j) => ['pending', 'running', 'review', 'failed'].includes(j.status)));
	const categoryName = (id: string | null | undefined) => {
		const c = categories?.find((c) => c.id === id);
		return c ? labelText(c.label, c.path) : '';
	};

	async function load() {
		try {
			[categories, imports] = await Promise.all([api.categories(), api.imports()]);
			error = null;
			void keepCategories(categories);
			void lookOver();
		} catch (e) {
			// Nothing to reach. What this device last saw is still the truth about
			// what there is to practise, and it is what every way into a session is
			// built from — without it the app opens on an empty collection with
			// nothing to tap, cards on the device or not.
			const last = await keptCategories();
			if (!last) {
				error = e instanceof Error ? e.message : String(e);
				return;
			}
			categories = last;
			imports = [];
			// The offline banner already says it; a red error as well would read as
			// something being broken.
			error = null;
		}
	}

	/**
	 * Look the collection over, quietly and never in the way.
	 *
	 * Two notes glossed the same way make a question with two right answers, and
	 * the extractor produces them honestly — so this has to be visible from the
	 * app rather than only from `memo audit`, which is a command nobody remembers
	 * to run. It never blocks the tree and it says nothing at all when the
	 * collection is clean, which is most days.
	 */
	async function lookOver() {
		try {
			looked = await api.audit();
		} catch {
			looked = null; // offline, or signed out: not something to report here
		}
	}

	async function create(event: SubmitEvent) {
		event.preventDefault();
		const path = newPath.trim().replace(/^\/+|\/+$/g, '');
		if (!path) return;
		creating = true;
		try {
			await api.createCategory(path);
			newPath = '';
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			creating = false;
		}
	}

	/** PLAN 5: export is manual. It writes the readable copy of the collection
	 *  and never deletes anything it did not write. */
	async function exportTree() {
		exporting = true;
		report = null;
		try {
			report = await api.exportTree();
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			exporting = false;
		}
	}

	async function loadLists() {
		try {
			lists = (await api.lists()).lists;
		} catch {
			lists = []; // offline, or signed out: lists are a laptop thing
		}
	}

	onMount(async () => {
		// On screen at once, from this device alone. Finding out whether the
		// laptop is there is the slow part, and the collection does not need to
		// wait for the answer to be drawn — it is replaced the moment one comes.
		const last = await keptCategories();
		if (last && categories === null) categories = last;
		await load();
		void loadLists();
	});
</script>

<svelte:head><title>Collection · CRAM</title></svelte:head>

<section class="stack">
	<div class="titling">
		<h1>Collection</h1>
		{#if cards}
			<a class="button primary" href="/practice/all">Practise</a>
		{/if}
	</div>

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	<form class="find" role="search" onsubmit={(e) => e.preventDefault()}>
		<label class="sr-only" for="find">Find a card</label>
		<input
			id="find"
			type="search"
			bind:value={typed}
			placeholder="Find a card"
			autocomplete="off"
			spellcheck="false"
		/>
		{#if query}
			<button type="button" onclick={() => (typed = '')}>Clear</button>
		{/if}
	</form>

	{#if collecting.into}
		<p class="collecting" role="status">
			Adding to <a href="/lists/{collecting.into.id}">{collecting.into.name}</a>
			{#if collecting.added.size}· {collecting.added.size} added{/if}
			<button type="button" onclick={() => collecting.stop()}>Done</button>
		</p>
	{/if}

	{#if query}
		{#if found === null}
			<Skeleton lines={4} height="var(--space-6)" label="Searching" />
		{:else if found.length === 0}
			<p class="muted empty">
				{#if searching}Looking…
				{:else if unasked}Finding a card needs the laptop, and a newer one than this: restart the
					server and it will work.
				{:else}Nothing matches “{query}”.{/if}
			</p>
		{:else}
			<p class="muted small" role="status">
				{total} word{total === 1 ? '' : 's'}{total > found.length ? ` · showing ${found.length}` : ''}
			</p>
			<ul class="words">
				{#each found as word (word.note_id)}
					<WordRow {word}>
						{#snippet actions(hit)}
							{#if collecting.into}
								{#if collecting.has(hit.note_id)}
									<span class="tag muted small">added</span>
								{:else}
									<button type="button" onclick={() => addToList(hit)}>+ list</button>
								{/if}
							{/if}
						{/snippet}
					</WordRow>
				{/each}
			</ul>
		{/if}
	{:else if pending.length}
		<ul class="imports">
			{#each pending as job (job.id)}
				<li class="spread">
					<a href="/imports/{job.id}">{job.pages.length} page{job.pages.length === 1 ? '' : 's'} → {categoryName(job.category_id)}</a>
					{#if job.status === 'review'}<span class="pill ready">ready</span>
					{:else if job.status === 'failed'}<span class="pill bad">failed</span>
					{:else}<span class="pill">reading</span>{/if}
				</li>
			{/each}
		</ul>
	{/if}

	{#if query}
		<!-- results stand in for the tree, above -->
	{:else if categories === null}
		<Skeleton lines={5} height="var(--space-6)" label="Loading the collection" />
	{:else if tree.length === 0}
		<p class="muted empty">Nothing here yet. Make a category below, then add photos of your pages to it.</p>
	{:else}
		<ul class="tree">
			{#each tree as node (node.category.id)}
				<TreeNode {node} bind:open categories={categories ?? []} onchanged={load} offline={!sync.online} />
			{/each}
		</ul>
	{/if}

	{#if wrong.length}
		<div class="card stack looked">
			<h2>
				Worth a look
				<Help label="What this is">
					A word's meaning is also the question asked in the other direction, so two notes glossed
					the same way ask one question with two right answers — and whichever you type, one of them
					is marked wrong. Nothing here is urgent; it is what an extractor leaves behind, and the
					app can only point at it.
				</Help>
			</h2>
			<ul class="findings">
				{#each wrong as finding (finding.key)}
					<li>
						<span class="finding-kind">{finding.says}</span>
						<span class="finding-words">{finding.what}</span>
						<span class="finding-fix">{finding.fix}</span>
						<span class="finding-where">
							{#each finding.where as note (note.data_file_id)}
								<a href="/files/{note.data_file_id}?note={note.note_id}">{note.file_title ?? 'untitled file'}</a>
							{/each}
						</span>
					</li>
				{/each}
			</ul>
		</div>
	{/if}

	{#if !query}
		<div class="card stack lists">
			<h2>
				Lists
				<Help label="What a list is for">
					A test is coming and twenty words are on it. A mark on a word is for ever and
					everywhere, so using it for a test leaves marks behind that nobody takes off again — a
					list is a set of words with a date instead. While the date is ahead, its words lead
					every sitting; when it passes they stop, and the list stays so you can drill it again.
					Nothing moves out of its lesson and no mark is written.
				</Help>
			</h2>
			{#if lists.length}
				<ul class="list-rows">
					{#each lists as item (item.id)}
						<li>
							<a href="/lists/{item.id}">
								<span class="name">{item.name}</span>
								<span class="when muted small">
									{#if item.focused}leading sittings
									{:else if item.focus_until}finished
									{:else}no date{/if}
								</span>
								<span class="count tnum">{item.count}</span>
							</a>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="muted small">No lists yet. Make one for the next test.</p>
			{/if}
			<p><a class="button" href="/lists">Manage lists</a></p>
		</div>
	{/if}

	<div class="card stack manage">
		<h2>Manage</h2>
		{#if !sync.online}
			<p class="muted small">Making and exporting categories needs the laptop.</p>
		{/if}

		<form class="line" onsubmit={create}>
			<label class="what" for="new-path">New category</label>
			<Help label="How a category path works">
				A path makes every level that is missing; the last part is the new category.
			</Help>
			<span class="control">
				<input id="new-path" type="text" bind:value={newPath} placeholder="korean/book1/03-daily-life" />
				<button type="submit" disabled={creating || !newPath.trim() || !sync.online}>Create</button>
			</span>
		</form>

		{#if tree.length}
			<div class="line">
				<span class="what">Export</span>
				<Help label="What export writes">
					Writes the collection as JSON into <code>data/</code>, one folder per category. Nothing is ever deleted.
				</Help>
				<span class="control">
					<button disabled={exporting || !sync.online} onclick={exportTree}>
						{exporting ? 'Exporting…' : 'Export'}
					</button>
				</span>
			</div>
			{#if report}
				<p class="muted small" role="status">
					{report.files.length} file{report.files.length === 1 ? '' : 's'} · {report.notes} notes → <code>{report.root}</code>
				</p>
			{/if}
		{/if}
	</div>
</section>

<style>
	/* The one thing the collection had no way to do: find a word. Full width and
	   first, because every other way in starts by remembering which lesson it was. */
	.find {
		display: flex;
		gap: var(--space-2);
	}

	.find input {
		flex: 1 1 auto;
		min-width: 0;
	}

	.collecting {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		flex-wrap: wrap;
		font-family: var(--font-ui);
		font-size: var(--text-sm);
		color: var(--muted);
	}

	.collecting button {
		margin-left: auto;
	}

	.words {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.list-rows {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.list-rows a {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		padding: var(--space-3) 0;
		min-height: var(--space-8);
		border-bottom: var(--border) solid var(--line-soft);
		color: var(--text);
		text-decoration: none;
	}

	.list-rows .name {
		flex: 1 1 auto;
		min-width: 0;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}

	.list-rows .when,
	.list-rows .count {
		flex: 0 0 auto;
	}

	.titling {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-4);
		flex-wrap: wrap;
		padding-bottom: var(--space-4);
		border-bottom: var(--border-strong) solid var(--text);
	}

	.titling h1 {
		margin: 0;
	}

	.tree {
		margin: 0;
		padding: 0;
	}

	/* Quiet on purpose: it is worth knowing about, not worth alarm. */
	.looked h2 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.findings {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.findings li {
		display: grid;
		gap: var(--space-1);
		padding: var(--space-3) 0;
	}

	.findings li + li {
		border-top: var(--border) solid var(--line-soft);
	}

	/* Prefixed, because `.what` in this file is the Manage card's field label and
	   carries a grid area with it. */
	.finding-kind {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: var(--label-tracking);
		text-transform: uppercase;
		color: var(--muted);
	}

	.finding-words {
		font-size: var(--text-md);
	}

	.finding-fix {
		font-size: var(--text-sm);
		color: var(--muted);
	}

	.finding-where {
		display: flex;
		flex-wrap: wrap;
		gap: 0 var(--space-3);
		font-family: var(--font-ui);
		font-size: var(--text-xs);
	}

	.imports {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.imports li {
		min-height: var(--tap);
		border-bottom: var(--border) solid var(--line-soft);
	}

	.empty {
		padding: var(--space-6) 0;
	}

	/* The things you do rarely, gathered at the foot of the page in one line
	   each, so they are findable without being in the way. */
	.manage {
		margin-top: var(--space-section);
	}

	/* Narrow: the name of the thing, then the thing, on two lines. Wide: one. */
	.line {
		display: grid;
		grid-template-columns: 1fr auto;
		grid-template-areas:
			'what help'
			'control control';
		align-items: center;
		gap: var(--space-2) var(--space-3);
	}

	@media (min-width: 560px) {
		.line {
			grid-template-columns: 9rem 1fr auto;
			grid-template-areas: 'what control help';
		}
	}

	.what {
		grid-area: what;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: var(--label-tracking);
		text-transform: uppercase;
		color: var(--muted);
	}

	.line :global(.help) {
		grid-area: help;
		justify-self: end;
	}

	.control {
		grid-area: control;
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.control input {
		flex: 1 1 auto;
		min-width: 0;
	}
</style>
