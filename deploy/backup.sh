#!/usr/bin/env bash
# A consistent copy of the live world, taken without stopping it (SQLite's
# online backup), kept for 14 days. Run daily from cron:
#   15 4 * * * /opt/lunarark/deploy/backup.sh >> /opt/lunarark/data/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/backups
stamp=$(date -u +%Y%m%d-%H%M%S)
docker compose exec -T game python - "$stamp" <<'PY'
import sqlite3, sys
src = sqlite3.connect("/data/world.db")
dst = sqlite3.connect(f"/data/backups/world-{sys.argv[1]}.db")
src.backup(dst)
dst.close()
PY
gzip "data/backups/world-$stamp.db"
find data/backups -name 'world-*.db.gz' -mtime +14 -delete
echo "$(date -u) backup world-$stamp.db.gz $(du -h "data/backups/world-$stamp.db.gz" | cut -f1)"
