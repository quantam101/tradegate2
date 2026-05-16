#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from runtime.security_scanner import scan_repo
findings = scan_repo('.')
if findings:
    print('Potential secret markers found:')
    for f in findings:
        print(f)
    raise SystemExit(1)
print('security-check: no known secret markers found')
PY
