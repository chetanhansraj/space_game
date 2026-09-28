#!/usr/bin/env bash
# Update a world installed with install-nginx.sh: back up, pull, reinstall,
# restart. The world lives in data/ and is untouched; on restart it runs
# every hour it missed.
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_PYTHON_INSTALL_DIR="$PWD/.python" UV_CACHE_DIR="$PWD/.cache/uv"
. ./.env
SERVICE="${ARKGAME_SERVICE:-arkgame}"
grep -qF "Lunar Ark game installer" "/etc/systemd/system/$SERVICE.service" \
  || { echo "No game service '$SERVICE' installed by install-nginx.sh here. Nothing was changed."; exit 1; }
KEEP=3 ./deploy/backup.sh || echo "Backup skipped or failed; updating anyway (the previous backups are kept)."
git pull --ff-only
nice -n 19 ionice -c3 uv pip install --quiet --python .venv/bin/python \
  -e './orbital[offline]' -e ./market -e ./sim -e ./voice -e ./api
systemctl restart "$SERVICE"
for _ in $(seq 1 30); do
  curl -fsS --max-time 3 "http://127.0.0.1:${SOLAR_PORT}/api/health" && { echo; echo "Updated."; exit 0; }
  sleep 2
done
journalctl -u "$SERVICE" -n 40 --no-pager
echo "The world did not come back up. Send the lines above to Claude."
exit 1
