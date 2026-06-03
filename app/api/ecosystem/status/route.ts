import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';

export const dynamic = 'force-dynamic';

const ROOT = process.cwd();

function probe(rel: string): { ok: boolean; note?: string } {
  try {
    const stat = fs.statSync(path.join(ROOT, rel));
    return { ok: true, note: `${stat.size}b` };
  } catch {
    return { ok: false };
  }
}

function safeReadYaml(rel: string): unknown {
  try {
    return yaml.load(fs.readFileSync(path.join(ROOT, rel), 'utf8'));
  } catch {
    return null;
  }
}

export async function GET() {
  const config = safeReadYaml('eaos.config.yaml') as Record<string, unknown> | null;
  const agents = safeReadYaml('agents/registry.yaml') as Record<string, unknown> | null;
  const connectors = safeReadYaml('connectors/registry.yaml') as Record<string, unknown> | null;

  const components: Record<string, { status: string; note?: string }> = {
    config:     { status: probe('eaos.config.yaml').ok        ? 'ok' : 'missing' },
    agents:     { status: probe('agents/registry.yaml').ok    ? 'ok' : 'missing' },
    connectors: { status: probe('connectors/registry.yaml').ok ? 'ok' : 'missing' },
    audit_log:  { status: probe('data/logs/audit.jsonl').ok   ? 'ok' : 'absent',
                  note: 'created at first event' },
  };

  const degraded = Object.values(components).some(
    (c) => c.status === 'missing',
  );

  return NextResponse.json({
    status: degraded ? 'degraded' : 'healthy',
    ecosystem: 'GMAOS / EAOS Zero-Spend Fabric',
    version: (config?.system as Record<string, unknown>)?.version ?? '0.1.0',
    mode: (config?.system as Record<string, unknown>)?.mode ?? 'unknown',
    agent_count: ((agents?.agents as unknown[]) ?? []).length,
    connector_count: ((connectors?.connectors as unknown[]) ?? []).length,
    components,
    timestamp: new Date().toISOString(),
  }, { status: degraded ? 207 : 200 });
}
