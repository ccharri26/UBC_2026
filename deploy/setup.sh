#!/usr/bin/env bash
# One-time setup of PennyWise on a fresh Ubuntu 24.04 VM. Safe to re-run.
#
#   git clone https://github.com/ccharri26/UBC_2026.git ~/UBC_2026
#   (copy your .env to ~/UBC_2026/.env from your laptop with scp)
#   bash ~/UBC_2026/deploy/setup.sh pennywise-ubc.centralus.cloudapp.azure.com
#
# Installs uv, Node 22 and Caddy; builds the app; runs uvicorn as the "pennywise"
# service on 127.0.0.1:8000 (one process, one worker: the Runner and the guardrail
# locks live in memory); and puts Caddy in front for HTTPS on the hostname.
# Agent output: journalctl -u pennywise -f
set -euo pipefail

HOST="${1:?usage: setup.sh <hostname, e.g. pennywise-ubc.centralus.cloudapp.azure.com>}"
APP="$(cd "$(dirname "$0")/.." && pwd)"
RUN_AS="$(whoami)"

if [ ! -f "$APP/.env" ]; then
  echo "Missing $APP/.env. From your laptop, run:"
  echo "  scp -i <key.pem> .env $RUN_AS@$HOST:$APP/.env"
  exit 1
fi
chmod 600 "$APP/.env"  # holds the wallet key

echo "== swap (the frontend build needs memory on small VMs)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "== packages"
sudo apt-get update -y
sudo apt-get install -y git curl ca-certificates gnupg debian-keyring debian-archive-keyring apt-transport-https

if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 22 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y caddy
fi

if [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$HOME/.local/bin/uv"

echo "== build"
cd "$APP"
"$UV" sync --frozen
(cd frontend && npm ci && npm run build)
mkdir -p "$APP/data"

echo "== service"
sudo tee /etc/systemd/system/pennywise.service >/dev/null <<EOF
[Unit]
Description=PennyWise API, dashboard and agent
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_AS
WorkingDirectory=$APP
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP/.venv/bin/uvicorn pennywise.api.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable pennywise
sudo systemctl restart pennywise

echo "== https"
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$HOST {
	encode gzip
	reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl enable caddy
sudo systemctl reload caddy || sudo systemctl restart caddy

sleep 3
if curl -fsS http://127.0.0.1:8000/api/health >/dev/null; then
  echo "PennyWise is up: https://$HOST/ (the HTTPS certificate can take a minute the first time)"
else
  echo "The service did not answer. Check: journalctl -u pennywise -n 50"
  exit 1
fi
