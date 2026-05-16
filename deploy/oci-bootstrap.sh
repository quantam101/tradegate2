#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/gmaos"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root or with sudo."
  exit 1
fi

apt-get update -y
apt-get install -y ca-certificates curl git ufw fail2ban unzip jq python3 python3-venv python3-pip

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

mkdir -p "$APP_DIR" /opt/gmaos-data/{logs,backups,uploads,vector-store,models}
chown -R "$SUDO_USER:${SUDO_USER:-root}" "$APP_DIR" /opt/gmaos-data || true

echo "Bootstrap complete. Copy repo to $APP_DIR, configure .env server-side, then run: docker compose up -d --build"
