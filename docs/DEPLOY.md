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

## The easy way: two pastes

Everything below is done for you by `deploy/install.sh`. You only need three
things from Hostinger's website, and nothing installed on your own computer.

**A. The DNS record.** hPanel → **Domains → lunarark.com → DNS / Nameservers**
→ add an **A** record: Name `play`, Points to *your VPS IP* (hPanel → VPS →
Overview), TTL 3600. Leave every other record alone.

**B. Open the terminal.** hPanel → **VPS → your server → Browser terminal**
(it logs you in as root).

**C. First paste** — makes a key that lets the server read the private code:

```bash
mkdir -p ~/.ssh && { [ -f ~/.ssh/lunarark ] || ssh-keygen -t ed25519 -N "" -q -f ~/.ssh/lunarark; } && echo && cat ~/.ssh/lunarark.pub
```

It prints one line starting `ssh-ed25519`. Copy that whole line, open
**https://github.com/chetanhansraj/space_game/settings/keys/new**, give it the
title `VPS`, paste the line into *Key*, leave *Allow write access* unticked, and
press **Add key**.

**D. Second paste** — fetches the code and runs the installer:

```bash
command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq git; }; grep -q github-lunarark ~/.ssh/config 2>/dev/null || printf 'Host github-lunarark\n  HostName github.com\n  User git\n  IdentityFile ~/.ssh/lunarark\n  StrictHostKeyChecking accept-new\n' >> ~/.ssh/config; [ -d /opt/lunarark ] || git clone git@github-lunarark:chetanhansraj/space_game.git /opt/lunarark; bash /opt/lunarark/deploy/install.sh
```

It checks the server, waits for the DNS record if it has not arrived yet,
installs Docker, builds and starts the world, gets the HTTPS certificate,
schedules daily backups, and finishes by printing the address and the
**access code** people need to join. If anything goes wrong it stops and says
so — copy what it printed and send it to Claude.

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
git clone git@github-space-game:chetanhansraj/space_game.git /opt/lunarark
cd /opt/lunarark
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
15 4 * * * /opt/lunarark/deploy/backup.sh >> /opt/lunarark/data/backup.log 2>&1
```

Backups land in `data/backups/`. Copy one off the server now and then.

## Updating

```bash
cd /opt/lunarark && ./deploy/update.sh
```

It backs up, pulls, rebuilds and restarts. The world is untouched — it lives in
`data/` — and when it comes back it runs every hour it missed, because offline
is absent, not paused.

## Looking after it

| | |
|---|---|
| Is it running? | `docker compose ps` |
| Logs | `docker compose logs -f game` |
| Is it on time? | `curl -s 127.0.0.1:8000/api/health` — `behind` should be 0 |
| Disk | `du -sh data/` — see below |
| Stop / start | `docker compose stop` / `docker compose --profile https up -d` |

**Disk.** The ledger is append-only by design, and the world writes about
**150 MB a day** — every order every firm places is a permanent record. A
50 GB VPS holds several months. That is fine for a playtest, and it is the
first thing to solve before a public launch (DECISIONS.md, D49).

**Never run two copies against the same `data/`.** One world, one process: a
second one would be a second, diverging world writing into the same ledger.

## Starting over

Only while testing, before anyone real is playing — the world is meant to be
permanent:

```bash
docker compose down && mv data data.old && docker compose --profile https up -d
```
