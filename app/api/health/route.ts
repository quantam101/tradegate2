import { NextResponse } from 'next/server';
import { readFileSync } from 'fs';
import { join } from 'path';

export const dynamic = 'force-dynamic';

function safeRead(file: string): boolean {
  try {
    readFileSync(join(process.cwd(), file), 'utf8');
    return true;
  } catch {
    return false;
  }
}

export async function GET() {
  const checks = {
    config: safeRead('eaos.config.yaml'),
    registry: safeRead('connectors/registry.yaml'),
    agents: safeRead('agents/registry.yaml'),
    env: !!(process.env.TOKENFORGE_API_KEY || process.env.NEXT_PUBLIC_SITE_URL),
  };

  const allPass = Object.values(checks).every(Boolean);
  const score = Math.round((Object.values(checks).filter(Boolean).length / Object.keys(checks).length) * 100);

  return NextResponse.json({
    healthScore: score,
    status: allPass ? 'pass' : 'degraded',
    repository: 'quantam101/tradegate2',
    connector: 'tokenforge_api',
    checks,
    timestamp: new Date().toISOString(),
  }, { status: allPass ? 200 : 207 });
}
