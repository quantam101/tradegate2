import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import {
  RISK_REVIEW_CHECKLIST,
  validateRobinhoodProposal,
} from '@/lib/robinhood-proposal';
import { requireApiSession } from '@/lib/api-auth';

const DATA_DIR = process.env.GMAOS_DATA_DIR || path.join(process.cwd(), 'data');
const PROPOSALS_PATH = path.join(DATA_DIR, 'robinhood-proposals.jsonl');
const KILL_SWITCH_PATH = path.join(DATA_DIR, 'robinhood-kill-switch.json');

function proposals(): Record<string, unknown>[] {
  try {
    return fs.readFileSync(PROPOSALS_PATH, 'utf8')
      .trim()
      .split('\n')
      .filter(Boolean)
      .map(line => JSON.parse(line) as Record<string, unknown>);
  } catch {
    return [];
  }
}

function killSwitchActive(): boolean {
  if (!fs.existsSync(KILL_SWITCH_PATH)) return false;
  try {
    return Boolean(JSON.parse(fs.readFileSync(KILL_SWITCH_PATH, 'utf8')).active);
  } catch {
    // Unknown emergency-halt state must fail closed.
    return true;
  }
}

export async function GET() {
  const unauthorized = await requireApiSession();
  if (unauthorized) return unauthorized;

  const all = proposals();
  return NextResponse.json({
    mode: 'proposal_only',
    execution_enabled: false,
    kill_switch_active: killSwitchActive(),
    count: all.length,
    dry_run_progress: Math.min(all.length, 30),
    dry_run_target: 30,
    risk_review_checklist: RISK_REVIEW_CHECKLIST,
    proposals: all.slice(-50).reverse(),
  });
}

export async function POST(req: NextRequest) {
  const unauthorized = await requireApiSession();
  if (unauthorized) return unauthorized;
  if (killSwitchActive()) {
    return NextResponse.json(
      { error: 'Robinhood MCP kill switch is active; proposals are halted' },
      { status: 423 },
    );
  }

  const parsed = validateRobinhoodProposal(await req.json().catch(() => ({})));
  if (!parsed.ok) {
    return NextResponse.json({ error: 'invalid proposal', details: parsed.errors }, { status: 422 });
  }

  fs.mkdirSync(DATA_DIR, { recursive: true });
  const record = {
    ...parsed.proposal,
    status: 'proposal_only',
    execution: 'blocked_until_future_explicit_approval',
    risk_review_required: true,
    created_at: new Date().toISOString(),
  };
  fs.appendFileSync(PROPOSALS_PATH, `${JSON.stringify(record)}\n`, 'utf8');

  return NextResponse.json({ ok: true, proposal: record }, { status: 201 });
}
