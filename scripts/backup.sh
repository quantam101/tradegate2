#!/usr/bin/env bash
set -euo pipefail
DEST="${1:-./backups/gmaos-backup-$(date +%Y%m%d-%H%M%S).tgz}"
mkdir -p "$(dirname "$DEST")"
tar -czf "$DEST" agents modules connectors approvals security docs runtime n8n eaos.config.yaml docker-compose.yml README.md
printf 'backup created: %s\n' "$DEST"
