import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { check, pieces } from './index.ts';

interface Vector {
	answer: string;
	expected: string;
	accepted: string[];
	outcome: string;
	why: string;
}

const spec = JSON.parse(
	readFileSync(new URL('../../../spec/answer-check.vectors.json', import.meta.url), 'utf8')
) as { vectors: Vector[] };

for (const v of spec.vectors) {
	test(`${JSON.stringify(v.answer)} vs ${JSON.stringify(v.expected)} → ${v.outcome} (${v.why})`, () => {
		assert.equal(check(v.answer, v.expected, v.accepted).outcome, v.outcome);
	});
}

test('build tiles: words when there are several', () => {
	assert.deepEqual(pieces('만나서 반가워요'), ['만나서', '반가워요']);
});

test('build tiles: one per syllable block in Hangul', () => {
	assert.deepEqual(pieces('러시아'), ['러', '시', '아']);
});

test('build tiles: one per grapheme, so accents stay on their letter', () => {
	assert.deepEqual(pieces('café'), ['c', 'a', 'f', 'é']);
	assert.deepEqual(pieces('cafe\u0301'), ['c', 'a', 'f', '\u00e9'], 'tiles come out in NFC');
});

test('the closest accepted answer is reported for the diff', () => {
	const result = check('whcih', 'what, which', ['what', 'which']);
	assert.equal(result.closest, 'which');
	assert.equal(result.distance, 1);
});
