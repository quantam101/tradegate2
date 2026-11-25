'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

type Connector = {
  id: string;
  name?: string;
  state?: string;
  enabled?: boolean;
  permissions?: string[];
  status_url?: string;
  execution_enabled?: boolean;
  proposal_contract?: string;
  notes?: string;
};

type RobinhoodStatus = {
  mode?: string;
  execution_enabled?: boolean;
  kill_switch_active?: boolean;
  count?: number;
  dry_run_progress?: number;
  dry_run_target?: number;
  risk_review_checklist?: string[];
};

export default function Page() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [robinhood, setRobinhood] = useState<RobinhoodStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch('/api/registry').then(r => r.json()),
      fetch('/api/robinhood/proposals').then(r => r.json()).catch(() => null),
    ]).then(([registry, robinhoodStatus]) => {
      setConnectors(registry.connectors ?? []);
      setRobinhood(robinhoodStatus);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const rh = connectors.find(c => c.id === 'robinhood_mcp');

  return (
    <main className="shell">
      <Link className="badge" href="/">Command Center</Link>
      <h1>Connectors</h1>
      <p className="muted">Live connector registry and brokerage proposal controls.</p>

      <section className="card" style={{ padding: 18, marginTop: 20, borderColor: '#f59e0b' }}>
        <div style={{ fontSize: 11, fontFamily: 'monospace', letterSpacing: '.1em', color: '#f59e0b', textTransform: 'uppercase' }}>
          No trade authorization
        </div>
        <h2 style={{ margin: '8px 0 6px' }}>Robinhood MCP is proposal-only</h2>
        <p className="muted" style={{ marginBottom: 0 }}>
          TradeGate can record public-source trade proposals, but it cannot collect credentials,
          submit orders, or enable execution without a future explicit approval.
        </p>
      </section>

      <section className="card" style={{ padding: 18, marginTop: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ margin: 0 }}>Robinhood source status</h2>
            <p className="muted" style={{ marginTop: 6 }}>
              {rh?.notes ?? 'Proposal-only connector contract is loaded from connectors/registry.yaml.'}
            </p>
          </div>
          <div style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: 12 }}>
            <div>mode: {robinhood?.mode ?? rh?.state ?? 'proposal_only'}</div>
            <div>execution: {robinhood?.execution_enabled || rh?.execution_enabled ? 'enabled' : 'blocked'}</div>
            <div>kill switch: {robinhood?.kill_switch_active ? 'active' : 'ready'}</div>
          </div>
        </div>
        <div style={{ marginTop: 12, fontSize: 13 }}>
          Dry-run proposals: <strong>{robinhood?.count ?? 0}</strong> · execution review requires{' '}
          <strong>{robinhood?.dry_run_target ?? 30}</strong> audited proposals.
        </div>
        <ul style={{ marginTop: 12, color: 'var(--muted)', fontSize: 13 }}>
          {(robinhood?.risk_review_checklist ?? []).map(item => <li key={item}>{item}</li>)}
        </ul>
      </section>

      <section style={{ marginTop: 20 }}>
        <h2>Registry</h2>
        {loading && <p className="muted">Loading connector registry…</p>}
        {!loading && connectors.map(connector => (
          <div key={connector.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 18px', marginBottom: 8 }}>
            <div>
              <div style={{ fontWeight: 600 }}>{connector.name ?? connector.id}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--muted)' }}>{connector.id}</div>
              {connector.permissions?.length ? (
                <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                  {connector.permissions.join(' · ')}
                </div>
              ) : null}
            </div>
            <div style={{ textAlign: 'right', fontSize: 12, fontFamily: 'monospace', alignSelf: 'center' }}>
              <div style={{ color: connector.enabled ? '#22c55e' : '#9fb0c6' }}>{connector.enabled ? '● ENABLED' : '○ DISABLED'}</div>
              <div className="muted">{connector.state ?? 'registered'}</div>
            </div>
          </div>
        ))}
        {!loading && !connectors.length && <p className="muted">No connectors registered.</p>}
      </section>
    </main>
  );
}
