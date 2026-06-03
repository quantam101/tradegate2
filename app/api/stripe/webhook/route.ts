/**
 * Stripe Webhook Handler
 * POST /api/stripe/webhook
 *
 * Must be pointed at the PRODUCTION URL:
 *   https://app.alreadyherellc.com/api/stripe/webhook
 *
 * Required env vars:
 *   STRIPE_SECRET_KEY        — sk_live_… (or sk_test_… for test mode)
 *   STRIPE_WEBHOOK_SECRET    — whsec_… from Stripe Dashboard → Webhooks → signing secret
 *
 * Stripe retries on any non-2xx. This handler always returns 200 after
 * signature verification so retries only fire on genuine failures.
 */

import { NextRequest, NextResponse } from 'next/server';
import Stripe from 'stripe';
import fs from 'fs';
import path from 'path';

export const dynamic = 'force-dynamic';

// Stripe requires the raw body for signature verification —
// Next.js 13+ App Router does not parse it automatically, so we read it directly.
export const runtime = 'nodejs';

function getStripe(): Stripe | null {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) return null;
  return new Stripe(key, { apiVersion: '2026-05-27.dahlia' });
}

function appendAuditLog(entry: Record<string, unknown>): void {
  try {
    const logDir = path.join(process.cwd(), 'data', 'logs');
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(
      path.join(logDir, 'audit.jsonl'),
      JSON.stringify({ ...entry, ts: new Date().toISOString() }) + '\n',
    );
  } catch {
    // Non-fatal — never let logging break the webhook response
  }
}

export async function POST(req: NextRequest) {
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;
  const stripeKey = process.env.STRIPE_SECRET_KEY;

  if (!stripeKey || !webhookSecret) {
    appendAuditLog({
      agent: 'stripe-webhook',
      event: 'webhook_misconfigured',
      result: 'fail',
      detail: 'STRIPE_SECRET_KEY or STRIPE_WEBHOOK_SECRET not set',
    });
    // Return 200 so Stripe doesn't retry an ops/config issue
    return NextResponse.json(
      { error: 'Webhook not configured', code: 'missing_env' },
      { status: 200 },
    );
  }

  const stripe = getStripe()!;

  // Read raw body — required for Stripe signature verification
  const rawBody = await req.text();
  const signature = req.headers.get('stripe-signature') ?? '';

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(rawBody, signature, webhookSecret);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    appendAuditLog({
      agent: 'stripe-webhook',
      event: 'signature_verification_failed',
      result: 'fail',
      detail: msg,
    });
    // 400 so Stripe knows this is a bad request (wrong secret / tampered payload)
    return NextResponse.json({ error: `Webhook signature invalid: ${msg}` }, { status: 400 });
  }

  appendAuditLog({
    agent: 'stripe-webhook',
    event: 'webhook_received',
    result: 'ok',
    stripe_event_type: event.type,
    stripe_event_id: event.id,
  });

  // ── Event routing ──────────────────────────────────────────────────────────
  switch (event.type) {
    case 'payment_intent.succeeded': {
      const pi = event.data.object as Stripe.PaymentIntent;
      appendAuditLog({
        agent: 'stripe-webhook',
        event: 'payment_intent.succeeded',
        result: 'ok',
        payment_intent_id: pi.id,
        amount_usd: (pi.amount / 100).toFixed(2),
        currency: pi.currency,
        customer: pi.customer ?? null,
      });
      break;
    }

    case 'payment_intent.payment_failed': {
      const pi = event.data.object as Stripe.PaymentIntent;
      appendAuditLog({
        agent: 'stripe-webhook',
        event: 'payment_intent.payment_failed',
        result: 'fail',
        payment_intent_id: pi.id,
        last_error: pi.last_payment_error?.message ?? null,
      });
      break;
    }

    case 'checkout.session.completed': {
      const session = event.data.object as Stripe.Checkout.Session;
      appendAuditLog({
        agent: 'stripe-webhook',
        event: 'checkout.session.completed',
        result: 'ok',
        session_id: session.id,
        customer_email: session.customer_details?.email ?? null,
        amount_total_usd: session.amount_total != null
          ? (session.amount_total / 100).toFixed(2)
          : null,
      });
      break;
    }

    case 'invoice.paid': {
      const inv = event.data.object as Stripe.Invoice;
      appendAuditLog({
        agent: 'stripe-webhook',
        event: 'invoice.paid',
        result: 'ok',
        invoice_id: inv.id,
        customer: inv.customer ?? null,
        amount_paid_usd: (inv.amount_paid / 100).toFixed(2),
      });
      break;
    }

    case 'invoice.payment_failed': {
      const inv = event.data.object as Stripe.Invoice;
      appendAuditLog({
        agent: 'stripe-webhook',
        event: 'invoice.payment_failed',
        result: 'fail',
        invoice_id: inv.id,
        customer: inv.customer ?? null,
        attempt_count: inv.attempt_count,
      });
      break;
    }

    case 'customer.subscription.deleted':
    case 'customer.subscription.updated':
    case 'customer.subscription.created': {
      const sub = event.data.object as Stripe.Subscription;
      appendAuditLog({
        agent: 'stripe-webhook',
        event: event.type,
        result: 'ok',
        subscription_id: sub.id,
        customer: sub.customer,
        status: sub.status,
      });
      break;
    }

    default:
      appendAuditLog({
        agent: 'stripe-webhook',
        event: 'webhook_unhandled',
        result: 'ok',
        stripe_event_type: event.type,
      });
  }

  // Always return 200 — Stripe will retry on non-2xx
  return NextResponse.json({ received: true, event_type: event.type });
}
