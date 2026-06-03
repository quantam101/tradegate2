/**
 * WorkMarket / ADP Payment Account Status
 * GET /api/workmarket/status
 *
 * WorkMarket (now part of ADP) does not publish a public REST API for
 * account/payment verification — all account actions go through the
 * WorkMarket web UI at https://www.workmarket.com or the ADP admin portal.
 *
 * This endpoint:
 *  1. Confirms whether the WorkMarket connector env vars are present
 *  2. Returns the direct verification URLs for a human to confirm account health
 *  3. Logs the check to the audit log
 *  4. Returns actionable instructions if anything is missing
 */

import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export const dynamic = 'force-dynamic';

function appendAuditLog(entry: Record<string, unknown>): void {
  try {
    const logDir = path.join(process.cwd(), 'data', 'logs');
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(
      path.join(logDir, 'audit.jsonl'),
      JSON.stringify({ ...entry, ts: new Date().toISOString() }) + '\n',
    );
  } catch { /* non-fatal */ }
}

export async function GET() {
  const wmToken = process.env.WORKMARKET_API_TOKEN ?? '';
  const wmCompanyId = process.env.WORKMARKET_COMPANY_ID ?? '';
  const adpClientId = process.env.ADP_CLIENT_ID ?? '';

  const tokenPresent = wmToken.length > 0;
  const companyIdPresent = wmCompanyId.length > 0;
  const adpPresent = adpClientId.length > 0;

  const warnings: string[] = [];
  if (!tokenPresent) {
    warnings.push(
      'WORKMARKET_API_TOKEN is not set. ' +
      'Obtain from WorkMarket → Settings → API Access.',
    );
  }
  if (!companyIdPresent) {
    warnings.push(
      'WORKMARKET_COMPANY_ID is not set. ' +
      'Find it in WorkMarket → Company Settings → Company ID.',
    );
  }

  appendAuditLog({
    agent: 'workmarket-status',
    event: 'account_status_check',
    result: warnings.length === 0 ? 'ok' : 'degraded',
    token_present: tokenPresent,
    company_id_present: companyIdPresent,
    adp_present: adpPresent,
  });

  return NextResponse.json({
    status: warnings.length === 0 ? 'configured' : 'action_required',
    connector: 'workmarket_adp',
    token_present: tokenPresent,
    company_id_present: companyIdPresent,
    adp_client_id_present: adpPresent,

    // ── Manual verification steps ────────────────────────────────────────────
    // WorkMarket has no public health-check API endpoint.
    // These are the canonical URLs to verify account and payment status directly.
    verification_urls: {
      workmarket_dashboard: 'https://www.workmarket.com/dashboard',
      workmarket_payments:  'https://www.workmarket.com/payments',
      workmarket_bank_accounts: 'https://www.workmarket.com/settings/banking',
      adp_marketplace:      'https://apps.adp.com',
      adp_run_payroll:      'https://run.adp.com',
    },
    verification_checklist: [
      'Log in at workmarket.com → Payments → confirm bank account is verified and not frozen.',
      'Check workmarket.com → Payments → Pending/Processing to confirm no stuck disbursements.',
      'If using ADP integration: log in at run.adp.com → confirm payroll account active.',
      'Confirm no outstanding WorkMarket compliance holds (Settings → Compliance).',
      'Confirm payment method on file is not expired (Settings → Banking → Payment Methods).',
    ],
    env_vars_required: {
      WORKMARKET_API_TOKEN: tokenPresent ? '✓ set' : '✗ missing',
      WORKMARKET_COMPANY_ID: companyIdPresent ? '✓ set' : '✗ missing',
      ADP_CLIENT_ID: adpPresent ? '✓ set' : '— optional',
    },
    warnings,
    timestamp: new Date().toISOString(),
  }, { status: warnings.length === 0 ? 200 : 207 });
}
