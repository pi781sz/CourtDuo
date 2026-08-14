# Scraper systemd timers

Runs both scrapers on the server itself, on the same schedule they used to
run under GitHub Actions cron (CLAUDE.md "Scraper scheduling"):

- **Tournaments:** three times a day.
- **Rankings:** daily at 15:00 Europe/Warsaw during the first 10 days of
  the month, weekly (Wednesdays) for the rest of it.

Rankings uses **two** timer units — `courtduo-rankings.timer` (the daily
leg, days 1–10) and `courtduo-rankings-weekly.timer` (the weekly leg, days
11 onward) — both pointing at the same `courtduo-rankings.service`.
systemd's `OnCalendar` can't express "daily for 10 days, then weekly" in
one line, and the alternative — a day-of-month guard inside the scraper
itself — would mean touching scraper code to solve a scheduling problem.
Two small timer files that only ever say *when*, leaving *what* untouched,
reads more clearly six months from now than a conditional buried in
`scrapers/rankings/__main__.py` would. The scraper's own "only re-scrape
if the published month changed" check (already in the code) is what keeps
the daily runs cheap; these timers just decide when to ask.

Both scrapers already read `.env` from `WorkingDirectory` exactly like the
bot does — no secret goes in a unit file.

**These units are not environment-specific.** Unlike the bot, which runs
as two separate services on this server — `courtduo-test` (test bot) and
`courtduo` (production) — a scraper run just writes to whatever
`DATABASE_URL` is set in `/opt/courtduo/.env`. There is one
`courtduo-tournaments`/`courtduo-rankings` pair of units, not a
test/production pair, unless you deliberately set up a second `/opt/...`
checkout with its own `.env` and copy the units there under different
names.

---

## Install

Copy the unit files into place:

```bash
sudo cp deploy/courtduo-tournaments.service deploy/courtduo-tournaments.timer \
        deploy/courtduo-rankings.service deploy/courtduo-rankings.timer \
        deploy/courtduo-rankings-weekly.timer \
        /etc/systemd/system/

sudo systemctl daemon-reload

sudo systemctl enable --now courtduo-tournaments.timer
sudo systemctl enable --now courtduo-rankings.timer
sudo systemctl enable --now courtduo-rankings-weekly.timer
```

(`courtduo-tournaments.service` and `courtduo-rankings.service` are
`Type=oneshot` — do not `enable --now` the `.service` files themselves,
only the `.timer` files. systemd starts the service when its timer fires.)

## Confirm they're scheduled

```bash
systemctl list-timers --all | grep courtduo
```

Shows each timer's next scheduled run and when it last fired. All three
timers (`courtduo-tournaments`, `courtduo-rankings`,
`courtduo-rankings-weekly`) should be listed and enabled.

## Run one immediately, without waiting for the schedule

```bash
sudo systemctl start courtduo-tournaments.service
sudo systemctl start courtduo-rankings.service
```

Then check it actually worked:

```bash
journalctl -u courtduo-tournaments -n 50 --no-pager
journalctl -u courtduo-rankings -n 50 --no-pager
```

A successful run logs how many tournaments/ranking entries it scraped and
wrote. A failure logs an exception — either way, `scraper_runs` gets a row
either way (CLAUDE.md "Operations"), so the staleness alarm sees it too.

## If a run was missed (server was off)

`Persistent=true` on every timer means a run that was scheduled while the
machine was down fires once at the next boot instead of being skipped
entirely.

---

## Journal size cap

Scraper output goes to journald, not a file under `/opt/courtduo` — there
is nothing for classic `logrotate` to rotate. `deploy/courtduo-logrotate`
is a journald configuration drop-in (despite the filename, kept for
naming consistency with the rest of this directory) that caps the
persistent journal at roughly 200 MB, which is plenty for two oneshot
scrapers running a handful of times a day. On a small server, disk is the
constrained resource, so this matters.

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp deploy/courtduo-logrotate /etc/systemd/journald.conf.d/courtduo.conf
sudo systemctl restart systemd-journald

# optional: shrink the journal to the new cap immediately, rather than
# waiting for it to grow back into the limit naturally
sudo journalctl --vacuum-size=200M
```

---

## Uninstalling / rolling back

```bash
sudo systemctl disable --now courtduo-tournaments.timer
sudo systemctl disable --now courtduo-rankings.timer
sudo systemctl disable --now courtduo-rankings-weekly.timer
sudo rm /etc/systemd/system/courtduo-tournaments.service \
        /etc/systemd/system/courtduo-tournaments.timer \
        /etc/systemd/system/courtduo-rankings.service \
        /etc/systemd/system/courtduo-rankings.timer \
        /etc/systemd/system/courtduo-rankings-weekly.timer
sudo systemctl daemon-reload
```

---

## Don't forget the GitHub side

These timers replace the *schedule*, not the workflow file itself — see
the main PR description / CLAUDE.md for the manual-dispatch-only
replacement workflow YAML. If the old scheduled workflow is left in
place alongside these timers, both will scrape on their own schedules and
the runs will double up (wasted PZT requests, and two `scraper_runs` rows
close together). Remove its `schedule:` block by hand on github.com
before — or right after — enabling these timers.
