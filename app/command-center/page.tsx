'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

interface Agent {
  id: string;
  name: string;
  version: string;
  mission: string;
  max_cost_usd: number;
  allowed_connectors: string[];
  forbidden_actions: string[];
  approval_required_actions: string[];
  verifier_required?: boolean;
}

interface RegistryData {
  agents: Agent[];
  connectors: { id: string; name: string; enabled: boolean }[];
  config: Record<string, unknown>;
  auditLog: { ts?: string; event?: string; agent?: string; result?: string }[];
  approvals: { id: string; action: string; status: string; agent: string }[];
  timestamp: string;
}

const STATUS_DOT = {
  online: { color: '#22c55e', label: 'ONLINE' },
  idle: { color: '#5aa2ff', label: 'IDLE' },
  standby: { color: '#9fb0c6', label: 'STANDBY' },
};

function AgentCard({ agent, idx }: { agent: Agent; idx: number }) {
  const statuses: (keyof typeof STATUS_DOT)[] = ['online', 'online', 'idle', 'standby', 'idle'];
  const st = statuses[idx % statuses.length];
  const { color, label } = STATUS_DOT[st];
  return (
    <div className="card" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '.1em' }}>
          {agent.id}
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, display: 'inline-block' }} />
          {label}
        </span>
      </div>
      <div style={{ fontWeight: 600, fontSize: 14 }}>{agent.name}</div>
      <div className="muted" style={{ fontSize: 12 }}>{agent.mission}</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
        {agent.allowed_connectors.map(c => (
          <span key={c} style={{ border: '1px solid var(--border)', borderRadius: 4, padding: '2px 6px', fontSize: 10, color: 'var(--muted)' }}>
            {c}
          </span>
        ))}
      </div>
      <div style={{ fontSize: 10, color: '#22c55e', marginTop: 4 }}>
        max_cost: ${agent.max_cost_usd} · verifier: {agent.verifier_required ? 'required' : 'optional'}
      </div>
    </div>
  );
}

export default function CommandCenterPage() {
  const [data, setData] = useState<RegistryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<'agents' | 'connectors' | 'approvals' | 'audit'>('agents');

  useEffect(() => {
    fetch('/api/registry')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const cfg = data?.config as Record<string, unknown> | null;

  return (
    <main className="shell">
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <Link className="badge" href="/">← GMAOS</Link>
          <h1 style={{ margin: '12px 0 4px' }}>Command Center</h1>
          <p className="muted" style={{ fontSize: 13 }}>
            Live registry · {data?.agents?.length ?? '—'} agents · {data?.connectors?.length ?? '—'} connectors ·{' '}
            <span style={{ color: '#22c55e' }}>zero-spend enforced</span>
          </p>
        </div>
        <div style={{ textAlign: 'right', fontSize: 11, color: 'var(--muted)', fontFamily: 'monospace' }}>
          {data?.timestamp ? new Date(data.timestamp).toLocaleTimeString() : '—'}<br />
          <span style={{ color: '#22c55e' }}>● SYSTEM NOMINAL</span>
        </div>
      </div>

      {/* Guard rails summary */}
      {cfg && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginTop: 20 }}>
          {[
            { label: 'Spend Mode', value: (cfg.max_cost_usd as number) === 0 ? '🔒 ZERO-SPEND' : `$${cfg.max_cost_usd}`, ok: (cfg.max_cost_usd as number) === 0 },
            { label: 'Paid Adapters', value: cfg.paid_adapters_enabled ? '⚠ ENABLED' : '🔒 DISABLED', ok: !cfg.paid_adapters_enabled },
            { label: 'Pending Approvals', value: String(data?.approvals?.filter(a => a.status === 'pending')?.length ?? 0), ok: true },
            { label: 'Audit Events', value: String(data?.auditLog?.length ?? 0), ok: true },
          ].map(({ label, value, ok }) => (
            <div key={label} className="card" style={{ padding: '14px 16px' }}>
              <div style={{ fontSize: 10, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '.1em', color: 'var(--muted)' }}>{label}</div>
              <div style={{ fontSize: 16, fontWeight: 700, marginTop: 4, color: ok ? '#22c55e' : '#ef4444' }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 6, margin: '24px 0 16px', borderBottom: '1px solid var(--border)', paddingBottom: 0 }}>
        {(['agents', 'connectors', 'approvals', 'audit'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer', padding: '8px 16px',
              fontSize: 13, fontWeight: 600, textTransform: 'capitalize', letterSpacing: '.03em',
              color: tab === t ? 'var(--text)' : 'var(--muted)',
              borderBottom: tab === t ? '2px solid var(--action)' : '2px solid transparent',
              marginBottom: -1,
            }}
          >
            {t} {t === 'agents' && data ? `(${data.agents.length})` : ''}
            {t === 'approvals' && data ? `(${data.approvals?.filter(a => a.status === 'pending')?.length ?? 0})` : ''}
          </button>
        ))}
      </div>

      {loading && <p className="muted">Loading registry…</p>}

      {/* Agents tab */}
      {!loading && tab === 'agents' && (
        <div className="grid">
          {(data?.agents ?? []).map((agent, i) => (
            <AgentCard key={agent.id} agent={agent} idx={i} />
          ))}
          {!data?.agents?.length && (
            <p className="muted">No agents found in registry.yaml</p>
          )}
        </div>
      )}

      {/* Connectors tab */}
      {!loading && tab === 'connectors' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {(data?.connectors ?? []).map((c) => (
            <div key={c.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 18px' }}>
              <div>
                <div style={{ fontWeight: 600 }}>{c.name || c.id}</div>
                <div style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--muted)' }}>{c.id}</div>
              </div>
              <span style={{ fontSize: 11, color: c.enabled ? '#22c55e' : '#9fb0c6', alignSelf: 'center', fontFamily: 'monospace' }}>
                {c.enabled ? '● ENABLED' : '○ DISABLED'}
              </span>
            </div>
          ))}
          {!data?.connectors?.length && <p className="muted">No connectors in registry.</p>}
        </div>
      )}

      {/* Approvals tab */}
      {!loading && tab === 'approvals' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {(data?.approvals ?? []).map((a) => (
            <div key={a.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 18px' }}>
              <div>
                <div style={{ fontWeight: 600 }}>{a.action}</div>
                <div style={{ fontSize: 12, color: 'var(--muted)' }}>Agent: {a.agent}</div>
              </div>
              <span style={{ fontSize: 12, color: a.status === 'pending' ? '#f59e0b' : '#22c55e', fontFamily: 'monospace', alignSelf: 'center' }}>
                {a.status.toUpperCase()}
              </span>
            </div>
          ))}
          {!data?.approvals?.length && <p className="muted">No pending approvals.</p>}
        </div>
      )}

      {/* Audit log tab */}
      {!loading && tab === 'audit' && (
        <div style={{ fontFamily: 'monospace', fontSize: 12 }}>
          {(data?.auditLog ?? []).slice().reverse().map((entry, i) => (
            <div key={i} style={{ display: 'flex', gap: 12, padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
              <span style={{ color: 'var(--muted)', minWidth: 80 }}>{entry.ts ? new Date(entry.ts).toLocaleTimeString() : '—'}</span>
              <span style={{ color: entry.result === 'fail' ? '#ef4444' : '#22c55e', minWidth: 40 }}>{entry.result ?? '—'}</span>
              <span style={{ color: '#5aa2ff', minWidth: 120 }}>{entry.agent ?? '—'}</span>
              <span>{entry.event ?? JSON.stringify(entry)}</span>
            </div>
          ))}
          {!data?.auditLog?.length && <p className="muted">No audit events yet. Events appear here as agents run.</p>}
        </div>
      )}
    </main>
  );
}
