// K12: citation display rule (ui/src/utils/citationMarkers.js).
// Reads the same shared case file as tests/unit/test_citation_markers.py.
// Run from the repo root: node --test ui/test/citationMarkers.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normaliseMarkers } from '../src/utils/citationMarkers.js';

const FIX = new URL('../../tests/fixtures/', import.meta.url);
const CASES = JSON.parse(readFileSync(new URL('marker_cases.json', FIX), 'utf8'));
const range = (max) => Array.from({ length: max }, (_, i) => i + 1);

for (const c of CASES) {
  test(c.name, () => {
    assert.equal(normaliseMarkers(c.input, range(c.valid_max)), c.expected);
  });
}

const REAL = [
  ['oq03_run1_answer.json', ['[36-37]'], [['[36-37]', '[36][37]']]],
  ['oq03_run2_answer.json', ['[36(e), 37(e)]', '[36(g)]'],
    [['[36(e), 37(e)]', '[36][37]'], ['[36(g)]', '[36]']]],
  ['oq03_run3_answer.json', ['[11.10(d)]', '[11.10(f)]', '[11.300(b)]'], []],
];

for (const [fname, mustContain, reps] of REAL) {
  test('recorded answer ' + fname, () => {
    const data = JSON.parse(readFileSync(new URL(fname, FIX), 'utf8'));
    for (const m of mustContain) {
      assert.ok(data.answer.includes(m), 'instrument: original marker ' + m + ' not in fixture ' + fname);
    }
    let expected = data.answer;
    for (const [oldS, newS] of reps) expected = expected.split(oldS).join(newS);
    assert.equal(normaliseMarkers(data.answer, range(data.valid_max)), expected);
  });
}
