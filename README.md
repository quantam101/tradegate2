# tradegate2

TradeGate2 is a GMAOS command-center runtime for declarative, local-first trading and operations workflows.

## Production role

This repo is not a passive demo. It is the controlled command-center layer for:

- local-first runtime execution
- approval-gated automation
- cost-guarded inference routes
- audit logging
- security scanning
- operational dashboards
- Docker/OCI deployment paths

## Required verification

Run every gate before deployment:

```bash
npm ci
pip install -r requirements.txt
npm run lint
npm run typecheck
npm run build
npm run test:runtime
npm run security:scan
pip-audit -r requirements.txt
```

## Production standards

- No committed secrets.
- No fake live claims.
- No automatic financial execution without explicit approval gates.
- No non-blocking security failures.
- No deploy unless frontend, runtime, and security checks pass.

## Runtime commands

```bash
npm run dev
npm run healthcheck
```

## Release decision

A release is acceptable only when CI passes, the healthcheck passes, and the deployment target has valid environment variables configured through secret storage.
