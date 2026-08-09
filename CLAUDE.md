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

1. **No free-text messaging between users. Ever.** Every interaction is inline keyboard buttons and pre-defined messages. No chat, no message relay, no "add a note" field. An invitation carries only: inviter name, tournament, date, and buttons — Zatwierdź, Odrzuć, (per the spec change under "Invitation engine") Nie jadę na ten turniej, and a Menu button that lets the recipient step away without answering — the invitation stays PENDING either way.

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
       🟠 Peter Lorenz — <tournament> — zaproszenie oczekujące
```

Peter simultaneously receives:

```
Adam Smith zaprasza Cię do gry podwójnej.
<tournament name>
<date>
Uwaga: po akceptacji nie można zmienić partnera.
[✅ Zatwierdź]  [❌ Odrzuć]  [⛔ Nie jadę na ten turniej]  [🔵 Menu]
```

Telegram can't colour a button, so each answer carries a leading icon instead (✅/❌/⛔), and `[🔵 Menu]` alongside them lets Peter step away — check something else first, look at Moje deble — without answering; the invitation stays PENDING and is answerable later from there (step 8.3).

**On Zatwierdź** — both see 🟢 with tournament, date and partner name. Adam gets an alert: *"Peter Lorenz przyjął zaproszenie."*

**On Odrzuć** — Peter sees 🔴 *"Odrzuciłeś zaproszenie od Adam Smith — <tournament>"*. Adam's status flips to 🔴 *odmowa* with the name and tournament.

**On Nie jadę na ten turniej** — Peter sees *"Odpowiedziałeś, że nie jedziesz na ten turniej."* Adam's status flips to 🔴 *"Peter Lorenz nie jedzie na ten turniej."* — the same colour as odmowa (step 8.3: "not happening" either way), the wording is what tells them apart. This closes that one invitation only — see "Spec change: a third invitation response" under Invitation engine — but per step 8.3's re-invite block, Adam may not send Peter a second invitation for this tournament; he's free to invite someone else immediately.

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

**Age category first, always.** Before asking for a place, the bot shows category buttons and the player taps one. This is asked every session; the bot never remembers the last choice or defaults to one. A category with no eligible tournaments is shown rather than hidden, labelled e.g. "U12 — brak turniejów"; tapping it just re-shows the category buttons, never a place prompt. Availability must respect the player's gender — a girl must not see a category marked available on the strength of a boys-only draw.

**A player may play up but never down.** A younger player may enter an older draw, but not the reverse — a U16 player cannot enter a U12 draw. The category screen offers only categories **≥ the player's own** (a U12 player sees all four; a U16 player sees only U16 and U18); categories below are hidden entirely, which is different from "brak turniejów" — hidden means not eligible, empty-but-shown means eligible with nothing on right now. Re-verified at tap time too, not just at render time, in case a stale keyboard names a category that's no longer offered.

**Deriving a player's own age category.** The LOWEST ranking list the player appears in for the newest `(year, month)` in `rankings` (overall, not per-list — the same "one canonical current period" registration already reads) — a player in `M14` and `M16` is a U14 player playing up, so their category is 14. `players.age_category` is a snapshot of whichever ranking row was scraped last and is **not** guaranteed to be the lowest one; derive fresh from `rankings` instead of reading that column. Registration requires a PZT ID present in a ranking list, so a registered player always has one — but handle a missing value without crashing anyway (never guess an age; fall back to showing everything rather than blocking the player).

This same ceiling applies to the **named player**, not just the screen the inviter sees — see "Pre-invitation checks" below.

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

**If the named player already has a pending invitation to *this* player for the same tournament** — don't create a second invitation chasing the same pair. Redirect the inviter to the answer they already owe instead of blocking them outright:

> *Masz już zaproszenie od Peter Lorenz na ten turniej.*
> *[✅ Zatwierdź]  [❌ Odrzuć]  [⛔ Nie jadę na ten turniej]  [🔵 Menu]*

Reuses the exact invitation, the exact wording, and the exact four-button keyboard the original notification carries — the player can simply accept it. Enforced twice: once here as a friendly pre-check, and again inside the send transaction itself (`SendFailure.ALREADY_INVITED_BY_INVITEE`), since the other player may have sent their invitation moments after this check ran.

**If the named player's gender does not match the event:** refuse and explain.

**If the named player's own age category is older than the tournament's** — a player may play up but never down (see "Tournament selection"):

> *Amelia Nowak nie może grać w kategorii U14.*
> *Wpisz imię i nazwisko innej osoby.*

Checked **before** the "does not use CourtDuo yet" refusal (scenario 2) — live testing showed a too-old player being told "nie używa jeszcze CourtDuo", which is true but not the reason that matters; the age reason is the real one and must be shown first. If the named player has no ranking rows at all, don't block on age — fall through to the rest of the checks; never guess an age.

**If the named player already answered REJECTED or NOT_ATTENDING to an invitation from this same inviter for this same tournament** — refuse a re-invite:

> *Ta osoba już odpowiedziała na zaproszenie na ten turniej.*
> *Wpisz imię i nazwisko innej osoby.*

"Rejection is instant and free — the inviter may immediately invite someone else" (see "Invitation engine") still holds, but for someone **else** — not the same person again, for the same tournament. This applies to NOT_ATTENDING too, even though NOT_ATTENDING otherwise carries no other memory (see "Spec change: a third invitation response"): it still blocks *this one inviter* from re-asking *this one player* for *this one tournament*. It does not block anyone else from inviting that player, and does not stop the named player from turning around and inviting the original inviter back — the block is directional, one ordered pair, one tournament. Enforced twice: once here as a friendly pre-check, and again inside the send transaction (`SendFailure.ALREADY_ANSWERED`), since the answer may have landed moments after this check ran.

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
- Rejection is instant and free. The inviter may immediately invite someone else — someone **else**, not the same person again for the same tournament (see "Pre-invitation checks", the re-invite block).
- Responding "Nie jadę na ten turniej" is instant and free too, exactly like rejection — the inviter may immediately invite someone else, same "not the same person again" limit. See "Spec change: a third invitation response" below.

**Eligibility:**

- **Gender must match.** A Chłopcy event needs two boys. Refuse and explain.
- The tournament must have a `Gra podwójna` event.
- **A player may play up but never down.** Age category is enforced as a ceiling, not an exact match: a younger player may enter an older draw, but the named player's own derived age category (see "Tournament selection") may not be older than the tournament's. Unenforceable when the named player has no ranking rows at all — never guess an age.

**Spec change: a third invitation response.** *(Documented now; not built until step 7 — do not implement this yet.)*

An invitation gets a third button alongside Zatwierdź and Odrzuć: **"Nie jadę na ten turniej"**.

- `NOT_ATTENDING` closes that one invitation and nothing else.
- It is explicitly **not** a stored fact about the player and the tournament in general: it must not block, hide or filter any future invitation to that player for that tournament **from someone else**. Players change their minds, enter late, and withdraw. Do not design a "not attending" table or flag — this is purely a terminal state on the one `Invitation` row. The one narrow exception is the re-invite block (step 8.3, "Pre-invitation checks"): the *same* inviter may not re-ask the *same* player for the *same* tournament, exactly as a rejection also blocks.
- The invitee sees: *"Odpowiedziałeś, że nie jedziesz na ten turniej."*
- The inviter sees a status worded distinctly from a refusal, same colour: 🔴 *"Peter Lorenz nie jedzie na ten turniej."*
- The inviter may immediately invite someone else, exactly as with rejection — someone else, not this same player again for this tournament.

---

## Status display — "Moje deble"

One place a player sees every invitation they have sent or received, and what happened to it. Reachable three ways: the `/moje_deble` command, "Moje deble" from the [Menu] chooser every terminal message opens (see "Buttons only at the end" below), and the "Moje deble" button carried directly by the age-category screen.

The summary message opens with a short heading (`Moje deble`) as its first line, so a player scrolling back through the chat knows what they're looking at without having to reread it — the age-category screen gets the same treatment, headed `Znajdź partnera`. A heading, not a paragraph.

Two collapsing rules apply before anything is rendered:

- **A match hides everything else.** If a tournament has a confirmed partner, show ONLY that line for that tournament — the match is locked, so an older rejection or an invitation to a third player that never went anywhere is dead history, not something to leave on screen underneath it.
- **Repeats collapse to the latest.** Two players can invite each other back and forth at the same tournament (a rejection or "nie jadę" is free and instant) — collapse to one line per (tournament, other player), showing only the most recent state, whichever direction it happened to be in.

**Ordering is activity order, oldest first, newest last** — not tournament date. The most recently touched thing sits at the bottom, nearest the input box the player is looking at. Tournament groups are ordered by their own most recent activity; within a group, whatever survives collapsing is ordered the same way. "Activity" means the last state change on a row (`updated_at`), not when it was created — a fresh PENDING send and a just-answered REJECTED both count as "recent" the same way.

```
Moje deble

SS Kraków - 05.09.2026
🟠 Zaproszenie od: Wiktoria Wójcik

OTK Zielona Góra - 29.08.2026
🟠 Wysłane do: Maja Nowak
🔴 Odmowa: Bartosz Nowak

WTK Uniejów - 22.08.2026
🟢 Gracie razem: Jagoda Szewczyk
```

*(Groups above are ordered by their own last activity, oldest first — not by the tournament dates shown, which happen to run the other way in this example.)*

Colours — one lookup (`bot.formatting.STATUS_EMOJI`), every message routes through it, no literal status emoji anywhere else:

- 🟠 pending (sent or received, not yet answered)
- 🔴 not happening (rejected, or not attending — the wording carries which, the colour doesn't need to)
- 🟢 matched

**Button icons.** Telegram's inline-keyboard buttons have no colour or style field, so the three invitation answers and Menu carry a leading emoji instead: ✅ Zatwierdź, ❌ Odrzuć, ⛔ Nie jadę na ten turniej, 🔵 Menu — everywhere these actions appear, including the per-invitation follow-up messages here. Every other button (Znajdź partnera, Moje deble, Zmień miejscowość, Zmień kategorię wiekową, the tournament/category lists) stays plain — if everything is decorated, nothing stands out.

Both directions are shown — invitations this player sent and ones they received — and direction is carried by the phrase at the *start* of the line, not a trailing explanation: `Wysłane do: {name}` for a sent one, `Zaproszenie od: {name}` for a received one, `Odmowa: {name}` when they refused a sent invitation, and so on — status word first, name last, one line each. A matched line (`Gracie razem: {name}`) is symmetric regardless of who invited whom.

**A pending received invitation can't hang its buttons off the summary.** There can be more than one, and a single message can't carry more than one invitation's worth of buttons unambiguously. So: the summary is sent as one message, then every still-open received invitation gets its own follow-up message, each carrying the same four-button invitation keyboard the original notification carries — Zatwierdź / Odrzuć / "Nie jadę na ten turniej" / Menu — reusing step 7's own callback classes and handlers unchanged. No follow-up messages at all when there is nothing pending to answer. A player who dismissed the original notification is not stuck hunting for it.

**What it hides.** Only tournaments that have not finished. Use `date_to` where present, otherwise `date_from`; a tournament is over at the end of that day, Europe/Warsaw. Nothing is deleted from the database — this is a display filter only, so past invitations stay available for the results-based verification planned later. Invitations cancelled automatically when someone else accepted are noise, not history, and are never listed — the player was already told at the time.

**Empty state.** If there is nothing to show, say so plainly and offer "Znajdź partnera" (not "Moje deble" — that would point back at the same empty screen). The non-empty summary message gets the same single "Znajdź partnera" button, for the same reason.

**Never** reveals who a third party's partner is — only this player's own matches. If another player is matched with someone else at a tournament, this view never names that someone else.

**Buttons only at the end.** "Never dead-end" (see "Tournament selection") does not mean every message needs a keyboard — a mid-flow prompt like "Wpisz imię i nazwisko osoby, z którą chcesz grać." followed by navigation buttons is clutter that invites mis-taps, since those buttons would abandon the flow the player is already in.

The rule: a message carries the `[Menu]` navigation button (`bot.keyboards.navigation.terminal_keyboard`) only when the journey has **ended** and the player has no next step in the current flow — a sent invitation, an accept/reject/"nie jadę" outcome on either side, "ten zawodnik znalazł już partnera", "masz już partnera na ten turniej", zero tournaments eligible for a category, the Moje deble summary, or any refusal that genuinely ends the attempt (tells the player to wait, not to type again). A **mid-flow** message — the next thing expected is the player typing or tapping something in the same flow, including a refusal that says "Wpisz imię i nazwisko innej osoby" — carries no navigation button at all; if it already has flow-specific buttons of its own (a tournament list, a category list, a disambiguation list, "Zmień miejscowość", "Zmień kategorię wiekową", "Pokaż wszystkie turnieje"), those stay and nothing is added.

Tapping `[Menu]` opens one small chooser message with `[Znajdź partnera]` and `[Moje deble]` — one navigation entry point instead of two buttons stamped on every terminal screen. `Znajdź partnera` returns the player straight to the age-category screen. `/start` must never be the only way forward.

`tests/test_no_dead_ends.py` checks this mechanically for every statically-traceable message (one passed to `t()` with a literal locale key) across `bot/`: a message on the terminal list must carry some navigation keyboard, and a message on the mid-flow list must never carry `[Menu]`. Messages composed by helper functions (`sent_text()`, `matched_text()`, ...) or chosen through a dict keyed by an enum aren't traceable this way and are instead covered by the handler-level tests in `tests/test_*_db.py`, which assert the actual buttons a real handler call produces.

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
