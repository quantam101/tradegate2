import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  TOKENFORGE_DEFAULT_OUTPUT_TOKENS,
  TOKENFORGE_MAX_OUTPUT_TOKENS,
  clampMaxTokens,
} from '../../app/api/tokenforge/budget.ts';

test('caller cannot exceed the output-token cap', () => {
  assert.equal(clampMaxTokens(1_000_000), TOKENFORGE_MAX_OUTPUT_TOKENS);
  assert.equal(clampMaxTokens(TOKENFORGE_MAX_OUTPUT_TOKENS + 1), TOKENFORGE_MAX_OUTPUT_TOKENS);
});

test('caller may request less than the cap', () => {
  assert.equal(clampMaxTokens(64), 64);
  assert.equal(clampMaxTokens(64.9), 64);
});

test('missing or invalid values fall back to the default', () => {
  for (const v of [undefined, null, '5000', 0, -1, Number.NaN, Number.POSITIVE_INFINITY, {}]) {
    assert.equal(clampMaxTokens(v), TOKENFORGE_DEFAULT_OUTPUT_TOKENS);
  }
});

test('the route sends the clamped budget upstream', async () => {
  const { readFile } = await import('node:fs/promises');
  const src = await readFile(new URL('../../app/api/tokenforge/route.ts', import.meta.url), 'utf8');
  assert.match(src, /max_tokens: clampMaxTokens\(body\.max_tokens\)/);
});

test('the route targets the live zero-cost proxy and defaults to free providers', async () => {
  const { readFile } = await import('node:fs/promises');
  const src = await readFile(new URL('../../app/api/tokenforge/route.ts', import.meta.url), 'utf8');
  assert.match(src, /app\.alreadyherellc\.com/);
  assert.match(src, /`\/api\/tokenforge`/);
  assert.match(src, /provider = 'auto'/);
  assert.doesNotMatch(src, /claude-haiku/);
  assert.doesNotMatch(src, /\/proxy\/chat/);
});
