# Deploying CourtDuo

Setting up and running the bot on a Linux server. Verified on Ubuntu 24.04 and Ubuntu 26.04; anything else with Python 3.11+ works with minor changes.

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
apt-get update -qq && apt-get install -y -qq python3-venv python3-pip postgresql-client git

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

`git` is only coincidentally preinstalled on some base images — it's listed explicitly above so this works regardless. A full install was verified 2026-08-15 on Ubuntu 26.04 LTS / Python 3.14.4 (x86_64, Hetzner Cloud CX23, Helsinki): `git 2.53.0` and `curl` were already present in that base image, `psql (PostgreSQL) 18.4`, and every compiled dependency (`asyncpg`, `selectolax`, `pydantic-core`, `aiohttp`, `greenlet`) had a cp314 manylinux x86_64 wheel, so `pip install` needed no compiler. Installed versions: `aiogram` 3.30.0, `SQLAlchemy` 2.0.52, `alembic` 1.19.1, `httpx` 0.28.1, `python-dotenv` 1.2.2.

---

## Configuration

The app reads `.env` from its working directory. Copy `.env.example` and fill it in:

```
BOT_TOKEN=
DATABASE_URL=
SCRAPER_CONTACT_EMAIL=
DEFAULT_LANG=pl
VIEWER_ALLOWLIST_PZT_IDS=
ALARM_TELEGRAM_IDS=
```

| Variable | Notes |
|---|---|
| `BOT_TOKEN` | From @BotFather |
| `DATABASE_URL` | `postgresql://…`; the app rewrites the scheme for asyncpg itself |
| `SCRAPER_CONTACT_EMAIL` | Sent as part of the scrapers' `User-Agent` header so PZT can make contact. Optional — `core/http.py` falls back to a default when unset |
| `DEFAULT_LANG` | `pl`. `en` scaffolding exists but `locales/en.json` is not written |
| `VIEWER_ALLOWLIST_PZT_IDS` | Comma-separated. Leave empty to disable the read-only viewer feature |
| `ALARM_TELEGRAM_IDS` | Comma-separated numeric Telegram ids. These receive staleness alerts and are the only ids that may use the operator-only `/status` command. Leave empty to disable notifications — the alarm still runs and still logs a warning, it just has nobody to tell |

Two more environment variables exist purely to override the staleness alarm's thresholds for testing, without a code change — `STALENESS_TOURNAMENTS_HOURS` and `STALENESS_RANKINGS_HOURS` (default 36 and 216 hours; see `bot/staleness.py`). Neither is needed for a normal deploy, and neither is in `.env.example`.

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

**The scraper units are not part of this split.** `deploy/courtduo-tournaments.service` and `deploy/courtduo-rankings.service` hardcode `WorkingDirectory=/opt/courtduo` — whichever checkout lives at that exact path is the one the scrapers feed; the other environment gets no scraped data at all unless you copy the unit files and edit that path yourself. See `deploy/README.md` for the full explanation.

The directory name and the systemd service name are chosen independently of each other — nothing ties `/opt/courtduo-test` to a service literally called `courtduo-test`. A deploy has already broken from exactly this: code was pulled into one directory while `systemctl restart` targeted a service name that didn't match it, so the running process never actually restarted. Whatever directory/service pairing you choose, write it down.

---

## Moving to another server

Almost no state lives on the machine — code is in git, data is in Postgres. A move is this document repeated, roughly twenty minutes.

- Registered players are unaffected: accounts live in the database, and the bot username does not change.
- Telegram uses long polling, not webhooks, so no DNS record, domain, TLS certificate or firewall rule is tied to the server's address.
- In-progress conversations use `MemoryStorage` and are lost on restart. Anyone mid-flow sends `/start` again. True of any restart, not just a move.
- Stop the old service before starting the new one.

---

## Scrapers

Both scrapers run on **systemd timers on the server**, not GitHub Actions — see `deploy/README.md` for the unit files and install steps. They can also be run directly, same as the timers do:

```bash
cd /opt/courtduo
set -a; . ./.env; set +a
./venv/bin/python -m scrapers.rankings
./venv/bin/python -m scrapers.tournaments
```

Scheduling lives on the server because GitHub disables scheduled workflows automatically after 60 days without a commit to the default branch — silently, with no banner in the Actions tab, just one easily-missed email. That's a real problem for a low-commit-velocity public repo, and it's the reason scheduling moved to systemd timers rather than a live risk to guard against here: the only GitHub workflow in this repo, `.github/workflows/test-scraper.yml`, is `workflow_dispatch`-only and `--dry-run`, so it writes nothing and is exempt from the 60-day disable.

**A dead or failing scraper doesn't rely on anyone noticing by chance.** The staleness alarm (`bot/staleness.py`) checks 30 seconds after the bot starts and every 6 hours after, comparing each scraper's newest successful `scraper_runs` row against a threshold (36 hours for tournaments, 216 hours / 9 days for rankings), and messages every id in `ALARM_TELEGRAM_IDS` (see "Configuration" above) when a scraper is stale, plus a reminder every 24 hours until it recovers. The same ids can send `/status` to the bot at any time for a plain-text report of both scrapers' last successful run, last run, and current threshold state. Set `ALARM_TELEGRAM_IDS` for this to have anywhere to send alerts and anyone able to use `/status` — leave it empty and the alarm still runs and logs, it just has nobody to tell.

---

## Tests

```bash
cd /opt/courtduo
./venv/bin/python -m pytest
```

Database-backed tests skip cleanly unless `TEST_DATABASE_URL` is set. **Never point it at a database with real data** — the tests write and delete.
