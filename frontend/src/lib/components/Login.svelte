<script lang="ts">
	import { auth } from '$lib/auth.svelte';

	let password = $state('');
	let error = $state<string | null>(null);
	let busy = $state(false);

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		error = null;
		try {
			await auth.login(password);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			password = '';
		} finally {
			busy = false;
		}
	}
</script>

<main>
	<form class="card stack" onsubmit={submit}>
		<h1>CRAM</h1>
		<label class="stack tight">
			<span class="muted">Password</span>
			<!-- svelte-ignore a11y_autofocus -->
			<input type="password" bind:value={password} autocomplete="current-password" autofocus required />
		</label>
		{#if error}<p class="error" role="alert">{error}</p>{/if}
		<button class="primary" type="submit" disabled={busy || !password}>Sign in</button>
	</form>
</main>

<style>
	main {
		display: grid;
		place-items: center;
		min-height: 90vh;
		padding: var(--space-4);
	}

	form {
		width: min(100%, 360px);
	}

	button {
		width: 100%;
	}
</style>
