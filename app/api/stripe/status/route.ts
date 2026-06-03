/**
 * Stripe Integration Status
 * GET /api/stripe/status
 *
 * Returns:
 *  - Whether STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are present
 *  - Whether the key is live vs test mode
 *  - The correct production webhook URL this app expects
 *  - Last 10 stripe webhook audit events from the local audit log
 *  - Actionable warnings if anything is misconfigured
 */

import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export const dynamic = 'force-dynamic';

const PRODUCTION_WEBHOOK_URL = `${
  process.env.NEXT_PUBLIC_SITE_URL ?? 'https://app.alreadyherellc.com'
}/api/stripe/webhook`;

function readStripeAuditEvents(n = 10): unknown[] {
  try {
    const logPath = path.join(process.cwd(), 'data', 'logs', 'audit.jsonl');
    if (!fs.existsSync(logPath)) return [];
    return fs
      .readFileSync(logPath, 'utf8')
      .trim()
      .split('\n')
      .map((l) => { try { return JSON.parse(l); } catch { return null; } })
      .filter((e): e is Record<string, unknown> => !!e && e.agent === 'stripe-webhook')
      .slice(-n);
  } catch {
    return [];
  }
}

export async function GET() {
  const secretKey = process.env.STRIPE_SECRET_KEY ?? '';
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET ?? '';

  const keyPresent = secretKey.startsWith('sk_');
  const webhookSecretPresent = webhookSecret.startsWith('whsec_');
  const isLiveMode = secretKey.startsWith('sk_live_');
  const isTestMode = secretKey.startsWith('sk_test_');

  const warnings: string[] = [];

  if (!keyPresent) {
    warnings.push('STRIPE_SECRET_KEY is not set. Set it in Vercel environment variables.');
  }
  if (!webhookSecretPresent) {
    warnings.push(
      'STRIPE_WEBHOOK_SECRET is not set. ' +
      'Get it from Stripe Dashboard → Developers → Webhooks → your endpoint → Signing secret.',
    );
  }
  if (keyPresent && !isLiveMode && !isTestMode) {
    warnings.push('STRIPE_SECRET_KEY does not look like a valid Stripe key (should start with sk_live_ or sk_test_).');
  }
  if (isTestMode) {
    warnings.push(
      'STRIPE_SECRET_KEY is a TEST key (sk_test_…). ' +
      'Payments will NOT process real money. Switch to sk_live_ for production.',
    );
  }

  const recentEvents = readStripeAuditEvents(10);
  const lastEvent = recentEvents.at(-1) as Record<string, unknown> | undefined;

  return NextResponse.json({
    status: warnings.length === 0 ? 'healthy' : 'degraded',
    stripe_configured: keyPresent && webhookSecretPresent,
    mode: isLiveMode ? 'live' : isTestMode ? 'test' : 'unconfigured',
    key_prefix: keyPresent ? secretKey.slice(0, 14) + '…' : null,
    webhook_secret_present: webhookSecretPresent,
    expected_webhook_url: PRODUCTION_WEBHOOK_URL,
    webhook_instruction:
      'In Stripe Dashboard → Developers → Webhooks, ensure the endpoint URL is set to ' +
      `"${PRODUCTION_WEBHOOK_URL}" (not a preview/branch URL). ` +
      'Select events: payment_intent.succeeded, payment_intent.payment_failed, ' +
      'checkout.session.completed, invoice.paid, invoice.payment_failed, ' +
      'customer.subscription.*',
    recent_webhook_events: recentEvents,
    last_event_at: lastEvent?.ts ?? null,
    warnings,
    timestamp: new Date().toISOString(),
  }, { status: warnings.length === 0 ? 200 : 207 });
}
