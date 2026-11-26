export const TOKENFORGE_DEFAULT_OUTPUT_TOKENS = 256;
export const TOKENFORGE_MAX_OUTPUT_TOKENS = 1024;

/** Output-token budget for the proxy: callers may lower it, never exceed the cap. */
export function clampMaxTokens(requested: unknown): number {
  if (typeof requested !== 'number' || !Number.isFinite(requested) || requested < 1) {
    return TOKENFORGE_DEFAULT_OUTPUT_TOKENS;
  }
  return Math.min(Math.floor(requested), TOKENFORGE_MAX_OUTPUT_TOKENS);
}
