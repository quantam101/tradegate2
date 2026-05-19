import Link from 'next/link';

const cards = [
  ['Agents', '/command-center/agents', 'Inspect the active declarative agent registry.'],
  ['Modules', '/command-center/modules', 'View enabled modules and disabled placeholders awaiting verified source.'],
  ['Workflows', '/command-center/workflows', 'Launch safe local workflows and queue risky work.'],
  ['Approvals', '/command-center/approvals', 'Review pending approvals before any risky action.'],
  ['Costs', '/command-center/costs', 'Confirm strict zero-spend mode and paid adapter lockout.'],
  ['Security', '/command-center/security', 'Review no-spend, secrets, and production gate posture.'],
  ['Logs', '/command-center/logs', 'Read runtime and audit event status.'],
  ['Connectors', '/command-center/connectors', 'Inspect connector state and disable paid paths.'],
  ['Changelog', '/command-center/changelog', 'Lifelong Catch and Correct correction log.']
];

export default function HomePage() {
  return (
    <main className="shell">
      <span className="badge">GMAOS / EAOS</span>
      <h1>Global Multi-Agent Operating System Command Center</h1>
      <p className="muted">Zero-spend-first, declarative, local-first execution fabric for agentic business automation.</p>
      <div className="grid">
        {cards.map(([title, href, body]) => (
          <Link key={href} href={href} className="card">
            <h2>{title}</h2>
            <p className="muted">{body}</p>
          </Link>
        ))}
      </div>
    </main>
  );
}
