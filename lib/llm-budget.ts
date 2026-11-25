/** Hard output-token ceiling for LLM calls proxied on behalf of HTTP callers. */
export const MAX_OUTPUT_TOKENS = 1024;
export const DEFAULT_OUTPUT_TOKENS = 256;

/**
 * Resolve a caller-supplied `max_tokens` to an explicit, bounded integer.
 * Returns null when the value is present but not a positive integer.
 */
export function resolveMaxTokens(requested: unknown): number | null {
  if (requested === undefined || requested === null) return DEFAULT_OUTPUT_TOKENS;
  if (typeof requested !== 'number' || !Number.isInteger(requested) || requested < 1) return null;
  return Math.min(requested, MAX_OUTPUT_TOKENS);
}
