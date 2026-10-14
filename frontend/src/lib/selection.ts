/** Letting you copy the study text out of a tap target, without answering the card.
 *
 *  Text inside a `<button>` cannot be selected unless a style asks for it
 *  (`user-select: text`), and a drag that does select it still fires `click` — so every
 *  tappable answer asks this first. A plain tap leaves no selection and goes through.
 */
export function selecting(target: EventTarget | null): boolean {
	if (!(target instanceof Node) || typeof window === 'undefined') return false;
	const selection = window.getSelection();
	if (!selection || selection.isCollapsed || !selection.toString().trim()) return false;
	// Only a selection made *here* blocks the tap; one left behind elsewhere must not.
	return target.contains(selection.anchorNode) || target.contains(selection.focusNode);
}
