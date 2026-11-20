#!/usr/bin/env bash
# Pull the latest main, rebuild and restart. Restarting ends any active Run.
#   bash ~/UBC_2026/deploy/update.sh
set -euo pipefail
APP="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP"
git pull --ff-only
"$HOME/.local/bin/uv" sync --frozen
(cd frontend && npm ci && npm run build)
sudo systemctl restart pennywise
echo "updated to $(git log --oneline -1)"
