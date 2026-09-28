# Running the world on a server

One server runs one world, continuously. These steps put it on a Hostinger VPS
(any Ubuntu VPS works the same way) at **https://play.lunarark.com**.

Why `play.lunarark.com`: lunarark.com is the Moon, and v1 is the Moon, so the
game belongs under its name — but the front page is a research codex with its
own audience, and a subdomain keeps the two apart (VISION.md, open questions).
To use a different address, put it in `SOLAR_DOMAIN` below and in the DNS
record; nothing else changes.

What you need: the VPS's IP address (hPanel → VPS → Overview), its root
password or SSH key, and access to the DNS for lunarark.com.

---

## The easy way

Everything below is done for you by the installer. It runs from Hostinger's
browser terminal, and nothing needs installing on your own computer.

**A. The DNS record.** hPanel → **Domains → lunarark.com → DNS / Nameservers**
→ add an **A** record: Name `play`, Points to *your VPS IP* (hPanel → VPS →
Overview), TTL 3600. Leave every other record alone.

**B. Open the terminal.** hPanel → **VPS → your server → Browser terminal**.

**C. Check first — changes nothing.** This fetches the game into its own
folder, `/opt/arkgame`, and reports whether anything on the server would
collide with it:

```bash
command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq git; }; [ -e /opt/arkgame ] || git clone -q https://github.com/chetanhansraj/space_game.git /opt/arkgame; if [ -f /opt/arkgame/deploy/install-nginx.sh ]; then CHECK_ONLY=1 bash /opt/arkgame/deploy/install-nginx.sh; else echo "/opt/arkgame exists and is not the game. Nothing was changed."; fi
```

It should end with **"Check passed. Nothing was changed."**

**D. Install.**

```bash
bash /opt/arkgame/deploy/install-nginx.sh
```

It finishes by printing the address and the **access code** people need to
join. If anything goes wrong it stops and says so — copy what it printed and
send it to Claude.

### What it will and will not touch

It creates only things named `arkgame`, and every file it writes carries the
line *"Written by the Lunar Ark game installer (arkgame)"*. Before changing
anything it **refuses** if:

- the folder is not a clone of this repository;
- a service or user with its name already exists and it did not make it;
- another service or nginx site already uses its folder;
- a settings file (`.env`) is there that it did not write, or has no access code;
- an nginx block for the domain exists that it did not write.

On a server that already runs websites with nginx — lunarark.com's server
serves lunarark.com and kundali.app — it uses no Docker. The game is a small
service on `127.0.0.1:8740` (about 80 MB of RAM, at most 60% of one CPU, low
priority) running as its own user who can write only `/opt/arkgame/data`.
nginx gets one new block, reloaded only if `nginx -t` passes, and the certbot
that already renews your other certificates adds one more. Ports 80/443, the
firewall and every other site are left as they are.

Backups run daily: three kept, and never taken if they would leave less than
3 GB free. The game also refuses new companies unless an access code is set,
so a missing setting can never leave it open to anyone.

On a server with no web server at all, `deploy/install.sh` uses Docker with
Caddy for HTTPS instead, and hands over to the nginx installer by itself if
it finds nginx.

The rest of this page is what the installer does, step by step, for doing it
by hand or understanding it.

---

## 1. Point the name at the server

In Hostinger hPanel → **Domains → lunarark.com → DNS / Nameservers → Manage DNS
records**, add:

| Type | Name | Points to | TTL |
|---|---|---|---|
| A | `play` | your VPS IP address | 3600 |

Leave every existing record alone — lunarark.com itself keeps working as it is.
If the domain's DNS is managed somewhere else (Cloudflare, another registrar),
add the same record there instead.

It can take a few minutes to an hour to take effect. Check from your own
computer:

```bash
ping play.lunarark.com        # should show your VPS IP
```

## 2. Log in to the server

```bash
ssh root@YOUR_VPS_IP
```

## 3. Install Docker

If the VPS was created from Hostinger's Docker template, skip this. Otherwise:

```bash
curl -fsSL https://get.docker.com | sh
docker compose version        # should print a version
```

Open the firewall for web traffic, if `ufw` is on:

```bash
ufw allow OpenSSH && ufw allow 80 && ufw allow 443
```

## 4. Get the code

The repository is private, so the server needs a read-only key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/space_game -N ""
cat ~/.ssh/space_game.pub
```

Copy the line it prints. On GitHub: **chetanhansraj/space_game → Settings →
Deploy keys → Add deploy key**, paste it, leave *Allow write access* **off**.
Then on the server:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github-space-game
  HostName github.com
  IdentityFile ~/.ssh/space_game
EOF
git clone git@github-space-game:chetanhansraj/space_game.git /opt/arkgame
cd /opt/arkgame
```

## 5. Configure

```bash
cp deploy/env.example .env
nano .env
```

Set `SOLAR_DOMAIN` (default `play.lunarark.com`) and choose an
`SOLAR_ACCESS_CODE` — the invitation code people type to found a company.
Save with Ctrl-O, Enter, Ctrl-X.

## 6. Start the world

**A. The server runs nothing else on ports 80/443** (the usual case for a new
VPS). Caddy fetches the HTTPS certificate on its own:

```bash
docker compose --profile https up -d --build
```

**B. The server already runs nginx for other sites.** Start only the game, then
put it behind the existing nginx:

```bash
docker compose up -d --build
cp deploy/nginx-play.lunarark.com.conf /etc/nginx/sites-available/play.lunarark.com
ln -s /etc/nginx/sites-available/play.lunarark.com /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
apt install -y certbot python3-certbot-nginx && certbot --nginx -d play.lunarark.com
```

The first start builds the image (a few minutes) and then runs one game week of
history — about ten seconds — so the markets have prices before anyone
arrives. Check it:

```bash
curl http://127.0.0.1:8000/api/health     # {"ok":true,"tick":168,"behind":0}
```

Then open **https://play.lunarark.com**.

## 7. Keep it safe

Back up the world every day, keeping two weeks:

```bash
crontab -e
# add this line:
15 4 * * * /opt/arkgame/deploy/backup.sh >> /opt/arkgame/data/backup.log 2>&1
```

Backups land in `data/backups/`. Copy one off the server now and then.

## Updating

```bash
bash /opt/arkgame/deploy/update-nginx.sh     # installed alongside nginx
bash /opt/arkgame/deploy/update.sh           # installed with Docker
```

It backs up, pulls, rebuilds and restarts. The world is untouched — it lives in
`data/` — and when it comes back it runs every hour it missed, because offline
is absent, not paused.

## Looking after it

| | |
|---|---|
| Is it running? | `systemctl status arkgame` (or `docker compose ps` for the Docker install) |
| Logs | `journalctl -u arkgame -f` (or `docker compose logs -f game`) |
| Is it on time? | `curl -s 127.0.0.1:8740/api/health` (8000 for Docker) — `behind` should be 0 |
| Disk | `du -sh data/` — see below |
| Stop / start | `docker compose stop` / `docker compose --profile https up -d` |

**Disk.** The ledger is append-only by design, and the world writes about
**150 MB a day** — every order every firm places is a permanent record. A
50 GB VPS holds several months. That is fine for a playtest, and it is the
first thing to solve before a public launch (DECISIONS.md, D49). Two brakes
protect anything else on the server: backups are skipped rather than taken
when they would leave less than 3 GB free, and below 3 GB free the world
itself stops advancing and reports `"holding_for_disk": true` on its health
check, until space is freed and it catches up (D51).

**Never run two copies against the same `data/`.** One world, one process: a
second one would be a second, diverging world writing into the same ledger.

## Starting over

Only while testing, before anyone real is playing — the world is meant to be
permanent:

```bash
docker compose down && mv data data.old && docker compose --profile https up -d
```
