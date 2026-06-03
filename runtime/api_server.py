"""
GMAOS Runtime HTTP Gateway
Serves on :8080 so Caddy can reverse-proxy api.{SITE_DOMAIN} to runtime:8080.

Endpoints
---------
GET  /health              — liveness + readiness probe
GET  /daily-command       — daily readiness summary
POST /daily-command       — queue a local-first objective (returns declarative receipt)
GET  /ecosystem/status    — component health map
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("gmaos.api")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _probe(rel: str) -> bool:
    return (ROOT / rel).exists()


def _safe_read_yaml(rel: str) -> Any:
    try:
        import yaml  # type: ignore
        return yaml.safe_load((ROOT / rel).read_text())
    except Exception:
        return None


def _audit_tail(n: int = 20) -> list:
    log_path = ROOT / "data" / "logs" / "audit.jsonl"
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text().strip().split("\n")[-n:]
        result = []
        for l in lines:
            try:
                result.append(json.loads(l))
            except Exception:
                pass
        return result
    except Exception:
        return []


def _json(obj: Any) -> bytes:
    return json.dumps(obj, default=str).encode()


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def handle_health() -> tuple[int, Any]:
    config = _safe_read_yaml("eaos.config.yaml") or {}
    checks = {
        "config":     _probe("eaos.config.yaml"),
        "agents":     _probe("agents/registry.yaml"),
        "connectors": _probe("connectors/registry.yaml"),
        "env":        bool(os.getenv("NEXT_PUBLIC_SITE_URL") or os.getenv("SITE_DOMAIN")),
    }
    passed = sum(checks.values())
    total = len(checks)
    score = round(passed / total * 100)
    all_pass = passed == total
    system = config.get("system", {}) or {}
    return (200 if all_pass else 207), {
        "healthScore": score,
        "status": "pass" if all_pass else "degraded",
        "runtime": "gmaos-python",
        "version": system.get("version", "0.1.0"),
        "checks": checks,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def handle_daily_command_get() -> tuple[int, Any]:
    config = _safe_read_yaml("eaos.config.yaml") or {}
    agents = _safe_read_yaml("agents/registry.yaml") or {}
    audit = _audit_tail(20)
    system = config.get("system", {}) or {}
    runtime = config.get("runtime", {}) or {}
    return 200, {
        "status": "ok",
        "command": "daily-readiness-check",
        "system_mode": system.get("mode", "unknown"),
        "agent_count": len(agents.get("agents", []) or []),
        "recent_audit_events": len(audit),
        "zero_spend": runtime.get("max_cost_usd", 0) == 0,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def handle_daily_command_post(body: Dict[str, Any]) -> tuple[int, Any]:
    objective = body.get("objective", "")
    if not isinstance(objective, str) or not objective.strip():
        return 422, {"error": "Missing required field: objective"}
    return 200, {
        "status": "queued",
        "command": "daily-command",
        "objective": objective[:500],
        "route": "local_first",
        "spend_usd": 0,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def handle_ecosystem_status() -> tuple[int, Any]:
    config = _safe_read_yaml("eaos.config.yaml") or {}
    agents = _safe_read_yaml("agents/registry.yaml") or {}
    connectors = _safe_read_yaml("connectors/registry.yaml") or {}
    system = config.get("system", {}) or {}

    components = {
        "config":     {"status": "ok" if _probe("eaos.config.yaml")         else "missing"},
        "agents":     {"status": "ok" if _probe("agents/registry.yaml")      else "missing"},
        "connectors": {"status": "ok" if _probe("connectors/registry.yaml")  else "missing"},
        "audit_log":  {"status": "ok" if _probe("data/logs/audit.jsonl")     else "absent",
                       "note": "created at first event"},
    }
    degraded = any(c["status"] == "missing" for c in components.values())
    return (207 if degraded else 200), {
        "status": "degraded" if degraded else "healthy",
        "ecosystem": "GMAOS / EAOS Zero-Spend Fabric",
        "version": system.get("version", "0.1.0"),
        "mode": system.get("mode", "unknown"),
        "agent_count": len(agents.get("agents", []) or []),
        "connector_count": len(connectors.get("connectors", []) or []),
        "components": components,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class GMAOSHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # silence default logger
        logger.info("%s - - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: Any) -> None:
        payload = _json(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path in ("/health", ""):
            status, body = handle_health()
        elif path == "/daily-command":
            status, body = handle_daily_command_get()
        elif path == "/ecosystem/status":
            status, body = handle_ecosystem_status()
        else:
            status, body = 404, {"error": "not found", "path": path}
        self._send(status, body)

    def do_POST(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path == "/daily-command":
            body = self._read_body()
            status, resp = handle_daily_command_post(body)
        else:
            status, resp = 404, {"error": "not found", "path": path}
        self._send(status, resp)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    port = int(os.getenv("RUNTIME_PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), GMAOSHandler)
    logger.info("GMAOS runtime API listening on :%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
