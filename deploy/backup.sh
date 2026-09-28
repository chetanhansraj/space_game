#!/usr/bin/env bash
# A consistent copy of the live world, taken without stopping it (SQLite's
# online backup), compressed, keeping only the newest $KEEP copies.
#
# The world grows by roughly 150 MB a real day (DECISIONS.md D49), so backups
# are the fastest way to fill a shared disk. Two guards:
#   - only $KEEP copies are kept (default 3), newest first;
#   - if taking one would leave less than SOLAR_MIN_FREE_GB free (default 3),
#     it is skipped and says so, rather than filling the disk.
#
# Run daily from cron; install.sh and install-nginx.sh schedule it.
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP="${KEEP:-3}"
MIN_GB="${SOLAR_MIN_FREE_GB:-3}"
DB=data/world.db
[ -f "$DB" ] || { echo "$(date -u) no world at $DB, nothing to back up"; exit 0; }
mkdir -p data/backups

size_kb=$(du -k "$DB" | cut -f1)
free_kb=$(df -Pk data | awk 'NR==2{print $4}')
need_kb=$(( ${MIN_GB%.*} * 1000000 + size_kb ))
if [ "$free_kb" -lt "$need_kb" ]; then
  echo "$(date -u) SKIPPED: $((free_kb / 1000)) MB free, a backup needs" \
       "$((size_kb / 1000)) MB and ${MIN_GB} GB must stay free"
  exit 1
fi

stamp=$(date -u +%Y%m%d-%H%M%S)
out="data/backups/world-$stamp.db"
if [ -x .venv/bin/python ]; then
  # Installed as a service (install-nginx.sh): back up the file directly.
  .venv/bin/python - "$DB" "$out" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
PY
else
  # Running in Docker (install.sh): back up from inside the container.
  docker compose exec -T game python - "/data/backups/world-$stamp.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect("/data/world.db"); dst = sqlite3.connect(sys.argv[1])
src.backup(dst); dst.close(); src.close()
PY
fi
gzip "$out"
ls -1t data/backups/world-*.db.gz | tail -n +"$((KEEP + 1))" | xargs -r rm --
echo "$(date -u) backup world-$stamp.db.gz $(du -h "$out.gz" | cut -f1)," \
     "keeping $(ls -1 data/backups/world-*.db.gz | wc -l)"
