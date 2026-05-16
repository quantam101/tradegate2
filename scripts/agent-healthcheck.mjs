import fs from 'node:fs';

const required = [
  'agents/registry.yaml',
  'connectors/registry.yaml',
  'approvals/policy.yaml',
  'security/no-spend-policy.yaml',
  'runtime/sovereign_core.py',
  'docker-compose.yml'
];

const missing = required.filter((path) => !fs.existsSync(path));
if (missing.length) {
  console.error('Missing required files:', missing.join(', '));
  process.exit(1);
}
console.log('agent-healthcheck: ok');
