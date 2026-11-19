import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { displayCitations } from '../src/utils/citationDisplay.js';
import { normaliseMarkers } from '../src/utils/citationMarkers.js';

const resp = JSON.parse(fs.readFileSync(new URL('../../tests/fixtures/oq03_run1_response.json', import.meta.url), 'utf8'));
const byChunk = new Map(resp.citations.map((c) => [c.chunk_id, c]));

test('screen number equals the JSON index for every chunk', () => {
  const out = displayCitations(resp);
  assert.equal(out.citations.length, resp.citations.length);
  for (const c of out.citations) {
    assert.equal(c.index, byChunk.get(c.chunk_id).index, 'chunk ' + c.chunk_id);
  }
});

test('no renumbering: displayed index set equals JSON index set', () => {
  const out = displayCitations(resp);
  const shown = out.citations.map((c) => c.index).sort((a, b) => a - b);
  const json = resp.citations.map((c) => c.index).sort((a, b) => a - b);
  assert.deepEqual(shown, json);
});

test('cited sources are listed first, each group in original index order', () => {
  const out = displayCitations(resp);
  const flags = out.citations.map((c) => !!c.cited_by_llm);
  const firstUncited = flags.indexOf(false);
  const nCited = resp.citations.filter((c) => c.cited_by_llm).length;
  assert.equal(firstUncited, nCited);
  const cited = out.citations.slice(0, nCited).map((c) => c.index);
  const unc = out.citations.slice(nCited).map((c) => c.index);
  assert.deepEqual(cited, [...cited].sort((a, b) => a - b));
  assert.deepEqual(unc, [...unc].sort((a, b) => a - b));
});

test('answer markers are not rewritten (original indices kept)', () => {
  const out = displayCitations(resp);
  const orig = resp.answer.match(/\[[^\[\]]*\]/g);
  const now = out.answerText.match(/\[[^\[\]]*\]/g);
  assert.deepEqual(now, orig);
});

test('K12 display rule on the screen expands ranges and lists with original indices', () => {
  const out = displayCitations(resp);
  const valid = out.citations.map((c) => c.index);
  const shown = normaliseMarkers(out.answerText, valid);
  assert.ok(!/\[\d+-\d+\]/.test(shown), 'ranges are expanded');
  assert.ok(shown.includes('[36][37]'), 'range 36-37 is shown as [36][37]');
  assert.ok(!/\[\d+, \d+\]/.test(shown), 'comma lists are expanded');
});

test('empty result passes through', () => {
  const out = displayCitations({ citations: [], answer: '' });
  assert.deepEqual(out, { citations: [], answerText: '' });
});
