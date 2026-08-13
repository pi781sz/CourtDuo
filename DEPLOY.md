# Deploying CourtDuo

Setting up and running the bot on a Linux server. Written for Ubuntu 24.04; anything else with Python 3.11+ works with minor changes.

Nothing here is architecture-specific — ARM and x86 both work.

---

## What you need first

- A server with Python 3.11+, `git`, and outbound internet access
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A PostgreSQL database URL

Run the bot as an **unprivileged system user**, never as root. It is internet-facing and accepts input from strangers.

---

## First-time setup

```bash
# prerequisites
apt-get update -qq && apt-get install -y -qq python3-venv python3-pip postgresql-client

# unprivileged user, home directory doubles as the install path
adduser --system --group --home /opt/courtduo --shell /usr/sbin/nologin courtduo

# code
git clone https://github.com/pi781sz/CourtDuo.git /opt/courtduo
chown -R courtduo:courtduo /opt/courtduo

# python environment
cd /opt/courtduo
python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt
```

---

## Configuration

The app reads `.env` from its working directory. Copy `.env.example` and fill it in:

```
BOT_TOKEN=
DATABASE_URL=
DEFAULT_LANG=pl
VIEWER_ALLOWLIST_PZT_IDS=
ALARM_TELEGRAM_IDS=
```

| Variable | Notes |
|---|---|
| `BOT_TOKEN` | From @BotFather |
| `DATABASE_URL` | `postgresql://…`; the app rewrites the scheme for asyncpg itself |
| `DEFAULT_LANG` | `pl`. `en` scaffolding exists but `locales/en.json` is not written |
| `VIEWER_ALLOWLIST_PZT_IDS` | Comma-separated. Leave empty to disable the read-only viewer feature |
| `ALARM_TELEGRAM_IDS` | Comma-separated numeric Telegram ids. Who the staleness alarm notifies and who `/status` answers for — see "Staleness alarm" below |

Lock it down:

```bash
chown courtduo:courtduo /opt/courtduo/.env
chmod 600 /opt/courtduo/.env
```

**Never commit `.env`.** It is gitignored; keep it that way.

### Managed-Postgres connection strings

Some providers append parameters asyncpg rejects. `sslmode` is stripped automatically by `db/session.py`; **`channel_binding` is not**, and will cause a connection error. Remove it:

```bash
# turns ...?sslmode=require&channel_binding=require into ...?sslmode=require
sed -E 's/([?&])channel_binding=[^&]*&/\1/; s/[?&]channel_binding=[^&]*$//'
```

---

## Database

```bash
cd /opt/courtduo
set -a; . ./.env; set +a
./venv/bin/alembic upgrade head
```

The bot reads tournament and ranking data that the scrapers write. A fresh database is empty, so **run both scrapers before starting the bot**, or every search returns nothing:

```bash
./venv/bin/python -m scrapers.rankings
./venv/bin/python -m scrapers.tournaments
```

Both are rate-limited to roughly one request every two seconds and take a few minutes. They print progress to stderr.

---

## Running under systemd

`/etc/systemd/system/courtduo.service`:

```ini
[Unit]
Description=CourtDuo Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=courtduo
Group=courtduo
WorkingDirectory=/opt/courtduo
ExecStart=/opt/courtduo/venv/bin/python -m bot.main
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/courtduo

[Install]
WantedBy=multi-user.target
```

`WorkingDirectory` matters — it is how the app finds `.env`. Keeping the token out of the unit file means it never appears in `systemctl show` output.

```bash
systemctl daemon-reload
systemctl enable --now courtduo
systemctl status courtduo --no-pager
```

Logs:

```bash
journalctl -u courtduo -f
```

Set up `logrotate` if disk is tight.

---

## Deploying a change

```bash
cd /opt/courtduo
git pull
chown -R courtduo:courtduo /opt/courtduo
set -a; . ./.env; set +a
./venv/bin/alembic upgrade head
systemctl restart courtduo
sleep 3
git log --oneline -3
systemctl status courtduo --no-pager | head -5
```

`chown` after `git pull` because root writes new files as root. `alembic upgrade head` is safe whether or not there is a new migration — it no-ops when already current. `git log` confirms the pull actually landed, which is the most common reason a change appears not to have worked.

If git refuses with "dubious ownership", once:

```bash
git config --global --add safe.directory /opt/courtduo
```

---

## Running test and production side by side

Telegram has no staging environment, so use two bots against two databases:

| | Test | Production |
|---|---|---|
| Bot | `@CourtDuoTestBot` | `@CourtDuoBot` |
| Directory | `/opt/courtduo-test` | `/opt/courtduo` |
| Service | `courtduo-test` | `courtduo` |
| Database | separate branch or database | separate branch or database |

Each gets its own `.env`, venv and systemd unit. They share nothing.

**Only one process may poll a given bot token at a time.** Two instances on the same token fight over updates and behave erratically. When moving servers, stop the old service *before* starting the new one.

---

## Moving to another server

Almost no state lives on the machine — code is in git, data is in Postgres. A move is this document repeated, roughly twenty minutes.

- Registered players are unaffected: accounts live in the database, and the bot username does not change.
- Telegram uses long polling, not webhooks, so no DNS record, domain, TLS certificate or firewall rule is tied to the server's address.
- In-progress conversations use `MemoryStorage` and are lost on restart. Anyone mid-flow sends `/start` again. True of any restart, not just a move.
- Stop the old service before starting the new one.

---

## Scrapers

Currently run on GitHub Actions cron. They also run fine on the server:

```bash
cd /opt/courtduo
set -a; . ./.env; set +a
./venv/bin/python -m scrapers.rankings
./venv/bin/python -m scrapers.tournaments
```

**A caution about scheduled workflows in public repositories.** GitHub disables them automatically after 60 days without commits to the default branch, with no visible warning beyond one email. The bot will not crash — it keeps reading the database and serving progressively staler data, until every tournament ages out of the search window and every search returns "nothing found", which is indistinguishable from a genuine empty result.

---

## Staleness alarm

Built-in, not something you need to set up separately. The bot checks each scraper's run history (the `scraper_runs` table — see CLAUDE.md "Operations") 30 seconds after startup and every 6 hours after that. If tournaments hasn't had a successful run in 36 hours, or rankings in 216 hours (9 days — it only runs weekly outside the first ten days of a month), every id in `ALARM_TELEGRAM_IDS` gets a Telegram message, with a reminder every 24 hours until it recovers.

Leave `ALARM_TELEGRAM_IDS` empty and the alarm still runs and still logs a warning — it just has nobody to notify.

The same list can run `/status` against the bot at any time for a plain-text snapshot of both scrapers' last successful run, last run outcome, and current threshold state. Anyone not on the list gets no reply at all.

---

## Account deletion and blocking

Players delete their own account from inside the bot (`/usun_konto`) — nothing to set up. Blocking a PZT id (so it can't register or use invitations again, even if it already has an account) is operator-only and deliberately has no bot command at all: it's done directly in `psql`. See **`docs/RUNBOOK.md`** for the copy-pasteable SQL — blocking, unblocking, deleting an account on a player's behalf when they can't do it themselves, and answering a subject access request.

---

## Tests

```bash
cd /opt/courtduo
./venv/bin/python -m pytest
```

Database-backed tests skip cleanly unless `TEST_DATABASE_URL` is set. **Never point it at a database with real data** — the tests write and delete.
