#!/usr/bin/env bash
# Put the Lunar Ark world on this server, start to finish.
#
#   bash /opt/lunarark/deploy/install.sh [domain]
#
# Written to be run by someone who has never run a server, from Hostinger's
# browser terminal, as root. It checks everything it can before changing
# anything, says what it is doing in plain words, and stops with a clear
# message rather than guessing. Safe to run again: every step checks whether
# it is already done.
#
# The two things it cannot do itself -- create the DNS record, and add the
# server's key to GitHub -- happen before it runs; see docs/DEPLOY.md.
set -euo pipefail

DOMAIN="${1:-play.lunarark.com}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m!\033[0m %s\n' "$*"; }
stop() {
  printf '\n\033[1;31m== Stopped: %s\033[0m\n' "$*"
  printf 'Nothing is broken. Copy everything above this line and send it to Claude.\n\n'
  exit 1
}

[ "$(id -u)" = 0 ] || stop "this needs to run as root (the browser terminal logs in as root)."

# A server that already serves websites with nginx gets the version that
# leaves them alone: no Docker, no change to ports 80/443, the existing
# certbot. See install-nginx.sh.
if command -v nginx >/dev/null && systemctl is-active --quiet nginx; then
  printf '\nThis server already runs nginx, so your existing sites stay exactly as they are.\n'
  printf 'Switching to the installer made for that: deploy/install-nginx.sh\n'
  exec bash "$HERE/deploy/install-nginx.sh" "$DOMAIN"
fi

# -- 1. the server --------------------------------------------------------------
say "1/7  Looking at this server"
. /etc/os-release 2>/dev/null && ok "System: ${PRETTY_NAME:-unknown}"
ok "Memory: $(free -m | awk '/^Mem:/{print $2}') MB, disk free: $(df -h / | awk 'NR==2{print $4}')"
IP="$(curl -fsS4 --max-time 10 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
ok "Public address: $IP"
[ "$(df -Pm / | awk 'NR==2{print $4}')" -gt 5000 ] || stop "less than 5 GB of disk is free."

# -- 2. the name --------------------------------------------------------------
say "2/7  Checking that $DOMAIN points here"
while true; do
  DNS="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)"
  if [ "$DNS" = "$IP" ]; then ok "$DOMAIN -> $IP"; break; fi
  warn "$DOMAIN points to '${DNS:-nothing yet}', but this server is $IP."
  warn "In Hostinger: Domains -> lunarark.com -> DNS -> add an A record:"
  warn "    Name: ${DOMAIN%%.*}    Points to: $IP    TTL: 3600"
  warn "It can take a few minutes to an hour to take effect."
  read -r -p "   Press Enter to check again, or type 'skip' to continue anyway: " answer
  [ "$answer" = "skip" ] && { warn "Continuing. HTTPS will not work until the record is right."; break; }
done

# -- 3. the ports -------------------------------------------------------------
say "3/7  Checking nothing else is using the web ports"
# Output is captured before it is searched: with pipefail on, 'cmd | grep -q'
# can report failure when grep stops reading early.
RUNNING="$(docker compose ps --services --status running 2>/dev/null || true)"
BUSY="$(ss -ltnH '( sport = :80 or sport = :443 )' 2>/dev/null || true)"
if grep -qx caddy <<<"$RUNNING"; then
  ok "Ports 80/443 are ours already (Caddy is running)."
elif [ -n "$BUSY" ]; then
  ss -ltnp '( sport = :80 or sport = :443 )' || true
  stop "another web server is using port 80 or 443. That is fine, but it needs the other setup (docs/DEPLOY.md, option B)."
else
  ok "Ports 80 and 443 are free."
fi

# -- 4. docker ------------------------------------------------------------------
say "4/7  Installing Docker"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  ok "Already installed: $(docker --version)"
else
  curl -fsSL https://get.docker.com | sh
  docker compose version >/dev/null 2>&1 || stop "Docker installed, but 'docker compose' is missing."
  ok "Installed: $(docker --version)"
fi
systemctl enable --now docker >/dev/null 2>&1 || true

if command -v ufw >/dev/null && grep -q "Status: active" <<<"$(ufw status 2>/dev/null || true)"; then
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
  ok "Firewall: opened 80 and 443."
fi

# -- 5. settings --------------------------------------------------------------
say "5/7  Settings"
if [ -f .env ]; then
  ok "Keeping the existing settings in $HERE/.env"
else
  CODE="ark-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
  cat > .env <<EOF
SOLAR_DOMAIN=$DOMAIN
SOLAR_ACCESS_CODE=$CODE
SOLAR_WARMUP_TICKS=168
EOF
  chmod 600 .env
  ok "Created $HERE/.env"
fi
mkdir -p data

# -- 6. start -----------------------------------------------------------------
say "6/7  Building and starting the world (the first build takes a few minutes)"
docker compose --profile https up -d --build
printf '   Waiting for the world to come up'
for _ in $(seq 1 120); do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then break; fi
  printf '.'; sleep 5
done
echo
HEALTH="$(curl -fsS --max-time 3 http://127.0.0.1:8000/api/health 2>/dev/null || true)"
[ -n "$HEALTH" ] || { docker compose logs --tail 60 game; stop "the game did not start."; }
ok "The world is running: $HEALTH"

printf '   Waiting for the HTTPS certificate'
for _ in $(seq 1 24); do
  if curl -fsS --max-time 5 "https://$DOMAIN/api/health" >/dev/null 2>&1; then break; fi
  printf '.'; sleep 5
done
echo
if curl -fsS --max-time 5 "https://$DOMAIN/api/health" >/dev/null 2>&1; then
  ok "https://$DOMAIN is live."
else
  warn "The game runs, but https://$DOMAIN is not answering yet."
  warn "Usually the DNS record has not reached everyone. Caddy keeps retrying on its own."
  docker compose logs --tail 20 caddy || true
fi

# -- 7. backups ---------------------------------------------------------------
say "7/7  Daily backups"
LINE="15 4 * * * $HERE/deploy/backup.sh >> $HERE/data/backup.log 2>&1"
CRON="$(crontab -l 2>/dev/null || true)"
if grep -qF "$HERE/deploy/backup.sh" <<<"$CRON"; then
  ok "Already scheduled."
else
  printf '%s\n%s\n' "$CRON" "$LINE" | sed '/^$/d' | crontab -
  ok "Scheduled every day at 04:15 server time, kept for 14 days."
fi

# -- done -----------------------------------------------------------------------
. ./.env
printf '\n\033[1;32m== Done.\033[0m\n\n'
printf '   Play:          https://%s\n' "$SOLAR_DOMAIN"
printf '   Access code:   %s   (people need this to found a company)\n' "$SOLAR_ACCESS_CODE"
printf '   Update later:  bash %s/deploy/update.sh\n\n' "$HERE"
