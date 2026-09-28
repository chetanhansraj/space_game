#!/usr/bin/env bash
# Install the Lunar Ark world on a server that ALREADY serves websites with
# nginx and certbot -- without touching them.
#
#   bash /opt/arkgame/deploy/install-nginx.sh [domain]
#
# The pattern is the one such a server already uses for its own apps: the
# game runs as a plain service bound to 127.0.0.1, nginx proxies one new
# server block to it, and the existing certbot issues and renews its
# certificate. What it deliberately does not do:
#
#   - no Docker (no image build on a small CPU, no daemon, no iptables rules)
#   - no change to ports 80/443, the firewall, or any other site's config
#   - no nginx reload unless `nginx -t` passes with the new block in place
#
# The service is capped (60% of one CPU, 600 MB, low priority) so a busy
# game can never starve the sites beside it; it uses about 80 MB running.
# Safe to run again: each step checks whether it is already done.
#
# It never takes over anything it did not create. Everything it writes
# carries the marker below, and before changing anything it refuses if the
# service name, the user, the settings file or the nginx block already
# exist without that marker, or if another service or site uses this
# directory. (The first version used the name "lunarark" -- which is what
# the lunarark.com Codex service on the target server is called. A review
# of the real server caught it before it ran.)
set -euo pipefail

DOMAIN="${1:-play.lunarark.com}"
PORT="${SOLAR_PORT:-8740}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE="${ARKGAME_SERVICE:-arkgame}"
RUNAS="${ARKGAME_USER:-arkgame}"
MARK="Written by the Lunar Ark game installer (arkgame)"
UNIT="/etc/systemd/system/$SERVICE.service"
cd "$HERE"

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m!\033[0m %s\n' "$*"; }
stop() {
  printf '\n\033[1;31m== Stopped: %s\033[0m\n' "$*"
  printf 'Your existing sites are untouched. Copy everything above this line and send it to Claude.\n\n'
  exit 1
}
health() { curl -fsS --max-time 3 "http://127.0.0.1:$PORT/api/health" 2>/dev/null; }
ours() { [ -f "$1" ] && grep -qF "$MARK" "$1"; }
ours_user() { getent passwd "$RUNAS" | cut -d: -f5 | grep -qF "arkgame installer"; }
CHECK_ONLY="${CHECK_ONLY:-0}"

[ "$(id -u)" = 0 ] || stop "this needs to run as root."

# -- 0 -------------------------------------------------------------------------
say "0/8  Making sure nothing here belongs to something else"
for f in api/src/api/server.py sim/src/sim/game.py deploy/install-nginx.sh; do
  [ -f "$f" ] || stop "$HERE does not look like the game's code (no $f). Nothing was changed."
done
grep -q "space_game" .git/config 2>/dev/null \
  || stop "$HERE is not a clone of the space_game repository. Nothing was changed."
ok "$HERE is the game's own clone."
if [ -f "$UNIT" ] && ! ours "$UNIT"; then
  stop "a service called '$SERVICE' already exists and was not made by this installer. Re-run with ARKGAME_SERVICE=<another name> in front."
fi
ok "Service name '$SERVICE' is free (or already ours)."
if id "$RUNAS" >/dev/null 2>&1 && ! ours_user; then
  stop "a user called '$RUNAS' already exists and was not made by this installer. Re-run with ARKGAME_USER=<another name> in front."
fi
ok "User name '$RUNAS' is free (or already ours)."
OTHERS="$(grep -lsF "$HERE" /etc/systemd/system/*.service /lib/systemd/system/*.service 2>/dev/null | grep -vxF "$UNIT" || true)"
[ -z "$OTHERS" ] || stop "$HERE is used by another service: $OTHERS"
NGINX_USERS="$(grep -rlsF "$HERE" /etc/nginx 2>/dev/null || true)"
for f in $NGINX_USERS; do ours "$f" || stop "$HERE is used by nginx config $f"; done
ok "No other service or website uses $HERE."
if [ -f .env ]; then
  ours .env || stop "$HERE/.env exists and was not made by this installer. Nothing was changed."
  grep -qE '^SOLAR_ACCESS_CODE=.+' .env || stop "$HERE/.env has no access code. Nothing was changed."
fi

# -- 1 -------------------------------------------------------------------------
say "1/8  Looking at this server (changing nothing)"
. /etc/os-release 2>/dev/null && ok "System: ${PRETTY_NAME:-unknown}"
ok "CPUs: $(nproc), memory: $(free -m | awk '/^Mem:/{print $2}') MB, swap: $(free -m | awk '/^Swap:/{print $2}') MB, disk free: $(df -h / | awk 'NR==2{print $4}')"
IP="$(curl -fsS4 --max-time 10 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
ok "Public address: $IP"
command -v nginx >/dev/null && systemctl is-active --quiet nginx \
  || stop "nginx is not running here. On a server without nginx, use deploy/install.sh instead."
ok "nginx is running: $(nginx -v 2>&1 | cut -d/ -f2)"
command -v certbot >/dev/null || stop "certbot is not installed, so HTTPS cannot be added the usual way."
ok "certbot is installed."
[ "$(df -Pm "$HERE" | awk 'NR==2{print $4}')" -gt 8000 ] || stop "less than 8 GB of disk is free."
if [ -n "$(ss -ltnH "( sport = :$PORT )" 2>/dev/null || true)" ] && ! health >/dev/null; then
  ss -ltnp "( sport = :$PORT )" || true
  stop "port $PORT is used by something else. Re-run with SOLAR_PORT=<another port> in front."
fi
ok "Port $PORT on 127.0.0.1 is free for the game."

if [ "$CHECK_ONLY" = 1 ]; then
  DNS="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)"
  [ "$DNS" = "$IP" ] && ok "$DOMAIN -> $IP" || warn "$DOMAIN points to '${DNS:-nothing yet}', not $IP."
  printf '\n\033[1;32m== Check passed. Nothing was changed.\033[0m\n'
  printf '   Would create: user %s, service %s (127.0.0.1:%s), %s/.env,\n' "$RUNAS" "$SERVICE" "$PORT" "$HERE"
  printf '   an nginx block for %s, its certificate, and a daily backup in cron.\n\n' "$DOMAIN"
  exit 0
fi

# -- 2 -------------------------------------------------------------------------
say "2/8  Checking that $DOMAIN points here"
while true; do
  DNS="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)"
  if [ "$DNS" = "$IP" ]; then ok "$DOMAIN -> $IP"; break; fi
  warn "$DOMAIN points to '${DNS:-nothing yet}', but this server is $IP."
  warn "Add an A record: Name ${DOMAIN%%.*}, Points to $IP. It can take up to an hour."
  read -r -p "   Press Enter to check again, or type 'skip' to continue without HTTPS for now: " answer
  [ "$answer" = "skip" ] && { warn "Continuing; HTTPS will be added when you re-run this."; break; }
done

# -- 3 -------------------------------------------------------------------------
say "3/8  Installing Python 3.11 and the game, at low priority"
export UV_PYTHON_INSTALL_DIR="$HERE/.python"     # readable by the service user,
export UV_CACHE_DIR="$HERE/.cache/uv"            # unlike anything under /root
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh >/dev/null
fi
ok "uv $(uv --version | cut -d' ' -f2)"
[ -x .venv/bin/python ] || nice -n 19 uv venv --quiet --python 3.11 .venv
nice -n 19 ionice -c3 uv pip install --quiet --python .venv/bin/python \
  -e './orbital[offline]' -e ./market -e ./sim -e ./voice -e ./api
ok "Installed: $(.venv/bin/python --version)"

# -- 4 -------------------------------------------------------------------------
say "4/8  A service account that owns only the world's data"
id "$RUNAS" >/dev/null 2>&1 || useradd --system --home-dir "$HERE" --no-create-home \
  --shell /usr/sbin/nologin --comment "Lunar Ark game (arkgame installer)" "$RUNAS"
mkdir -p data
chown "$RUNAS:$RUNAS" data && chmod 750 data
ok "User '$RUNAS' can write $HERE/data and nothing else."

# -- 5 -------------------------------------------------------------------------
say "5/8  Settings"
if [ -f .env ]; then
  ok "Keeping the existing settings in $HERE/.env"
else
  CODE="ark-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
  cat > .env <<EOF
# $MARK
ARKGAME_SERVICE=$SERVICE
SOLAR_DOMAIN=$DOMAIN
SOLAR_ACCESS_CODE=$CODE
SOLAR_WARMUP_TICKS=168
SOLAR_HOST=127.0.0.1
SOLAR_PORT=$PORT
SOLAR_MIN_FREE_GB=3
EOF
  chmod 640 .env && chown "root:$RUNAS" .env
  ok "Created $HERE/.env"
fi

# -- 6 -------------------------------------------------------------------------
say "6/8  Starting the world as a service"
cat > "$UNIT" <<EOF
# $MARK
[Unit]
Description=Lunar Ark world ($DOMAIN)
After=network.target

[Service]
User=$RUNAS
Group=$RUNAS
WorkingDirectory=$HERE/data
EnvironmentFile=$HERE/.env
Environment=SOLAR_DB=$HERE/data/world.db
Environment=SOLAR_WEB=$HERE/web
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=NUMBA_CACHE_DIR=$HERE/data/.numba
ExecStart=$HERE/.venv/bin/python -m api
Restart=always
RestartSec=5
TimeoutStopSec=20
# A good neighbour on a small shared server.
Nice=10
CPUQuota=60%
MemoryMax=600M
# It may write its own data directory and nothing else.
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$HERE/data

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --quiet "$SERVICE"
systemctl restart "$SERVICE"
printf '   Waiting for the world (a new one first runs a week of history, ~15 s)'
for _ in $(seq 1 60); do health >/dev/null && break; printf '.'; sleep 3; done
echo
health >/dev/null || { journalctl -u "$SERVICE" -n 50 --no-pager; stop "the game did not start."; }
ok "Running on 127.0.0.1:$PORT: $(health)"

# -- 7 -------------------------------------------------------------------------
say "7/8  Adding $DOMAIN to nginx, and its certificate"
if [ -d /etc/nginx/sites-enabled ]; then
  SITE="/etc/nginx/sites-available/$DOMAIN"; LINK="/etc/nginx/sites-enabled/$DOMAIN"
else
  SITE="/etc/nginx/conf.d/$DOMAIN.conf"; LINK=""
fi
if [ -f "$SITE" ] && ! ours "$SITE"; then
  stop "nginx already has a block for $DOMAIN ($SITE) that this installer did not write."
elif [ -f "$SITE" ]; then
  ok "Keeping the nginx block for $DOMAIN written on a previous run."
else
  cat > "$SITE" <<EOF
# $MARK, from $HERE
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 64k;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
EOF
  [ -n "$LINK" ] && ln -sf "$SITE" "$LINK"
  if ! nginx -t 2>/tmp/arkgame-nginx-test; then
    cat /tmp/arkgame-nginx-test
    rm -f "$SITE"; [ -n "$LINK" ] && rm -f "$LINK"
    stop "nginx rejected the new block, so it was removed again and nginx was not reloaded."
  fi
  systemctl reload nginx
  ok "nginx now serves $DOMAIN (the other sites were not touched)."
fi
if grep -q ssl_certificate "$SITE"; then
  ok "HTTPS is already set up for $DOMAIN."
elif [ "${DNS:-}" = "$IP" ]; then
  if certbot --nginx -d "$DOMAIN" --non-interactive --redirect; then
    ok "HTTPS certificate issued; it renews with your other certificates."
  else
    warn "certbot could not issue the certificate. The game works at http://$DOMAIN meanwhile."
  fi
else
  warn "Skipped HTTPS until $DOMAIN points here. Re-run this script then."
fi

# -- 8 -------------------------------------------------------------------------
say "8/8  Daily backups (3 kept, never below 3 GB free)"
LINE="15 4 * * * KEEP=3 $HERE/deploy/backup.sh >> $HERE/data/backup.log 2>&1"
CRON="$(crontab -l 2>/dev/null || true)"
if grep -qF "$HERE/deploy/backup.sh" <<<"$CRON"; then
  ok "Already scheduled."
else
  printf '%s\n%s\n' "$CRON" "$LINE" | sed '/^$/d' | crontab -
  ok "Scheduled every day at 04:15 server time."
fi

. ./.env
SCHEME=http; grep -q ssl_certificate "$SITE" && SCHEME=https
printf '\n\033[1;32m== Done.\033[0m\n\n'
printf '   Play:          %s://%s\n' "$SCHEME" "$DOMAIN"
printf '   Access code:   %s   (people need this to found a company)\n' "$SOLAR_ACCESS_CODE"
printf '   Status:        systemctl status %s    Logs: journalctl -u %s -f\n' "$SERVICE" "$SERVICE"
printf '   Update later:  bash %s/deploy/update-nginx.sh\n\n' "$HERE"
