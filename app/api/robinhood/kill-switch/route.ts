import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

const DATA_DIR = path.join(process.cwd(), 'data');
const KILL_SWITCH_PATH = path.join(DATA_DIR, 'robinhood-kill-switch.json');

function state() {
  try {
    return JSON.parse(fs.readFileSync(KILL_SWITCH_PATH, 'utf8')) as {
      active?: boolean;
      reason?: string;
      updated_at?: string;
    };
  } catch {
    return { active: false };
  }
}

export async function GET() {
  return NextResponse.json({ connector: 'robinhood_mcp', ...state() });
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { active?: unknown; reason?: unknown };
  const active = body.active === true;
  const reason = typeof body.reason === 'string' && body.reason.trim()
    ? body.reason.trim().slice(0, 500)
    : active ? 'manual safety halt' : 'manual reset';
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const record = {
    connector: 'robinhood_mcp',
    active,
    reason,
    updated_at: new Date().toISOString(),
  };
  fs.writeFileSync(KILL_SWITCH_PATH, JSON.stringify(record, null, 2), 'utf8');
  return NextResponse.json({ ok: true, ...record });
}
