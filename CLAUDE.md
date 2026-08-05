# CourtDuo

Telegram bot that helps Polish junior tennis players find doubles partners for PZT tournaments.

---

## Context

**Who uses this:** Parents, guardians and coaches of junior players registered with Polski Związek Tenisowy (PZT). Every *player* in this system is a child aged roughly 10–18. The adult holds the Telegram account; the child does not.

**The problem:** Junior tournaments have doubles draws, but players arrive without partners. Today this is solved through WhatsApp groups and Facebook posts. There is no central way to see who else needs a partner for a specific event.

---

## Non-negotiable rules

These are not preferences. Do not implement anything that violates them. If a requested feature would break one, say so instead of building it.

1. **No free-text messaging between users. Ever.** All interaction is inline keyboard buttons and pre-defined messages. No chat feature, no message relay, no "add a note for your partner" field.

2. **Accounts belong to adults.** Registration asks the account holder to identify as *rodzic / opiekun / trener*. One account may manage several players (siblings, or a coach's squad).

3. **No automatic contact sharing.** On a confirmed match both sides see: player name, club, województwo, ranking position. Phone numbers and Telegram handles are shared **only** when both adults explicitly tap to share.

4. **Never commit secrets.** Bot token, database URL, any credential → environment variables and GitHub Secrets only. This repo is public.

5. **Never commit scraped player data.** No CSV, JSON, SQLite or fixture file containing player names may enter git. These are children's names in a public repository. Data lives in the database only. Enforce with `.gitignore`.

---

## Language

Interface is Polish. **Never hardcode user-facing strings.**

- All strings live in `locales/pl.json`
- Accessed through a `t(key, lang)` helper
- `locales/en.json` will be added later; the structure must support it from day one
- Data stays Polish permanently — tournament names, clubs and cities come from PZT and are not translated

---

## Data sources

All PZT pages are plain GET. No login, no JavaScript rendering, no ViewState POST needed for default views.

### Tournaments — four categories only

| Category | Age | URL |
|---|---|---|
| Skrzaty | U12 | `https://portal.pzt.pl/Tournament.aspx?CategoryID=12` |
| Młodzicy | U14 | `https://portal.pzt.pl/Tournament.aspx?CategoryID=14` |
| Kadeci | U16 | `https://portal.pzt.pl/Tournament.aspx?CategoryID=16` |
| Juniorzy | U18 | `https://portal.pzt.pl/Tournament.aspx?CategoryID=18` |

Adult categories (`CategoryID=19`) are **out of scope**. Do not scrape them.

Each page returns upcoming tournaments only. Available fields:

- Name and type prefix (`OTK`, `WTK`, `MW`, `OTK SS`)
- `Ranga` (1–7)
- Dates, format `Od: 2026.08.07 Do: 2026.08.09`
- Organiser, venue address, województwo
- `Termin zgłoszeń` — entry deadline (**critical**, see Matching)
- `Termin odwołań` — withdrawal deadline
- Tournament director: name, phone, email
- Entry fee, court surface, court count
- `Rozgrywki` block listing events: `Kategoria: … Typ: Gra pojedyncza|Gra podwójna; Chłopcy|Dziewczęta; <draw format>`
- Tournament GUID, extractable from the results link

**Critical:** many tournaments have no doubles draw at all. Only events containing `Gra podwójna` are relevant to this product. Model **events separately from tournaments** — one tournament has many events.

### Rankings — eight lists

Gender is **not** in the tournament category. It lives inside each event as `Chłopcy` or `Dziewczęta`. Join category + event gender to select the ranking list:

| Category | Chłopcy | Dziewczęta |
|---|---|---|
| U12 | `M12` | `W12` |
| U14 | `M14` | `W14` |
| U16 | `M16` | `W16` |
| U18 | `M18` | `W18` |

URL pattern:
```
https://portal.pzt.pl/Ranking.aspx?RCatID={code}&Sort={LP|A}&Year={YYYY}&Month={M}
```

- `Sort=LP` — ranked order. Use for a player's ranking position.
- `Sort=A` — alphabetical roster. **This is the player lookup table for registration.** There is no need to scrape player profile pages.

**Do not hardcode or increment Year/Month.** Scrape the index at `https://portal.pzt.pl/Ranking.aspx?RCatID=M` and follow the current *"lista X / YYYY"* links. PZT publishes on the first Wednesday of each month but can be late — guessing the month produces empty pages and silent data loss.

---

## Registration flow

1. Adult starts the bot, taps role: *rodzic / opiekun / trener*
2. Adult types the player's full name
3. Bot searches the alphabetical rosters and shows matches with club and ranking
4. If several players share a name, adult disambiguates by PZT ID
5. Player is linked to the account. Adult may add more players.

---

## Matching engine

The part most likely to break. Be careful here.

**Search states:** `OPEN` → `REQUESTED` → `MATCHED` | `REJECTED` | `EXPIRED`

**Rules:**

- One active search per `(player, event)`. Enforce with a unique constraint.
- Maximum **2 outgoing requests** per player per tournament.
- **First accept wins.** On acceptance, all other outgoing and incoming requests for both players in that event are cancelled with the notice *"Ten zawodnik znalazł już partnera."*
- **Atomic locking is mandatory.** The match transaction must `SELECT … FOR UPDATE` both search rows, re-verify both are still unmatched, then commit. Without this you will eventually double-book a player and destroy trust in the bot.
- Requests expire after 24h **or** at `Termin zgłoszeń`, whichever comes first.
- Rejection is free and instant; the requester may immediately request someone else.

**Eligibility:** two players may match only if — same tournament, same category, same gender event, and that event contains `Gra podwójna`.

**Notifications:**

- When a new player starts searching an event, **notify everyone already waiting there.** This is the key retention loop. With thin liquidity it is what turns a dead list into a match.
- 48h before `Termin zgłoszeń`, remind anyone still unmatched.

---

## Monetisation — build now, enable later

Everything is free at launch. Build the entitlement check anyway.

```
accounts.plan            'free' | 'paid'
accounts.searches_used   integer
can_start_search(account, tournament) -> bool    # currently always returns True
```

Every search creation must route through `can_start_search`. When paid tiers launch, exactly one function changes. Do not scatter quota logic through the codebase — retrofitting it into a live bot with real users is painful.

---

## Stack

- Python 3.11+
- `aiogram` 3 — Telegram
- PostgreSQL
- `httpx` + `selectolax` (or BeautifulSoup) — scraping
- Scrapers run on **GitHub Actions cron**: tournaments 3× daily, rankings weekly
- Bot runs on a small always-on VM

---

## Scraping etiquette

PZT is a national federation, not an API provider. Treat their server with respect:

- Rate limit to roughly **one request per 2 seconds**
- Set a descriptive `User-Agent` including a contact email
- Cache aggressively; never scrape more often than the data changes
- Fail gracefully — if a page shape changes, log and alert rather than writing garbage to the database

---

## Build order

1. Tournament scraper with doubles-draw detection → database
2. Ranking scraper, both `LP` and alphabetical → database
3. Bot skeleton: `/start`, role selection, player registration
4. Tournament browsing — doubles events only, next 14 days, sorted by entry deadline
5. Search creation and the waiting pool
6. Request / accept / reject with atomic locking
7. Notification and expiry jobs
