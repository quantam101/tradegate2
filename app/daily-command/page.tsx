'use client';

import { useEffect, useState } from 'react';

interface DailyCommandStatus {
  status: string;
  command: string;
  system_mode: string;
  agent_count: number;
  recent_audit_events: number;
  zero_spend: boolean;
  timestamp: string;
}

export default function DailyCommandPage() {
  const [data, setData] = useState<DailyCommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [objective, setObjective] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [receipt, setReceipt] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    fetch('/api/daily-command')
      .then((r) => r.json())
      .then(setData)
      .catch(() => setError('Failed to reach /api/daily-command'));
  }, []);

  async function handleSubmit() {
    if (!objective.trim()) return;
    setSubmitting(true);
    setReceipt(null);
    try {
      const r = await fetch('/api/daily-command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ objective }),
      });
      setReceipt(await r.json());
      setObjective('');
    } catch {
      setReceipt({ error: 'Submission failed' });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-8 font-mono">
      <h1 className="text-2xl font-bold mb-2">⚙️ Daily Command</h1>
      <p className="text-zinc-400 mb-8 text-sm">Local-first execution fabric · zero-spend mode</p>

      {error && (
        <div className="bg-red-900/40 border border-red-700 rounded p-4 mb-6 text-red-300 text-sm">
          {error}
        </div>
      )}

      {data && (
        <section className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3">
          {[
            ['Status',       data.status],
            ['System Mode',  data.system_mode],
            ['Agents',       String(data.agent_count)],
            ['Audit Events', String(data.recent_audit_events)],
            ['Zero Spend',   data.zero_spend ? '✅ yes' : '⚠️ no'],
            ['As of',        new Date(data.timestamp).toLocaleTimeString()],
          ].map(([label, value]) => (
            <div key={label} className="bg-zinc-900 border border-zinc-800 rounded p-3">
              <div className="text-zinc-500 text-xs mb-1">{label}</div>
              <div className="text-zinc-100 text-sm font-semibold">{value}</div>
            </div>
          ))}
        </section>
      )}

      <section className="bg-zinc-900 border border-zinc-800 rounded p-6 mb-6">
        <h2 className="text-sm font-semibold text-zinc-300 mb-4">Submit Objective</h2>
        <textarea
          className="w-full bg-zinc-800 border border-zinc-700 rounded p-3 text-sm text-zinc-100 placeholder-zinc-500 resize-none focus:outline-none focus:border-zinc-500"
          rows={3}
          placeholder="Describe the analytical objective…"
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
        />
        <button
          onClick={handleSubmit}
          disabled={submitting || !objective.trim()}
          className="mt-3 px-4 py-2 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm font-medium transition-colors"
        >
          {submitting ? 'Queuing…' : 'Queue Command'}
        </button>
      </section>

      {receipt && (
        <section className="bg-zinc-900 border border-zinc-700 rounded p-4">
          <h2 className="text-xs text-zinc-400 mb-2">Receipt</h2>
          <pre className="text-xs text-green-400 overflow-auto whitespace-pre-wrap">
            {JSON.stringify(receipt, null, 2)}
          </pre>
        </section>
      )}
    </main>
  );
}
