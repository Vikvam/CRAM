<script lang="ts">
	/** Lessons moved into the drill-down from /progress; an old link lands there. */
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	onMount(() => goto('/progress', { replaceState: true }));
</script>
