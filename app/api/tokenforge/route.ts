import { NextRequest, NextResponse } from 'next/server';

const TF_API = 'https://api.tokenforge.io/api/proxy/chat';
const TF_STATUS = 'https://api.tokenforge.io/api/status';

export async function POST(req: NextRequest) {
  const apiKey = process.env.TOKENFORGE_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: 'TOKENFORGE_API_KEY not configured' }, { status: 503 });
  }
  const body = await req.json();
  const { prompt, provider = 'anthropic', model = 'claude-haiku-4-5-20251001', max_tokens = 256 } = body;
  if (!prompt) return NextResponse.json({ error: 'prompt is required' }, { status: 400 });
  const res = await fetch(TF_API, {
    method: 'POST',
    headers: { 'X-TF-Key': apiKey, 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, provider, model, max_tokens }),
  });
  return NextResponse.json(await res.json(), { status: res.status });
}

export async function GET() {
  const apiKey = process.env.TOKENFORGE_API_KEY;
  if (!apiKey) return NextResponse.json({ ok: false, error: 'TOKENFORGE_API_KEY not configured' }, { status: 503 });
  try {
    const res = await fetch(TF_STATUS, { headers: { 'X-TF-Key': apiKey }, next: { revalidate: 30 } });
    return NextResponse.json({ ok: res.ok, key_prefix: apiKey.slice(0, 12) + '...', ...(await res.json()) });
  } catch {
    return NextResponse.json({ ok: false, error: 'tokenforge unreachable' }, { status: 503 });
  }
}
