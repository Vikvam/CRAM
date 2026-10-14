import { expect, test } from 'vitest';
import { diff } from './diff';

test('one wrong syllable is one unit', () => {
	expect(diff('학샘', '학생')).toEqual([
		{ text: '학', kind: 'same' },
		{ text: '샘', kind: 'extra' },
		{ text: '생', kind: 'missing' }
	]);
});

test('a missing letter is marked missing', () => {
	expect(diff('Rusia', 'Russia')).toEqual([
		{ text: 'Rus', kind: 'same' },
		{ text: 's', kind: 'missing' },
		{ text: 'ia', kind: 'same' }
	]);
});

test('case is not a mistake', () => {
	expect(diff('russia', 'Russia')).toEqual([{ text: 'Russia', kind: 'same' }]);
});
