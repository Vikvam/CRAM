/**
 * Whether a key press was meant for the page or for something being typed into.
 *
 * Practice binds bare keys — Enter, Space, the digits, Backspace — on `window`,
 * and three components do it at once, so without this a shortcut would fire on
 * every letter of a typed answer. A readonly box is deliberately *not* excluded:
 * the answer field keeps the focus while the verdict is up, and Enter has to go
 * on continuing from there.
 */
export function forPage(event: KeyboardEvent): boolean {
	if (event.ctrlKey || event.metaKey || event.altKey) return false;
	const target = event.target;
	if (!(target instanceof HTMLElement)) return true;
	if (target.isContentEditable) return false;
	if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
		return target.readOnly || target.disabled;
	}
	// A select answers the arrow keys itself, and the setup screen is full of them.
	return !(target instanceof HTMLSelectElement);
}
