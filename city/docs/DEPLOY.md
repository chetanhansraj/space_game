# Putting the city builder on the server

The city builder is a static page: `city/dist/index.html` and
`city/dist/game.js`. There is no service, no database and no login. These
steps put it at **https://sim.lunarark.com** on the Hostinger VPS that already
serves lunarark.com and the trade game.

It lives in the same repository as the trade game, so the server already has
the code: the trade game's clone at `/opt/arkgame`. The installer adds one
nginx block that serves `/opt/arkgame/city/dist`, and one certificate.

## Steps

**A. The DNS record.** hPanel → **Domains → lunarark.com → DNS / Nameservers**
→ add an **A** record: Name `sim`, Points to *your VPS IP* (the same address
the `play` record points to), TTL 3600. Leave every other record alone.

**B. Open the terminal.** hPanel → **VPS → your server → Browser terminal**.

**C. Fetch the code.** This is the trade game's own updater. It backs up the
world, pulls, and restarts the trade game, which is down for a few seconds:

```bash
bash /opt/arkgame/deploy/update-nginx.sh
```

**D. Check first. This changes nothing.**

```bash
CHECK_ONLY=1 bash /opt/arkgame/city/deploy/install-nginx.sh
```

It should end with **"Check passed. Nothing was changed."**

**E. Install.**

```bash
bash /opt/arkgame/city/deploy/install-nginx.sh
```

It finishes by printing the address. If anything goes wrong it stops and says
so. Copy what it printed and send it to Claude.

## What it will and will not touch

It writes exactly one file, the nginx block for the domain, marked *"Written
by the Lunar Ark city installer (arksim)"*, and asks certbot for one
certificate. Before changing anything it **refuses** if:

- the folder is not inside a clone of this repository;
- nginx already has a block for the domain that it did not write;
- any other nginx config already answers for the domain;
- another site or service already uses the `city/` folder;
- nginx cannot read `city/dist`.

nginx is reloaded only if `nginx -t` passes with the new block in place; if it
fails, the block is removed again. Ports, the firewall, the trade game's
service and data, and every other site are left as they are.

The block asks search engines not to index the page while the game is in
development. To let it be found, delete the `X-Robots-Tag` line from
`/etc/nginx/sites-available/sim.lunarark.com` and run `systemctl reload nginx`.

## Updating

When only the city builder changed:

```bash
bash /opt/arkgame/city/deploy/update.sh
```

It pulls and is done; players get the new build on their next page load. If
the update also touches the trade game it changes nothing and tells you to run
`bash /opt/arkgame/deploy/update-nginx.sh`, which updates both.

## Removing it

```bash
rm /etc/nginx/sites-available/sim.lunarark.com /etc/nginx/sites-enabled/sim.lunarark.com
systemctl reload nginx
```

## Notes

- Saved games are kept in each player's browser, per address. A base started
  somewhere else (a preview link, a local build) does not carry over.
- The page loads PixiJS from cdn.jsdelivr.net and its fonts from Google Fonts.
- To rebuild `dist/` after changing the source: `npm ci && npm run build` in
  `city/`. Commit `dist/` with the change; the server does not build.
