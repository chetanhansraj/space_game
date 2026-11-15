#!/usr/bin/env bash
# Update the city builder installed with install-nginx.sh. The built game is
# in the repository (city/dist), and nginx serves it straight from this clone,
# so an update is one pull and nothing needs restarting.
#
# The clone is shared with the trade game. If the update also changes the
# trade game's code, this script changes nothing and points to the trade
# game's own updater, which backs up the world, reinstalls and restarts it.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
grep -rqsF "Lunar Ark city installer (arksim)" /etc/nginx \
  || { echo "No city builder installed by city/deploy/install-nginx.sh here. Nothing was changed."; exit 1; }
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git fetch --quiet origin "$BRANCH"
CHANGED="$(git diff --name-only HEAD FETCH_HEAD)"
if [ -z "$CHANGED" ]; then echo "Already up to date."; exit 0; fi
OTHER="$(grep -vE '^(city/|docs/|README\.md$)' <<<"$CHANGED" || true)"
if [ -n "$OTHER" ]; then
  echo "This update also changes the trade game:"
  sed 's/^/   /' <<<"$OTHER" | head -10
  echo "Nothing was changed. Update both games together with:"
  echo "   bash $ROOT/deploy/update-nginx.sh"
  exit 1
fi
BEFORE="$(git rev-parse --short HEAD)"
git merge --ff-only --quiet FETCH_HEAD
echo "Updated: $BEFORE -> $(git rev-parse --short HEAD). Players get the new build on their next page load."
