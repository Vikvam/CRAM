<script lang="ts">
	/** What "known" and "mastered" take — the thresholds come from the server. */
	import type { Progress } from '$lib/api/client';
	import { LADDER } from '$lib/progress';
	import Help from '$lib/components/Help.svelte';

	let { rule }: { rule: Progress['rule'] } = $props();
</script>

<Help label="What counts as known and mastered">
	<p>
		A word is <strong>known</strong> once you have earned {rule.known_points} points on it and got
		{rule.rate_percent}% of its last {rule.rate_window} answers right, over at least {rule.min_reviews} answers.
	</p>
	<p>
		It is <strong>mastered</strong> at {rule.mastered_points} points, {rule.writing_points} of which have to come
		from typing the answer — recognising a word is not the same as writing it. Those points also have to be
		earned over at least {rule.spread_hours} hours: a word you can still produce an hour later is not yet a word
		you have kept.
	</p>
	<ul>
		{#each LADDER as step (step.points)}
			<li><strong>{step.points}</strong> — {step.what}</li>
		{/each}
	</ul>
	<p>
		A word asked both ways counts once, and only as far as its weaker way round. Points are kept for good, but a
		word you start getting wrong slips back down.
	</p>
	<p>A word marked −1 counts once it is known, until everything else is mastered — then it has to be mastered too.</p>
</Help>
