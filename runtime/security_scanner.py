from __future__ import annotations

import re
from pathlib import Path
from typing import List

# Patterns that use simple substring matching (case-insensitive). These are
# intentionally broad because this scanner is a repository guardrail, not a UI
# redactor. False positives are cheaper than committed brokerage secrets.
_SUBSTRING_MARKERS = [
    "API_KEY=",
    "BEGIN PRIVATE KEY",
    "AWS_SECRET",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "ROBINHOOD_TOKEN",
    "ROBINHOOD_ACCESS_TOKEN",
    "ROBINHOOD_REFRESH_TOKEN",
    "BROKERAGE_TOKEN",
    "BROKERAGE_ACCOUNT_ID",
    "ACCOUNT_ID=",
    "ACCOUNT_NUMBER=",
]

# Patterns that need word-boundary matching to avoid false positives.
_REGEX_MARKERS = [
    re.compile(r"(?<![a-z])sk-", re.IGNORECASE),
    re.compile(r"\b(?:rh|robinhood)[_-]?(?:access|refresh)?[_-]?token\b\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(?:brokerage|robinhood)[_-]?account[_-]?(?:id|number)\b\s*[:=]", re.IGNORECASE),
    re.compile(r"\baccount[_-]?(?:id|number)\b\s*[:=]\s*[0-9]{6,}", re.IGNORECASE),
]

# File types that must never be committed because they commonly contain raw
# brokerage account identifiers, balances, positions, or statement exports.
_BLOCKED_FILE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".heic",
    ".pdf",
    ".csv",
    ".xlsx",
    ".xls",
}

_BLOCKED_NAME_MARKERS = (
    "statement",
    "statements",
    "screenshot",
    "screen-shot",
    "brokerage-export",
    "brokerage_export",
    "account-export",
    "account_export",
    "robinhood-export",
    "robinhood_export",
)

_ALLOWED_BLOCKED_SUFFIX_DIRS = {"docs", "fixtures", "tests"}


def scan_text(text: str) -> List[str]:
    lowered = text.lower()
    found = [m for m in _SUBSTRING_MARKERS if m.lower() in lowered]
    found += [m.pattern for m in _REGEX_MARKERS if m.search(text)]
    return found


def _scan_file_name(path: Path) -> List[str]:
    lowered_name = path.name.lower()
    findings: List[str] = []
    if any(marker in lowered_name for marker in _BLOCKED_NAME_MARKERS):
        findings.append("blocked_statement_or_screenshot_filename")
    if path.suffix.lower() in _BLOCKED_FILE_SUFFIXES and any(marker in lowered_name for marker in _BLOCKED_NAME_MARKERS):
        findings.append("blocked_brokerage_export_filetype")
    return findings


def scan_repo(root: str = ".") -> List[str]:
    findings: List[str] = []
    skip_dirs = {".git", "node_modules", ".next", "__pycache__"}
    skip_files = {"security_scanner.py", "verifier.py", "package-lock.json"}
    for path in Path(root).rglob("*"):
        if not path.is_file() or any(part in skip_dirs for part in path.parts):
            continue
        if path.name in skip_files:
            continue

        name_markers = _scan_file_name(path)
        if name_markers and not any(part in _ALLOWED_BLOCKED_SUFFIX_DIRS for part in path.parts):
            findings.append(f"{path}:{','.join(name_markers)}")

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        markers = scan_text(text)
        if markers:
            findings.append(f"{path}: {','.join(markers)}")
    return findings
