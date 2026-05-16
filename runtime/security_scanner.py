from __future__ import annotations

from pathlib import Path
from typing import List

SECRET_MARKERS = ["sk-", "API_KEY=", "BEGIN PRIVATE KEY", "AWS_SECRET", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]


def scan_text(text: str) -> List[str]:
    lowered = text.lower()
    return [marker for marker in SECRET_MARKERS if marker.lower() in lowered]


def scan_repo(root: str = ".") -> List[str]:
    findings: List[str] = []
    for path in Path(root).rglob("*"):
        if not path.is_file() or any(part in {".git", "node_modules", ".next"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        markers = scan_text(text)
        if markers:
            findings.append(f"{path}: {','.join(markers)}")
    return findings
