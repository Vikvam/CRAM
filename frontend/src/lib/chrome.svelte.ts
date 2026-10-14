/**
 * Whether the app's own furniture should step out of the way.
 *
 * Answering a card is the one thing in this app that wants the whole screen:
 * the header, the bar of places and the skip link all go, so what is left is
 * the question. It is the phase of a session that decides this, not the URL —
 * the screen where a session is set up, and the one where it ends, are ordinary
 * pages and keep their navigation.
 */
class Immersion {
	on = $state(false);
}

export const immersion = new Immersion();
