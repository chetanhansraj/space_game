#!/usr/bin/env bash
# Pull the latest code and restart the game. The world is untouched: it lives
# in ./data, and on restart it catches up on every hour it missed.
set -euo pipefail
cd "$(dirname "$0")/.."
./deploy/backup.sh
git pull --ff-only
if docker compose --profile https ps --services --status running | grep -q caddy; then
  docker compose --profile https up -d --build
else
  docker compose up -d --build
fi
docker image prune -f >/dev/null
echo "Updated. Health: $(curl -fsS http://127.0.0.1:8000/api/health || echo 'starting...')"
