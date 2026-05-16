#!/usr/bin/env bash
set -euo pipefail
SRC="${1:?Usage: restore.sh backup.tgz}"
tar -xzf "$SRC" -C .
printf 'restore completed from: %s\n' "$SRC"
