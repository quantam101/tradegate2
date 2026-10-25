import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { requireApiSession } from '@/lib/api-auth';

const DATA_DIR = process.env.GMAOS_DATA_DIR || path.join(process.cwd(), 'data');
const KILL_SWITCH_PATH = path.join(DATA_DIR, 'robinhood-kill-switch.json');

function state() {
  if (!fs.existsSync(KILL_SWITCH_PATH)) return { active: false };
  try {
    return JSON.parse(fs.readFileSync(KILL_SWITCH_PATH, 'utf8')) as {
      active?: boolean;
      reason?: string;
      updated_at?: string;
    };
  } catch {
    // Match proposal submission semantics: unreadable halt state fails closed.
    return { active: true, reason: 'kill_switch_state_unreadable_fail_closed' };
  }
}

export async function GET() {
  const unauthorized = await requireApiSession();
  if (unauthorized) return unauthorized;
  return NextResponse.json({ connector: 'robinhood_mcp', ...state() });
}

export async function POST(req: NextRequest) {
  const unauthorized = await requireApiSession();
  if (unauthorized) return unauthorized;

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
