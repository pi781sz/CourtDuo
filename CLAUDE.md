# CourtDuo

Telegram bot that lets Polish junior tennis players invite a specific partner to play doubles at a PZT tournament.

---

## What this is — and what it is not

**It is:** a way for a player to send a structured invitation to another named player for a specific tournament, and get a yes or no.

**It is not:** a directory, a browsable pool, or a matchmaking service. There is no "show me who is looking". A player can only reach someone whose name they already know. Do not build discovery features.

Every user is a junior player aged roughly 10–18.

---

## Non-negotiable rules

Do not implement anything that violates these. If a request would break one, say so instead of building it.

1. **No free-text messaging between users. Ever.** Every interaction is inline keyboard buttons and pre-defined messages. No chat, no message relay, no "add a note" field. An invitation carries only: inviter name, tournament, date, and buttons — Zatwierdź, Odrzuć, and (per the spec change under "Invitation engine") Nie jadę na ten turniej.

2. **The bot never looks up, stores, or displays a phone number.** In the "invite a non-user" flow the bot generates share text; the phone's own contact picker chooses the recipient. The bot never sees who it went to.

3. **Never commit secrets.** Bot token, database URL, any credential → environment variables and GitHub Secrets. This repo is public.

4. **Never commit scraped player data.** No CSV, JSON, SQLite or fixture containing real player names may enter git. These are children's names in a public repository. Test fixtures use invented names. Enforce with `.gitignore`.

---

## Language

Interface is Polish. **Never hardcode user-facing strings.**

- All strings in `locales/pl.json`, accessed via `t(key, lang)`
- `locales/en.json` added later; structure supports it from day one
- Data stays Polish permanently — tournament names, clubs and cities come from PZT untranslated

---

## Identity

**One Telegram account = one PZT player.** Registration is by PZT ID, which the player already knows. No name search, no disambiguation, no role selection.

Gender is derived from which ranking list the player appears in:
- `M12` / `M14` / `M16` / `M18` → Chłopcy
- `W12` / `W14` / `W16` / `W18` → Dziewczęta

*(Multi-player accounts — a parent with two children — are not in scope now. Do not design them away, but do not build them.)*

**Name order: storage is PZT's, display is not.** PZT stores names "Nazwisko Imię" (surname first) — `accounts.full_name` and `players.full_name` keep that order permanently, and name matching (see "Tournament selection" → partner name entry) accepts either order. But every user-facing message must show "Imię Nazwisko" instead: "Szewczyk Jagoda" → "Jagoda Szewczyk". `core.text.display_name` does this reordering (first token is the surname, every remaining token is a given name) and every place a player's name is shown — invitations, accept/reject/not-attending notifications, "already has a partner" checks, disambiguation buttons — must go through it. `core.text.first_name`, used only for the player's own welcome greeting, returns just the first given name — the *second* token, since the first is the surname.

---

## User journeys

### Scenario 1 — invite a player who already uses CourtDuo

```
Bot:   Aby zacząć, podaj swój login PZT.
Adam:  SWD12345
Bot:   Witaj Adam Smith. [buttons: U12  U14  U16  U18]
Adam:  [taps U14]
Bot:   Podaj miejscowość turnieju.
Adam:  Uniejów
Bot:   [buttons: "WTK Uniejów - 29.08.2026", ...one per matching tournament]
Adam:  [taps one]
Bot:   Wybrany turniej: Uniejów U14 — 29.08.2026.
       Wpisz imię i nazwisko osoby, którą chcesz zaprosić.
Adam:  Peter Lorenz
Bot:   [confirmation screen, warns the match cannot be cancelled]
Adam:  [confirms]
Bot:   Zaproszenie zostało wysłane. Czekaj na odpowiedź.
       ⚪ Peter Lorenz — <tournament> — zaproszenie oczekujące
```

Peter simultaneously receives:

```
Adam Smith zaprasza Cię do gry podwójnej.
<tournament name>
<date>
Uwaga: po akceptacji nie można zmienić partnera.
[Zatwierdź]  [Odrzuć]  [Nie jadę na ten turniej]
```

**On Zatwierdź** — both see 🟢 with tournament, date and partner name. Adam gets an alert: *"Peter Lorenz przyjął zaproszenie."*

**On Odrzuć** — Peter sees 🔴 *"Odrzuciłeś zaproszenie od Adam Smith — <tournament>"*. Adam's status flips to 🔴 *odmowa* with the name and tournament.

**On Nie jadę na ten turniej** — Peter sees *"Odpowiedziałeś, że nie jedziesz na ten turniej."* Adam's status flips to a neutral 🟠 *"Peter Lorenz nie jedzie na ten turniej."*, distinct from 🔴 *odmowa*. This closes that one invitation only — see "Spec change: a third invitation response" under Invitation engine.

### Scenario 2 — the invited player is not on CourtDuo

Identical until the name is entered. Then:

```
Bot:   Peter Lorenz nie używa CourtDuo. Wyślij mu zaproszenie:
       [SMS]  [WhatsApp]  [Telegram]
```

Each button opens a share sheet with pre-written Polish invitation text and a link to the bot. **The recipient is chosen from the player's own phone contacts.** The bot never handles a number.

Store a pending invite keyed on the typed name. When someone registers whose name matches, notify Adam: *"Peter Lorenz dołączył do CourtDuo"*, and offer to send the real invitation.

### Scenario 3 — returning player

Skips registration entirely. `/start` goes straight to the age-category buttons.

---

## Tournament selection

**Age category first, always.** Before asking for a place, the bot shows four buttons — U12, U14, U16, U18 — and the player taps one. This is asked every session; the bot never remembers the last choice, defaults to one, or derives it from the player's own ranking lists. A younger player may enter an older draw, so all four are always offered regardless of the player's age. A category with no eligible tournaments is shown rather than hidden, labelled e.g. "U12 — brak turniejów"; tapping it just re-shows the four buttons, never a place prompt. Availability must respect the player's gender — a girl must not see a category marked available on the strength of a boys-only draw.

**Never ask the player to type a tournament name.** Real names are unusable — one live U18 tournament is literally `WTK - 👋U18 chł🎾dz😀Uniejów😀turniej grupowy🥇🥈🥉`.

Once a category is chosen, the player types a **place** (city or województwo). The bot matches against `venue_city` and `wojewodztwo`, diacritic-insensitively via `fold_diacritics`, and shows matching tournaments — already filtered to the chosen category — as buttons.

Only show tournaments that:
- match the chosen age category
- start within the next 28 days
- have at least one event with `Gra podwójna`
- match the player's gender (`Chłopcy` / `Dziewczęta`)
- do not have `ranga` 6 or 7 (see "Internal tournaments are hidden" below)

If nothing matches the typed place, offer a button to show all eligible tournaments (in the chosen category) in the next 28 days. Never dead-end.

**Internal tournaments are hidden.** Tournaments with `ranga` 6 or 7 are internal club events and must never appear — not in the results list, and not counted toward a category's availability (a category must never look available on the strength of a tournament the player will then not see). If `ranga` is `NULL`, the tournament is still shown, with no type prefix, and a warning naming the `guid` is logged — hiding it would risk losing a real tournament, which is worse than an unlabelled one.

**Button label format.** `<prefix> <place> - <date>` — prefix, space, city (or województwo when `venue_city` is null), space, plain hyphen (`-`, not an em dash), space, date as `DD.MM.YYYY`. When there is no prefix (`ranga` is `NULL` or unmapped) the label simply starts with the place, e.g.:

```
WTK Uniejów - 22.08.2026
OTK Kołobrzeg - 29.08.2026
MW Kraków - 05.09.2026
Radom - 20.08.2026            (ranga NULL — no prefix)
```

The prefix is derived from `ranga` via one lookup table (`bot.tournament_search.RANGA_PREFIX`), not scattered conditionals:

| `ranga` | prefix |
|---|---|
| 1 | MP |
| 2 | SS |
| 3 | OTK |
| 4 | MW |
| 5 | WTK |
| 6, 7 | *(not shown at all — see above)* |
| `NULL` | *(no prefix)* |

**All user-facing dates are `DD.MM.YYYY`**, e.g. `22.08.2026` — never `YYYY.MM.DD`. This applies to tournament button labels and to the selection confirmation message alike, so the player is never shown two different date formats in the same flow.

**Confirm the exact tournament chosen.** On selecting a tournament, state the town, the age category and the date together in one message — e.g. "Wybrany turniej: Grodzisk Mazowiecki U14 — 08.08.2026" — never a date-only confirmation. This feeds an invitation that cannot be cancelled, so it must be unambiguous which tournament was picked.

The results screen offers "Zmień miejscowość" (keeps the chosen category) and "Zmień kategorię wiekową" (clears it and returns to the four category buttons).

---

## Pre-invitation checks

Run these **at name-entry time, before the confirmation screen**, so a player never confirms an invitation that cannot succeed.

**If the inviter is already matched at this tournament** — do not ask for a name at all:

> *Masz już partnera na ten turniej: Peter Lorenz.*

**If the named player is already matched at this tournament:**

> *Peter Lorenz ma już partnera na ten turniej.*
> *Wpisz imię i nazwisko innej osoby.*

Never reveal **who** that partner is — it is not the inviter's business.

**If a pending invitation to that same person for that tournament already exists:**

> *Zaproszenie do Peter Lorenz zostało już wysłane. Czekaj na odpowiedź.*

**If the named player's gender does not match the event:** refuse and explain.

These checks are a courtesy, not a guarantee — the named player may accept someone else a second later. The atomic lock at accept time is what protects the data. Both are required.

---

## Invitation engine

The part most likely to break. Be careful.

**States:** `PENDING` → `ACCEPTED` | `REJECTED` | `NOT_ATTENDING` | `CANCELLED` | `EXPIRED`

**Rules:**

- A player may have up to **3 pending outgoing invitations** per tournament.
- **First accept wins.** On acceptance, all other pending invitations for **both** players at that tournament are cancelled. Each cancelled recipient is told: *"Ten zawodnik znalazł już partnera."*
- **Atomic locking is mandatory.** The accept transaction must `SELECT … FOR UPDATE` the relevant invitation rows, re-verify neither player is already matched at that tournament, then commit. Without this you will eventually double-book someone.
- **A confirmed match is locked.** Neither side can cancel or change partner. Both are warned of this *before* confirming — the inviter on the confirmation screen, the invitee in the invitation itself. *(Cancellation may be added later; do not build it now.)*
- Invitations expire at **10:00 Europe/Warsaw on the tournament start date**, computed via `zoneinfo` and stored as UTC. Poland is UTC+2 in summer, UTC+1 in winter — never hardcode an offset.
- Rejection is instant and free. The inviter may immediately invite someone else.
- Responding "Nie jadę na ten turniej" is instant and free too, exactly like rejection — the inviter may immediately invite someone else. See "Spec change: a third invitation response" below.

**Eligibility:**

- **Gender must match.** A Chłopcy event needs two boys. Refuse and explain.
- The tournament must have a `Gra podwójna` event.
- Age category is **not** enforced — younger players routinely play up.

**Spec change: a third invitation response.** *(Documented now; not built until step 7 — do not implement this yet.)*

An invitation gets a third button alongside Zatwierdź and Odrzuć: **"Nie jadę na ten turniej"**.

- `NOT_ATTENDING` closes that one invitation and nothing else.
- It is explicitly **not** a stored fact about the player and the tournament: it must not block, hide or filter any future invitation to that player for that tournament. Players change their minds, enter late, and withdraw. Do not design a "not attending" table or flag — this is purely a terminal state on the one `Invitation` row.
- The invitee sees: *"Odpowiedziałeś, że nie jedziesz na ten turniej."*
- The inviter sees a neutral status, distinct from 🔴 odmowa: 🟠 *"Peter Lorenz nie jedzie na ten turniej."*
- The inviter may immediately invite someone else, exactly as with rejection.

---

## Status display — "Moje deble"

One place a player sees every invitation they have sent or received, and what happened to it. Reachable two ways: the `/moje_deble` command, and a "Moje deble" button carried by every terminal message (see "A terminal message always carries a way back" below) and by the age-category screen.

Group by tournament, ordered by tournament date ascending. Within a tournament, matched first, then everything else by most recent.

```
WTK Uniejów - 22.08.2026
🟢 Partner: Jagoda Szewczyk

OTK Zielona Góra - 29.08.2026
⚪ Maja Nowak — wysłane
🔴 Bartosz Nowak — odmowa
🟠 Wiktoria Wójcik — nie jedzie
```

Colours:

- ⚪ pending
- 🟢 matched
- 🔴 rejected
- 🟠 not attending

Both directions are shown — invitations this player sent and ones they received — and wording makes clear which is which: a sent line reads `{name} — wysłane`/`odmowa`/`nie jedzie`; a received line is prefixed `Zaproszenie od {name} —` so it never reads like a sent one. A matched line is symmetric regardless of who invited whom.

A received invitation still pending is actionable from here: it carries the Zatwierdź / Odrzuć / "Nie jadę na ten turniej" buttons, reusing step 7's own callback classes and handlers unchanged — a player who dismissed the original notification is not stuck hunting for it.

**What it hides.** Only tournaments that have not finished. Use `date_to` where present, otherwise `date_from`; a tournament is over at the end of that day, Europe/Warsaw. Nothing is deleted from the database — this is a display filter only, so past invitations stay available for the results-based verification planned later. Invitations cancelled automatically when someone else accepted are noise, not history, and are never listed — the player was already told at the time.

**Empty state.** If there is nothing to show, say so plainly and offer "Znajdź partnera" (not "Moje deble" — that would point back at the same empty screen).

**Never** reveals who a third party's partner is — only this player's own matches. If another player is matched with someone else at a tournament, this view never names that someone else.

**A terminal message always carries a way back.** "Never dead-end" (see "Tournament selection") applies to notifications, not just search results: any message that ends a flow — a rejection, a "nie jedzie" notice, a "ten zawodnik znalazł już partnera" cancellation, the match confirmation both players get on Zatwierdź, an invitation just sent — carries both a "Moje deble" and a "Znajdź partnera" button, the latter returning the player straight to the age-category screen. The age-category screen carries both too. `/start` must never be the only way forward.

---

## Data sources

All PZT pages are plain GET. No login, no JavaScript.

### Tournaments — four junior categories

| Category | Age | URL |
|---|---|---|
| Skrzaty | U12 | `https://portal.pzt.pl/Tournament.aspx?CategoryID=12` |
| Młodzicy | U14 | `https://portal.pzt.pl/Tournament.aspx?CategoryID=14` |
| Kadeci | U16 | `https://portal.pzt.pl/Tournament.aspx?CategoryID=16` |
| Juniorzy | U18 | `https://portal.pzt.pl/Tournament.aspx?CategoryID=18` |

Adult categories (`CategoryID=19`) are out of scope.

Fields captured: `guid`, `name`, `type_prefix`, `age_category`, `ranga`, `date_from`, `date_to`, `wojewodztwo`, `venue_address`, `venue_city`, `entry_deadline`, `withdrawal_deadline`, `search_closes_at`, `events`. Doubles is not a tournament column — it's `events.is_doubles`, found by joining to the tournament's events.

**Model events separately from tournaments** — one tournament has many events. Only events containing `Gra podwójna` matter. Four of eighteen live U18 tournaments have no doubles draw at all.

**Known trap:** PZT serves `_light` variants of header CSS classes (`tournAppTopCent_B_light` etc.) for tournaments in certain states. Match header classes by **prefix**, never exact token, or dates silently return null.

### Rankings — eight lists, `Sort=A` only

| Category | Chłopcy | Dziewczęta |
|---|---|---|
| U12 | `M12` | `W12` |
| U14 | `M14` | `W14` |
| U16 | `M16` | `W16` |
| U18 | `M18` | `W18` |

```
https://portal.pzt.pl/Ranking.aspx?RCatID={code}&Sort=A&Year={YYYY}&Month={M}
```

The alphabetical list carries `position` for every player, so `Sort=LP` is unnecessary — sort in the database instead.

Captured per player: `pzt_id`, `full_name`, `club`, `position`, `itf_note`.

**Do not hardcode or increment Year/Month.** Scrape the index at `https://portal.pzt.pl/Ranking.aspx?RCatID=M` and follow the current *"lista X / YYYY"* links. PZT publishes on the first Wednesday monthly but is often late; guessing produces empty pages and silent data loss.

**Known trap:** ITF badges concatenate into the name cell (`"Błuś AleksanderMiejsce 77 na listach ITF 18"`). Extract the name node's own text only; keep the badge as `itf_note`.

---

## Scraper scheduling

- **Tournaments:** 3× daily via GitHub Actions cron
- **Rankings:** daily at 15:00 Europe/Warsaw during the first 10 days of each month, weekly otherwise. Each run reads the index first and re-scrapes the eight lists **only if the published month changed.**

The bot always reads the newest available `(year, month)`. Older lists stay in the table.

---

## Monetisation — build now, enable later

Free at launch. Build the entitlement check anyway.

```
accounts.plan               'free' | 'paid'
accounts.invitations_used   integer
can_send_invitation(account, tournament) -> bool   # currently always True
```

Every invitation must route through `can_send_invitation`. When paid tiers launch, one function changes. Do not scatter quota logic through the codebase.

---

## Stack

- Python 3.11+, `aiogram` 3, PostgreSQL
- `httpx` + `selectolax` for scraping
- SQLAlchemy models, Alembic migrations
- Scrapers on GitHub Actions cron; bot on a small always-on VM

**Scraping etiquette:** rate limit to ~1 request per 2 seconds, descriptive `User-Agent` with a contact email, cache aggressively, fail loudly rather than writing garbage.

---

## Build order

1. ~~Tournament scraper with doubles detection~~ **done**
2. ~~Ranking scraper, alphabetical lists~~ **done**
3. ~~Database schema and upserts~~ **done — needs revision for this spec**
4. Registration by PZT ID
5. Tournament selection by place
6. Pre-invitation checks
7. Invitation send / accept / reject with atomic locking
8. ~~Status view and notifications~~ **done**
9. Non-user invite flow and the "they joined" callback
