import { NextResponse } from 'next/server';

const TF_BASE = (process.env.TOKENFORGE_API_URL || 'https://api.alreadyherellc.com').replace(/\/$/, '');
const TF_API = `${TF_BASE}/proxy/chat`;

export const revalidate = 3600;

export async function GET() {
  const apiKey = process.env.TOKENFORGE_API_KEY;
  if (!apiKey) return NextResponse.json({ ok: false, error: 'TOKENFORGE_API_KEY not set' }, { status: 503 });
  const prompt =
    'You are a status reporter. Reply with ONLY a JSON object (no markdown) with keys: "status" (value: "TOKENFORGE_CONNECTED"), "service" (value: "tradegate-command-center"), "repo" (value: "quantam101/tradegate2"), "message" (one sentence confirming the LLM proxy is live).';
  const started = Date.now();
  let tfResponse: Record<string, unknown> = {};
  let tfOk = false;
  try {
    const res = await fetch(TF_API, {
      method: 'POST',
      headers: { 'X-TF-Key': apiKey, 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, provider: 'anthropic', model: 'claude-haiku-4-5-20251001', max_tokens: 100 }),
    });
    tfResponse = await res.json();
    tfOk = res.ok;
  } catch (err) {
    tfResponse = { error: String(err) };
  }
  return NextResponse.json(
    { ok: tfOk, proof: 'tokenforge_api_live', key_prefix: apiKey.slice(0, 12) + '...', latency_ms: Date.now() - started,
      connector: 'tokenforge_api', repository: 'quantam101/tradegate2', cached_for_seconds: revalidate,
      timestamp: new Date().toISOString(), tokenforge_response: tfResponse },
    { headers: { 'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=60' } },
  );
}
