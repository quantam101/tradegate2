'use client';

import { useEffect, useState } from 'react';

interface StripeStatus {
  status: string;
  stripe_configured: boolean;
  mode: string;
  key_prefix: string | null;
  webhook_secret_present: boolean;
  expected_webhook_url: string;
  webhook_instruction: string;
  recent_webhook_events: Record<string, unknown>[];
  last_event_at: string | null;
  warnings: string[];
  timestamp: string;
}

interface WorkMarketStatus {
  status: string;
  token_present: boolean;
  company_id_present: boolean;
  adp_client_id_present: boolean;
  verification_urls: Record<string, string>;
  verification_checklist: string[];
  env_vars_required: Record<string, string>;
  warnings: string[];
  timestamp: string;
}

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontSize: 11, fontFamily: 'monospace', fontWeight: 700,
      color: ok ? '#22c55e' : '#ef4444',
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: ok ? '#22c55e' : '#ef4444', display: 'inline-block' }} />
      {label}
    </span>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: 'var(--card, #0f1117)', border: '1px solid var(--border, #1e2130)',
      borderRadius: 8, padding: 20, ...style,
    }}>
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 10, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '.1em', color: 'var(--muted, #6b7280)', marginBottom: 12 }}>
      {children}
    </div>
  );
}

export default function PaymentsPage() {
  const [stripe, setStripe] = useState<StripeStatus | null>(null);
  const [wm, setWm] = useState<WorkMarketStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch('/api/stripe/status').then(r => r.json()).catch(() => null),
      fetch('/api/workmarket/status').then(r => r.json()).catch(() => null),
    ]).then(([s, w]) => {
      setStripe(s);
      setWm(w);
      setLoading(false);
    });
  }, []);

  return (
    <main style={{ padding: '32px 24px', maxWidth: 900, margin: '0 auto', fontFamily: 'system-ui, sans-serif', color: 'var(--text, #e2e8f0)' }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>💳 Payment Integrations</h1>
        <p style={{ margin: '6px 0 0', fontSize: 13, color: 'var(--muted, #6b7280)' }}>
          Stripe webhook health · WorkMarket / ADP account status
        </p>
      </div>

      {loading && <p style={{ color: 'var(--muted, #6b7280)' }}>Loading payment status…</p>}

      {/* ── Stripe ── */}
      {stripe && (
        <div style={{ marginBottom: 28 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Stripe</h2>
            <StatusBadge ok={stripe.status === 'healthy'} label={stripe.status.toUpperCase()} />
            {stripe.mode !== 'unconfigured' && (
              <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: stripe.mode === 'live' ? '#14532d' : '#713f12', color: stripe.mode === 'live' ? '#22c55e' : '#fbbf24', fontFamily: 'monospace' }}>
                {stripe.mode.toUpperCase()} MODE
              </span>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 16 }}>
            {[
              { label: 'Secret Key', value: stripe.key_prefix ?? '✗ not set', ok: !!stripe.key_prefix },
              { label: 'Webhook Secret', value: stripe.webhook_secret_present ? '✓ set' : '✗ not set', ok: stripe.webhook_secret_present },
              { label: 'Fully Configured', value: stripe.stripe_configured ? 'YES' : 'NO', ok: stripe.stripe_configured },
              { label: 'Last Event', value: stripe.last_event_at ? new Date(stripe.last_event_at).toLocaleString() : 'none yet', ok: true },
            ].map(({ label, value, ok }) => (
              <Card key={label} style={{ padding: '12px 16px' }}>
                <div style={{ fontSize: 10, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '.1em', color: 'var(--muted, #6b7280)', marginBottom: 4 }}>{label}</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: ok ? '#e2e8f0' : '#ef4444' }}>{value}</div>
              </Card>
            ))}
          </div>

          <Card style={{ marginBottom: 14 }}>
            <SectionTitle>Webhook Endpoint (must match Stripe Dashboard)</SectionTitle>
            <code style={{ display: 'block', fontSize: 12, padding: '8px 12px', background: '#0a0d14', borderRadius: 4, border: '1px solid #1e2130', color: '#22c55e', wordBreak: 'break-all' }}>
              {stripe.expected_webhook_url}
            </code>
            <p style={{ margin: '10px 0 0', fontSize: 12, color: 'var(--muted, #6b7280)', lineHeight: 1.6 }}>
              {stripe.webhook_instruction}
            </p>
          </Card>

          {stripe.warnings.length > 0 && (
            <Card style={{ border: '1px solid #7c2d12', background: '#1c0a05', marginBottom: 14 }}>
              <SectionTitle>⚠ Action Required</SectionTitle>
              {stripe.warnings.map((w, i) => (
                <div key={i} style={{ fontSize: 12, color: '#fca5a5', marginBottom: 6, paddingLeft: 8, borderLeft: '2px solid #ef4444' }}>{w}</div>
              ))}
            </Card>
          )}

          {stripe.recent_webhook_events.length > 0 && (
            <Card>
              <SectionTitle>Recent Webhook Events</SectionTitle>
              <div style={{ fontFamily: 'monospace', fontSize: 11 }}>
                {stripe.recent_webhook_events.slice().reverse().map((e, i) => (
                  <div key={i} style={{ display: 'flex', gap: 12, padding: '5px 0', borderBottom: '1px solid #1e2130' }}>
                    <span style={{ color: '#6b7280', minWidth: 130 }}>{e.ts ? new Date(e.ts as string).toLocaleTimeString() : '—'}</span>
                    <span style={{ color: e.result === 'ok' ? '#22c55e' : '#ef4444', minWidth: 40 }}>{String(e.result ?? '—')}</span>
                    <span style={{ color: '#60a5fa' }}>{String(e.stripe_event_type ?? e.event ?? '—')}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* ── WorkMarket / ADP ── */}
      {wm && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>WorkMarket / ADP</h2>
            <StatusBadge ok={wm.status === 'configured'} label={wm.status.replace('_', ' ').toUpperCase()} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 16 }}>
            {Object.entries(wm.env_vars_required).map(([k, v]) => (
              <Card key={k} style={{ padding: '12px 16px' }}>
                <div style={{ fontSize: 10, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '.08em', color: '#6b7280', marginBottom: 4 }}>{k}</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: v.startsWith('✓') ? '#22c55e' : v.startsWith('—') ? '#6b7280' : '#ef4444' }}>{v}</div>
              </Card>
            ))}
          </div>

          {wm.warnings.length > 0 && (
            <Card style={{ border: '1px solid #7c2d12', background: '#1c0a05', marginBottom: 16 }}>
              <SectionTitle>⚠ Action Required</SectionTitle>
              {wm.warnings.map((w, i) => (
                <div key={i} style={{ fontSize: 12, color: '#fca5a5', marginBottom: 6, paddingLeft: 8, borderLeft: '2px solid #ef4444' }}>{w}</div>
              ))}
            </Card>
          )}

          <Card style={{ marginBottom: 16 }}>
            <SectionTitle>Manual Verification Checklist</SectionTitle>
            {wm.verification_checklist.map((step, i) => (
              <div key={i} style={{ display: 'flex', gap: 10, marginBottom: 8, fontSize: 12 }}>
                <span style={{ color: '#6b7280', minWidth: 18 }}>{i + 1}.</span>
                <span style={{ color: '#cbd5e1', lineHeight: 1.5 }}>{step}</span>
              </div>
            ))}
          </Card>

          <Card>
            <SectionTitle>Direct Verification Links</SectionTitle>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {Object.entries(wm.verification_urls).map(([label, url]) => (
                <a key={label} href={url} target="_blank" rel="noopener noreferrer"
                  style={{ fontSize: 12, color: '#60a5fa', textDecoration: 'none', display: 'flex', justifyContent: 'space-between', padding: '6px 10px', background: '#0a0d14', borderRadius: 4, border: '1px solid #1e2130' }}>
                  <span style={{ color: '#94a3b8' }}>{label.replace(/_/g, ' ')}</span>
                  <span>{url}</span>
                </a>
              ))}
            </div>
          </Card>
        </div>
      )}
    </main>
  );
}
