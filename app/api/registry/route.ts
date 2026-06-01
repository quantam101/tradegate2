import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';

const ROOT = process.cwd();

function safeRead(rel: string) {
  try {
    const raw = fs.readFileSync(path.join(ROOT, rel), 'utf8');
    return yaml.load(raw);
  } catch {
    return null;
  }
}

export async function GET() {
  const agents = safeRead('agents/registry.yaml');
  const connectors = safeRead('connectors/registry.yaml');
  const config = safeRead('eaos.config.yaml');

  // Read audit log tail (last 50 entries)
  let auditLog: unknown[] = [];
  try {
    const logPath = path.join(ROOT, 'data/logs/audit.jsonl');
    if (fs.existsSync(logPath)) {
      const lines = fs.readFileSync(logPath, 'utf8').trim().split('\n').slice(-50);
      auditLog = lines.map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
    }
  } catch { /* no audit log yet */ }

  // Read approvals
  let approvals: unknown[] = [];
  try {
    const approvalsPath = path.join(ROOT, 'data/approvals.json');
    if (fs.existsSync(approvalsPath)) {
      approvals = JSON.parse(fs.readFileSync(approvalsPath, 'utf8'));
    }
  } catch { /* no approvals yet */ }

  return NextResponse.json({
    agents: (agents as Record<string, unknown>)?.agents ?? [],
    connectors: (connectors as Record<string, unknown>)?.connectors ?? [],
    config,
    auditLog,
    approvals,
    timestamp: new Date().toISOString(),
  });
}
