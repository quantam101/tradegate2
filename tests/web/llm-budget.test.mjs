import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { DEFAULT_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS, resolveMaxTokens } from '../../lib/llm-budget.ts';

test('missing max_tokens gets the explicit default', () => {
  assert.equal(resolveMaxTokens(undefined), DEFAULT_OUTPUT_TOKENS);
  assert.equal(resolveMaxTokens(null), DEFAULT_OUTPUT_TOKENS);
});

test('caller-supplied max_tokens is capped', () => {
  assert.equal(resolveMaxTokens(64), 64);
  assert.equal(resolveMaxTokens(MAX_OUTPUT_TOKENS), MAX_OUTPUT_TOKENS);
  assert.equal(resolveMaxTokens(1_000_000), MAX_OUTPUT_TOKENS);
});

test('non positive-integer max_tokens is rejected', () => {
  for (const bad of [0, -5, 1.5, '4096', true, Number.NaN, Number.POSITIVE_INFINITY, {}]) {
    assert.equal(resolveMaxTokens(bad), null);
  }
});

test('tokenforge proxy route forwards only the bounded max_tokens', () => {
  const src = readFileSync(new URL('../../app/api/tokenforge/route.ts', import.meta.url), 'utf8');
  assert.match(src, /resolveMaxTokens\(/);
  assert.doesNotMatch(src, /max_tokens\s*=\s*256/);
});
