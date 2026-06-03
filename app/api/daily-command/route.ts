import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';

export const dynamic = 'force-dynamic';

const ROOT = process.cwd();

function safeReadYaml(rel: string): unknown {
  try {
    return yaml.load(fs.readFileSync(path.join(ROOT, rel), 'utf8'));
  } catch {
    return null;
  }
}

function auditLogTail(n = 20): unknown[] {
  try {
    const logPath = path.join(ROOT, 'data/logs/audit.jsonl');
    if (!fs.existsSync(logPath)) return [];
    return fs
      .readFileSync(logPath, 'utf8')
      .trim()
      .split('\n')
      .slice(-n)
      .map((l) => {
        try {
          return JSON.parse(l);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
  } catch {
    return [];
  }
}

export async function GET() {
  const config = safeReadYaml('eaos.config.yaml') as Record<string, unknown> | null;
  const agents = safeReadYaml('agents/registry.yaml') as Record<string, unknown> | null;
  const recentAudit = auditLogTail(20);

  const systemMode = (config?.system as Record<string, unknown>)?.mode ?? 'unknown';
  const agentList = (agents?.agents as unknown[]) ?? [];

  return NextResponse.json({
    status: 'ok',
    command: 'daily-readiness-check',
    system_mode: systemMode,
    agent_count: agentList.length,
    recent_audit_events: recentAudit.length,
    zero_spend: (config?.runtime as Record<string, unknown>)?.max_cost_usd === 0,
    timestamp: new Date().toISOString(),
  });
}

export async function POST(request: Request) {
  let body: Record<string, unknown> = {};
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }

  const objective = typeof body.objective === 'string' ? body.objective.slice(0, 500) : null;
  if (!objective) {
    return NextResponse.json({ error: 'Missing required field: objective' }, { status: 422 });
  }

  // Local-first: no paid execution — log intent and return declarative receipt
  return NextResponse.json({
    status: 'queued',
    command: 'daily-command',
    objective,
    route: 'local_first',
    spend_usd: 0,
    timestamp: new Date().toISOString(),
  });
}
