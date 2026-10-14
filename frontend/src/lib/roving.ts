/**
 * Which tap target the focus moves to next.
 *
 * Every option, tile and piece is a real `<button>` in DOM order, so the arrow
 * keys move the actual focus rather than painting a highlight of their own —
 * which means the one `:focus-visible` ring, the hover styles and every screen
 * reader come along without a line of extra CSS or state.
 *
 * `skip` is "this one is already answered": a paired tile or a placed piece is
 * stepped over rather than focused and found to be dead.
 */
export function next(
	from: number,
	delta: number,
	length: number,
	skip: (index: number) => boolean = () => false
): number {
	if (length <= 0) return -1;
	const step = delta < 0 ? -1 : 1;
	let start: number;
	if (delta === 0) {
		// Staying put, but the row may have got shorter under us.
		start = Math.min(Math.max(from, 0), length - 1);
	} else if (from < 0 || from >= length) {
		// Nothing focused yet: an arrow lands on the near end of the row.
		start = step > 0 ? 0 : length - 1;
	} else {
		start = from + step;
	}
	for (let i = 0; i < length; i += 1) {
		const at = (((start + i * step) % length) + length) % length;
		if (!skip(at)) return at;
	}
	return from; // everything is answered — there is nowhere to go
}
