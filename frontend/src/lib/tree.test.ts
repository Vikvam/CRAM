import { expect, test } from 'vitest';
import { buildTree, labelBoth } from './tree';

const cat = (id: string, path: string, parent_id: string | null, n = 0) => ({
	id, path, parent_id, slug: path.split('/').at(-1)!, label: null, notes: n, cards: 2 * n, due: 0, new: 2 * n,
	practice: { modes: null, distractor_scope: null },
	practice_resolved: { modes: ['flip', 'typed', 'choice', 'match', 'build'], distractor_scope: 'auto' }
});

test('subtree totals include every descendant', () => {
	const [root] = buildTree([
		cat('k', 'korean', null),
		cat('b', 'korean/book1', 'k', 0),
		cat('l', 'korean/book1/02', 'b', 32),
		cat('m', 'korean/book1/03', 'b', 10)
	]);
	expect(root.totals.notes).toBe(42);
	expect(root.totals.cards).toBe(84);
	expect(root.children[0].children.map((c) => c.category.path)).toEqual(['korean/book1/02', 'korean/book1/03']);
});

test('totals are inventory only — nothing is counted as due or waiting', () => {
	const [root] = buildTree([cat('k', 'korean', null, 5)]);
	expect(Object.keys(root.totals).sort()).toEqual(['cards', 'notes']);
});

test('labels show the native side first', () => {
	expect(labelBoth({ en: 'Countries', ko: '나라' })).toBe('나라 · Countries');
});
