/**
 * Card text is Markdown + KaTeX (PLAN 1). Rendering is the only place markup
 * matters — the answer checker strips it before comparing.
 */
import MarkdownIt from 'markdown-it';
import texmath from 'markdown-it-texmath';
import katex from 'katex';
import 'katex/dist/katex.min.css';

const md = new MarkdownIt({ html: false, linkify: true, breaks: true }).use(texmath, {
	engine: katex,
	delimiters: 'dollars',
	katexOptions: { throwOnError: false }
});

/** Block rendering, for notes and study text. */
export function render(text: string | null | undefined): string {
	return text ? md.render(text) : '';
}

/** Inline rendering, for a card face — no wrapping paragraph. */
export function renderInline(text: string | null | undefined): string {
	return text ? md.renderInline(text) : '';
}

/**
 * The words alone, for a voice to read: no markup, no maths, one space between.
 *
 * Built from the inline tokens rather than by stripping tags off rendered HTML,
 * so `**굵게**` reads as 굵게 and a formula is simply not read.
 */
export function plain(text: string | null | undefined): string {
	if (!text) return '';
	let out = '';
	for (const token of md.parseInline(text, {})[0]?.children ?? []) {
		if (token.type === 'text' || token.type === 'text_special' || token.type === 'code_inline') {
			out += token.content;
		} else if (token.type === 'softbreak' || token.type === 'hardbreak') {
			out += ' ';
		}
	}
	return out.replace(/\s+/g, ' ').trim();
}
