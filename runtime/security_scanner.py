from __future__ import annotations

import re
from pathlib import Path
from typing import List

# Patterns that use simple substring matching (case-insensitive)
_SUBSTRING_MARKERS = ["API_KEY=", "BEGIN PRIVATE KEY", "AWS_SECRET", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]

# Patterns that need word-boundary matching to avoid false positives
# e.g. "sk-" should not match "disk-write"
_REGEX_MARKERS = [re.compile(r'(?<![a-z])sk-', re.IGNORECASE)]


def scan_text(text: str) -> List[str]:
    lowered = text.lower()
    found = [m for m in _SUBSTRING_MARKERS if m.lower() in lowered]
    found += [m.pattern for m in _REGEX_MARKERS if m.search(text)]
    return found


def scan_repo(root: str = ".") -> List[str]:
    findings: List[str] = []
    skip_dirs = {".git", "node_modules", ".next", "__pycache__"}
    skip_files = {"security_scanner.py", "verifier.py", "package-lock.json"}
    for path in Path(root).rglob("*"):
        if not path.is_file() or any(part in skip_dirs for part in path.parts):
            continue
        if path.name in skip_files:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        markers = scan_text(text)
        if markers:
            findings.append(f"{path}: {','.join(markers)}")
    return findings
