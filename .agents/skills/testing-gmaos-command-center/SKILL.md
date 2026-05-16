---
name: testing-gmaos-command-center
description: Test the GMAOS Enterprise command center scaffold end-to-end. Use when verifying Next.js UI pages, Python EAOS runtime, or navigation after merging or updating the GMAOS scaffold.
---

# Testing GMAOS Command Center

## Prerequisites

- Node.js and npm installed
- Python 3.x with `pyyaml` and `pytest` installed
- Run `npm install` in the project root

## Shell Tests (run first, no browser needed)

### Python Runtime Smoke Test
```bash
python3 -m runtime.sovereign_core
```
Expect: exit code 0, output contains `status='ok'`

### Python Unit Tests
```bash
python3 -m pytest tests/test_core.py -q
```
Expect: `2 passed`

**Important:** Use `python3 -m pytest` (not bare `pytest`) — bare pytest fails with `ModuleNotFoundError: No module named 'runtime'` because the project root isn't on sys.path.

### ESLint
```bash
npx eslint . --max-warnings=0
```
Expect: 0 errors, 0 warnings

### TypeScript
```bash
npx tsc --noEmit
```
Expect: 0 type errors

## Browser UI Tests

### Start Dev Server
```bash
npx next dev -p 3000
```
Wait for "Ready in Xms" message.

### Homepage (http://localhost:3000)
Verify:
- Tab title: "GMAOS Command Center"
- Badge: "GMAOS / EAOS" visible at top
- Heading: "Global Multi-Agent Operating System Command Center"
- Exactly 9 card links: Agents, Modules, Workflows, Approvals, Costs, Security, Logs, Connectors, Changelog
- Dark theme (dark blue/navy background)

### Command Center Pages
For each of these 9 pages at `/command-center/{slug}`:
- agents, modules, workflows, approvals, costs, security, logs, connectors, changelog

Verify:
- h1 heading matches page name
- "COMMAND CENTER" badge visible and links back to `/`
- Scaffold JSON block visible with: `"status": "scaffold"`, `"mode": "strict_zero_spend"`, `"paidAdapters": "disabled"`
- Description text "Merge-ready scaffold page" visible

### Badge Navigation
- Click "COMMAND CENTER" badge from any subpage
- Should return to homepage with all 9 cards

## Known Issues / Tips

- The `Caddyfile` and `docker-compose.yml` may reference `alreadyherellc.com` — these need updating per project before deployment
- `package.json` may have `"name": "gmaos-command-center"` — consider renaming per project
- The security scanner (`runtime/security_scanner.py`) skips its own source files and `verifier.py` to avoid false positives. If scanner logic is refactored into different files, update the `skip_files` set.
- When running multiple GMAOS repos simultaneously, use different ports (e.g., `-p 3000`, `-p 3001`)
- Next.js may auto-modify `tsconfig.json` on first dev server start — this is expected and can be ignored
