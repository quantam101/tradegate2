import { NextResponse } from 'next/server';
import { readFileSync } from 'fs';
import { join } from 'path';

export const dynamic = 'force-dynamic';

type HealthChecks = {
  config: boolean;
  registry: boolean;
  agents: boolean;
  env: boolean;
};

function safeRead(file: string): boolean {
  try {
    readFileSync(join(process.cwd(), file), 'utf8');
    return true;
  } catch {
    return false;
  }
}

function hasRuntimeUrl(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SITE_URL ||
      process.env.VERCEL_PROJECT_PRODUCTION_URL ||
      process.env.VERCEL_URL ||
      process.env.URL
  );
}

function hasConnectorCredential(): boolean {
  return Boolean(process.env.TOKENFORGE_API_KEY || process.env.TOKENFORGE_API_URL);
}

export async function GET() {
  const checks: HealthChecks = {
    config: safeRead('eaos.config.yaml'),
    registry: safeRead('connectors/registry.yaml'),
    agents: safeRead('agents/registry.yaml'),
    // Runtime liveness should not fail on Vercel just because optional
    // TokenForge connector credentials are absent. A deployment URL is enough
    // to prove the app has production routing; connector credentials can be
    // reported separately without degrading the web app.
    env: hasRuntimeUrl(),
  };

  const allPass = Object.values(checks).every(Boolean);
  const score = Math.round((Object.values(checks).filter(Boolean).length / Object.keys(checks).length) * 100);

  return NextResponse.json(
    {
      healthScore: score,
      status: allPass ? 'pass' : 'degraded',
      repository: 'quantam101/tradegate2',
      connector: 'tokenforge_api',
      connectorConfigured: hasConnectorCredential(),
      checks,
      timestamp: new Date().toISOString(),
    },
    { status: allPass ? 200 : 207 }
  );
}
