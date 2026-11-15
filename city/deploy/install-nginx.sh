#!/usr/bin/env bash
# Put the Lunar Ark city builder on a server that ALREADY serves websites with
# nginx and certbot, without touching them.
#
#   bash /opt/arkgame/city/deploy/install-nginx.sh [domain]
#
# The city builder lives in the city/ folder of the space_game repository, the
# same clone the trade game runs from (/opt/arkgame on the Lunar Ark server).
#
# The game is a static page: two files in dist/. There is no service, no
# database, no user account and no open port. nginx gets one new server block
# that serves dist/ for the domain, and the certbot that already renews the
# other certificates adds one more. What it deliberately does not do:
#
#   - no change to ports 80/443, the firewall, or any other site's config
#   - no nginx reload unless `nginx -t` passes with the new block in place
#   - nothing outside this folder except that one nginx block
#   - nothing of the trade game: not its service, its data, or its nginx block
#
# It never takes over anything it did not create. The nginx block carries the
# marker below, and before changing anything the script refuses if this folder
# is not the game's own clone, if nginx already has a block for the domain
# that it did not write, or if another site or service already uses this
# folder. Safe to run again: each step checks whether it is already done.
#
# CHECK_ONLY=1 in front runs the checks and changes nothing.
set -euo pipefail

DOMAIN="${1:-sim.lunarark.com}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="space_game"
MARK="Written by the Lunar Ark city installer (arksim)"
cd "$HERE"

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m!\033[0m %s\n' "$*"; }
stop() {
  printf '\n\033[1;31m== Stopped: %s\033[0m\n' "$*"
  printf 'Your existing sites are untouched. Copy everything above this line and send it to Claude.\n\n'
  exit 1
}
ours() { [ -f "$1" ] && grep -qF "$MARK" "$1"; }
CHECK_ONLY="${CHECK_ONLY:-0}"

[ "$(id -u)" = 0 ] || stop "this needs to run as root."

# -- 0 -------------------------------------------------------------------------
say "0/4  Making sure nothing here belongs to something else"
for f in dist/index.html dist/game.js deploy/install-nginx.sh src/sim/sim.ts; do
  [ -f "$f" ] || stop "$HERE does not look like the city builder (no $f). Nothing was changed."
done
ROOT="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$ROOT" ] && grep -qi "$REPO" "$ROOT/.git/config" 2>/dev/null \
  || stop "$HERE is not inside a clone of the $REPO repository. Nothing was changed."
ok "$HERE is the city builder, inside the clone at $ROOT."
if [ -d /etc/nginx/sites-enabled ]; then
  SITE="/etc/nginx/sites-available/$DOMAIN"; LINK="/etc/nginx/sites-enabled/$DOMAIN"
else
  SITE="/etc/nginx/conf.d/$DOMAIN.conf"; LINK=""
fi
if [ -f "$SITE" ] && ! ours "$SITE"; then
  stop "nginx already has a block for $DOMAIN ($SITE) that this installer did not write."
fi
CLAIMED="$(grep -rlsE "server_name[^;]*[[:space:]]$DOMAIN([[:space:]]|;)" /etc/nginx 2>/dev/null || true)"
for f in $CLAIMED; do ours "$f" || stop "another nginx config already answers for $DOMAIN: $f"; done
ok "No other nginx block answers for $DOMAIN."
NGINX_USERS="$(grep -rlsF "$HERE" /etc/nginx 2>/dev/null || true)"
for f in $NGINX_USERS; do ours "$f" || stop "$HERE is used by nginx config $f"; done
OTHERS="$(grep -lsF "$HERE" /etc/systemd/system/*.service /lib/systemd/system/*.service 2>/dev/null || true)"
[ -z "$OTHERS" ] || stop "$HERE is used by a service: $OTHERS"
ok "No other website or service uses $HERE."

# -- 1 -------------------------------------------------------------------------
say "1/4  Looking at this server (changing nothing)"
. /etc/os-release 2>/dev/null && ok "System: ${PRETTY_NAME:-unknown}"
IP="$(curl -fsS4 --max-time 10 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
ok "Public address: $IP"
command -v nginx >/dev/null && systemctl is-active --quiet nginx \
  || stop "nginx is not running here. This installer is for a server that already runs nginx."
ok "nginx is running: $(nginx -v 2>&1 | cut -d/ -f2)"
command -v certbot >/dev/null || stop "certbot is not installed, so HTTPS cannot be added the usual way."
ok "certbot is installed."
WEBUSER="$(awk '$1=="user"{gsub(";","",$2); print $2; exit}' /etc/nginx/nginx.conf 2>/dev/null || true)"; WEBUSER="${WEBUSER:-www-data}"
if id "$WEBUSER" >/dev/null 2>&1 && command -v runuser >/dev/null; then
  runuser -u "$WEBUSER" -- test -r "$HERE/dist/index.html" \
    || stop "nginx runs as '$WEBUSER', which cannot read $HERE/dist. Nothing was changed."
  ok "nginx (user $WEBUSER) can read $HERE/dist."
fi
DNS="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)"

if [ "$CHECK_ONLY" = 1 ]; then
  [ "$DNS" = "$IP" ] && ok "$DOMAIN -> $IP" || warn "$DOMAIN points to '${DNS:-nothing yet}', not $IP."
  printf '\n\033[1;32m== Check passed. Nothing was changed.\033[0m\n'
  printf '   Would create: one nginx block for %s serving %s/dist, and its certificate.\n\n' "$DOMAIN" "$HERE"
  exit 0
fi

# -- 2 -------------------------------------------------------------------------
say "2/4  Checking that $DOMAIN points here"
while true; do
  DNS="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)"
  if [ "$DNS" = "$IP" ]; then ok "$DOMAIN -> $IP"; break; fi
  warn "$DOMAIN points to '${DNS:-nothing yet}', but this server is $IP."
  warn "Add an A record: Name ${DOMAIN%%.*}, Points to $IP. It can take up to an hour."
  read -r -p "   Press Enter to check again, or type 'skip' to continue without HTTPS for now: " answer
  [ "$answer" = "skip" ] && { warn "Continuing; HTTPS will be added when you re-run this."; break; }
done

# -- 3 -------------------------------------------------------------------------
say "3/4  Adding $DOMAIN to nginx"
if [ -f "$SITE" ]; then
  ok "Keeping the nginx block for $DOMAIN written on a previous run."
else
  cat > "$SITE" <<CONF
# $MARK, from $HERE
server {
    listen 80;
    server_name $DOMAIN;
    root $HERE/dist;
    index index.html;

    # The game is still in development: ask search engines to leave it out.
    # Delete the next line when it is ready to be found.
    add_header X-Robots-Tag "noindex, nofollow" always;
    # Always fetch the newest build after an update.
    add_header Cache-Control "no-cache" always;

    location / { try_files \$uri \$uri/ =404; }
    location ~ /\. { deny all; }
}
CONF
  [ -n "$LINK" ] && ln -sf "$SITE" "$LINK"
  if ! nginx -t 2>/tmp/arksim-nginx-test; then
    cat /tmp/arksim-nginx-test
    rm -f "$SITE"; [ -n "$LINK" ] && rm -f "$LINK"
    stop "nginx rejected the new block, so it was removed again and nginx was not reloaded."
  fi
  systemctl reload nginx
  ok "nginx now serves $DOMAIN (the other sites were not touched)."
fi

# -- 4 -------------------------------------------------------------------------
say "4/4  HTTPS"
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

SCHEME=http; grep -q ssl_certificate "$SITE" && SCHEME=https
# nginx swaps its workers a moment after a reload, so ask a few times before believing a wrong answer.
CODE=""
for _ in 1 2 3 4 5 6; do
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 --resolve "$DOMAIN:80:127.0.0.1" "http://$DOMAIN/game.js" 2>/dev/null || true)"
  case "$CODE" in 200|301|308) break;; esac
  sleep 1
done
case "$CODE" in
  200|301|308) ok "The server answers for $DOMAIN (HTTP $CODE).";;
  *) warn "The server answered HTTP ${CODE:-nothing} for $DOMAIN/game.js. Send this to Claude.";;
esac
printf '\n\033[1;32m== Done.\033[0m\n\n'
printf '   Play:          %s://%s\n' "$SCHEME" "$DOMAIN"
printf '   Update later:  bash %s/deploy/update.sh\n' "$HERE"
printf '                  (or bash %s/deploy/update-nginx.sh, which updates the trade game as well)\n' "$ROOT"
printf '   Remove:        rm %s %s && systemctl reload nginx\n\n' "$SITE" "$LINK"
