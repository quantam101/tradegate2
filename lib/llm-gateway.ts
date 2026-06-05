/**
 * LiteLLM Hypervisor Gateway — shared utility for all Next.js API routes.
 * When GATEWAY_URL is set, routes LLM calls through the hypervisor mesh first.
 * Falls back to direct Groq/Gemini calls silently if gateway is unavailable.
 * Zero-cost only: all models are free tier.
 */

const GATEWAY_URL = (process.env.GATEWAY_URL ?? '').replace(/\/$/, '');
const GATEWAY_KEY = process.env.LITELLM_MASTER_KEY ?? '';
const GROQ_KEY    = process.env.GROQ_API_KEY ?? '';
const GEMINI_KEY  = process.env.GEMINI_API_KEY ?? '';

export interface LLMMessage { role: 'system' | 'user' | 'assistant'; content: string; }

export async function llmComplete(
  messages: LLMMessage[],
  maxTokens = 1500,
): Promise<string | null> {
  // 1. Try hypervisor gateway (handles all provider routing internally)
  if (GATEWAY_URL) {
    try {
      const res = await fetch(`${GATEWAY_URL}/v1/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(GATEWAY_KEY ? { Authorization: `Bearer ${GATEWAY_KEY}` } : {}),
        },
        body: JSON.stringify({ model: 'autonomous-intelligence-mesh', messages, max_tokens: maxTokens }),
        signal: AbortSignal.timeout(20_000),
      });
      if (res.ok) {
        const d = await res.json() as { choices: Array<{ message: { content: string } }> };
        return d.choices?.[0]?.message?.content ?? null;
      }
    } catch { /* gateway unavailable — fall through */ }
  }

  // 2. Groq direct (free tier)
  if (GROQ_KEY) {
    try {
      const res = await fetch('https://api.groq.com/openai/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${GROQ_KEY}` },
        body: JSON.stringify({ model: 'llama-3.3-70b-versatile', messages, max_tokens: maxTokens }),
        signal: AbortSignal.timeout(20_000),
      });
      if (res.ok) {
        const d = await res.json() as { choices: Array<{ message: { content: string } }> };
        return d.choices?.[0]?.message?.content ?? null;
      }
    } catch { /* fall through */ }
  }

  // 3. Gemini direct (free tier)
  if (GEMINI_KEY) {
    try {
      const contents = messages.map(m => ({
        role: m.role === 'assistant' ? 'model' : 'user',
        parts: [{ text: m.content }],
      }));
      const res = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${GEMINI_KEY}`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ contents, generationConfig: { maxOutputTokens: maxTokens } }),
          signal: AbortSignal.timeout(20_000) },
      );
      if (res.ok) {
        const d = await res.json() as { candidates: Array<{ content: { parts: Array<{ text: string }> } }> };
        return d.candidates?.[0]?.content?.parts?.[0]?.text ?? null;
      }
    } catch { /* all providers exhausted */ }
  }

  return null;
}
