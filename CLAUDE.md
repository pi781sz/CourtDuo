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

1. **No free-text messaging between users. Ever.** Every interaction is inline keyboard buttons, the persistent reply keyboard, and pre-defined messages. No chat, no message relay, no "add a note" field. An invitation carries only: inviter name, tournament, date, and buttons — Zatwierdź, Odrzuć, (per the spec change under "Invitation engine") Nie jadę na ten turniej. The recipient can step away without answering at any time via the persistent reply keyboard (see "Navigation") — the invitation stays PENDING either way.

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

**Read-only viewers (step 10, allowlisted test feature) qualify this rule — they don't break it.** "One Telegram account = one PZT player" still holds for *ownership*: a viewer is not a second player bound to the account, and does not change who the account belongs to. It's a separate, read-only relationship layered on top — a parent or coach who wants to see how partner search is going, without being able to act.

A player may grant up to **3** other Telegram accounts read-only visibility of their own activity: a copy of every notification they receive or trigger, and a read-only Moje deble. Granting is always the player's own action, from inside their own account — a single-use, 24-hour deep-link token they hand to whoever they choose — and the player can see and revoke any of their granted viewers at any time, taking effect immediately. There is no admin path: an operator can never attach a viewer by editing the database. The player is notified whenever a viewer is added or revoked, so access can never be silent.

A viewer can never send, accept, reject, cancel, or name a partner as the player, and can never see anything about any player other than the one who granted access — enforced server-side (`bot.middlewares.viewer_guard`), not by hiding buttons. A `viewer_telegram_id` may also be a registered player in their own right; the two roles are independent, and using the bot normally, they are always themselves.

This is free and allowlisted for now — only accounts whose `pzt_id` appears in `VIEWER_ALLOWLIST_PZT_IDS` (an environment variable; never a PZT id committed to this repo, per rule 4) see the Podgląd option at all. Gated through `entitlements.can_use_viewers`, alongside `can_send_invitation`, so a future paid tier changes one function. Everyone else's bot is completely unchanged.

**Step 10.1: which persistent keyboard, decided by whose account is in play.** Live testing found a viewer-only Telegram account seeing the player's own persistent keyboard, Znajdź partnera included — a flow it can never complete. The fix is one boolean, checked wherever a persistent reply keyboard would be sent, never a hidden button on a shared keyboard: does *this Telegram account* have its own `Account` row?
- Yes → `bot.keyboards.navigation.persistent_menu_keyboard`, always, unconditionally — a registered player acts as themselves, in their own flows and while looking at someone else's read-only data alike. Nothing ever swaps it away, so "a way back to their own account" is trivial: they never left it, and their own "Moje deble" tap already resolves to their own data first (`bot.handlers.moje_deble`) regardless of any viewer grant they also hold.
- No → `bot.keyboards.navigation.viewer_menu_keyboard` — one label, "Moje deble", which for an account-less Telegram id already opens the read-only Moje deble (`bot.handlers.viewers.render_moje_deble_for_viewer`). No Znajdź partnera, no Zaproś na CourtDuo, no partner search of any kind.

Attached everywhere a pure-viewer Telegram id can first see a keyboard: the viewer-bind confirmation (`viewer.bound`, step 10's own deep-link flow), a pure viewer's own `/start` (which now shows their read-only view directly rather than starting PZT-id registration on an account that will never own a player), and every render of `render_readonly_moje_deble` when the viewer looking has no `Account` of their own. Server-side guards (`bot.middlewares.viewer_guard`) are unaffected and still reject any action callback from a viewer regardless of which keyboard they were shown.

**Podgląd screen copy (step 10.1, reworded by step 10.2):**

```
Podgląd konta CourtDuo

Możesz udostępnić maksymalnie 3 osobom. Osoba z dostępem widzi Twoje
powiadomienia i Twoje deble, ale nie może niczego wysyłać ani odpowiadać za
Ciebie.

Nikt nie ma jeszcze dostępu do podglądu.
```

(the last line is the empty state; the existing viewer list renders in its place when grants exist — see "which viewer" just below). Below the explanation and the list sits exactly **one** button, `viewer.share_button` — "Udostępnij podgląd mojego konta" — CLAUDE.md step 10.2, PROBLEM 1: an earlier build had left both this button *and* a second, separate "create" flow live at once, stacked. Tapping it generates the token and sends **one** message carrying the share buttons, reusing `bot.keyboards.invite_friend.share_keyboard` rather than a second WhatsApp/Telegram builder:

```
Wyślij link z dostępem

Link jest jednorazowy i ważny 24 godziny.
[WhatsApp]  [Telegram]
```

(step 10.2, PROBLEM 2: no trailing colon on the first line). The share text itself: *"Zapraszam Cię do podglądu mojego konta CourtDuo. Link jednorazowy i ważny 24 godziny. {link}"* — the player's own name never goes into it (rule 2's spirit: a share message may be forwarded to anyone, and this one grants access to a child's account) — only the link does. The token itself is unchanged: still generated on demand, still single-use, still 24 hours. On acceptance the player is told: *"{telegram_name} ma teraz dostęp do podglądu Twojego konta CourtDuo."*

**Which viewer (step 10.2, PROBLEM 3).** The list must say who each grant belongs to, not just a numbered slot and a date — a player has to be able to tell one viewer from another before deciding whom to remove. `account_viewers.viewer_display_name` captures the viewer's own Telegram display name once, at bind time (`bot.viewers.bind_viewer`), and the list shows it: `1. Piotr Polska — dostęp od 09.08.2026`. A grant made before this column existed (or one bound with no name for any other reason) falls back to the plain numbered form, `1. dostęp od 09.08.2026`, rather than showing a raw Telegram id. The revoke button reads `viewer.revoke_button` — "Skasuj dostęp #{index}" (not "Odwołaj").

**Discoverability (step 10.2, PROBLEM 4).** `/podglad` still works exactly as before, but a fourth row is now shown on the persistent reply keyboard *only* for accounts `entitlements.can_use_viewers` allows:

```
[Znajdź partnera]
[Moje deble]  [Zaproś na CourtDuo]
[Podgląd konta]
```

`bot.keyboards.navigation.persistent_menu_keyboard` takes a `show_podglad` flag for this — every call site that sends the keyboard passes `can_use_viewers(account)` wherever an `Account` is in scope, so the row appears and disappears consistently across every screen rather than only some. Tapping the label opens the exact same `_render_menu` screen the command does. Everyone else's keyboard is unchanged: three buttons, exactly as before. A viewer-only account (no `Account` row of its own) still gets `viewer_menu_keyboard` and never sees this row either way — this only ever governs the fourth row of a registered player's own keyboard, and "Step 10's Podgląd menu is deliberately not a fourth label here" above is superseded by this gated version.

**Name order: storage is PZT's, display is not.** PZT stores names "Nazwisko Imię" (surname first) — `accounts.full_name` and `players.full_name` keep that order permanently, and name matching (see "Tournament selection" → partner name entry) accepts either order. But every user-facing message must show "Imię Nazwisko" instead: "Szewczyk Jagoda" → "Jagoda Szewczyk". `core.text.display_name` does this reordering (first token is the surname, every remaining token is a given name) and every place a player's name is shown — invitations, accept/reject/not-attending notifications, "already has a partner" checks, disambiguation buttons — must go through it. `core.text.first_name`, used only for the player's own welcome greeting, returns just the first given name — the *second* token, since the first is the surname.

---

## Navigation

**A persistent reply keyboard, not an inline [Menu] button.** The keyboard that sits below the text input and stays there between messages (`ReplyKeyboardMarkup`, `resize_keyboard` + `is_persistent`):

```
[Znajdź partnera]
[Moje deble]  [Zaproś na CourtDuo]
```

Attached on `/start` — for a brand new registration, on the very first greeting; for a returning player, on the greeting that precedes the age-category screen — but **not only there** (step 8.5: a keyboard sent exactly once, on `/start`, left every other entry into the bot without one — `/moje_deble` typed before `/start` ever ran, or a push notification landing in a chat the reply keyboard hadn't reached yet). It is re-attached on every plain-text reply that can plausibly be a player's first message of a session: the `/moje_deble` fallback shown before an account exists, every unprompted push (a new invitation's answer, an accept/reject/"nie jadę" notification, a cancelled-by-match notice), and every reply an invitee gets to their own tap. It is *not* re-attached on a message that already needs an inline keyboard of its own (a category list, a confirmation screen, the three invitation-answer buttons) — Telegram allows exactly one `reply_markup` per message, inline and reply keyboards can't share one, and once shown the reply keyboard stays visible under messages that carry an inline one too (the two are separate layers). Tapping a label sends it back as an ordinary text message; `bot.i18n.all_translations` matches that text against every locale's rendering of the label (not just the account's own language), and those handlers are registered ahead of the state-scoped ones (place, partner name, PZT id) so a tap always wins even mid-flow.

**Step 8.7:** a brand new registration's "very first greeting" (`Cześć!`, before the PZT id prompt) is not the only attachment point for a new player any more — the `Witaj {imię}.` message that completes registration, immediately before the age-category screen, now carries it too. That message is the new player's actual equivalent of "the greeting that precedes the age-category screen" the returning-player rule already names; the original attachment two messages earlier fires before the player has typed anything, so re-asserting the keyboard right before it's needed closes the gap rather than depending on the first attempt alone. This is the same "not only in one place" principle step 8.5 already established for other entry points, applied to the one step 8.4 and 8.5 both missed.

**Belt and braces (step 8.7):** the reply keyboard, even correctly attached with `is_persistent`, can still be collapsed by the player via Telegram's own keyboard icon, and Telegram remembers that per chat — no server-side flag prevents it. So the invitation-send confirmation ("Zaproszenie zostało wysłane. Czekaj na odpowiedź.") — the one screen a player has just acted on and is most likely to want to check next — also carries its own **inline** `[Moje deble]` button (`bot.keyboards.navigation.invitation_sent_keyboard`, reusing `MojeDebleCallback`). Inline buttons can't be collapsed. This is deliberately not added anywhere else — step 8.2 already established that mid-flow inline clutter is worse than the dead end it solves, and every other message either already carries the reply keyboard or an inline keyboard of its own.

This replaces the inline `[Menu]` button and its two-option chooser that earlier steps used: no message anywhere needs a navigation button of its own any more, because these actions are already one tap away, always. Inline keyboards for actual **choices** — category buttons, tournament lists, disambiguation, the invitation's three answer buttons — stay inline and unchanged; the reply keyboard only ever carries these fixed actions (three for everyone, a gated fourth for some — see step 10.2 immediately below).

**Step 10's Podgląd menu was deliberately not a fourth label here — superseded by step 10.2.** The original reasoning: reachable only via `/podglad`, same as `/moje_deble` is reachable by command independent of its reply-keyboard label; the reply keyboard is shown to every player regardless of the allowlist, so adding a label for a feature most accounts can't use would need the keyboard to become allowlist-aware. Live testing found that reasoning left the feature undiscoverable — an allowlisted player has no way to learn `/podglad` exists at all. Step 10.2 makes the keyboard allowlist-aware after all, but only for this one row: `bot.keyboards.navigation.persistent_menu_keyboard(lang, show_podglad)` adds `[Podgląd konta]` as a fourth row exactly when `entitlements.can_use_viewers(account)` is true, gated at the one place the keyboard is built, not per call site. `/podglad` keeps working unchanged as a command; the label opens the identical screen. This is about a registered player's own persistent keyboard specifically — see "Identity", step 10.1, for the separate, narrower keyboard a Telegram account with no player account of its own gets instead, which this does not touch.

**Zaproś na CourtDuo** — a generic invite, unattached to any tournament or named player. Sends WhatsApp and Telegram share buttons (both plain `https://` URLs — Telegram inline buttons accept nothing else) pre-filled with a short Polish invitation and a link built from the bot's own username (`get_me()`, fetched at runtime — never hardcoded, so the same code is correct for the test and production bots). There is no SMS option at all (step 8.5 dropped it — an `sms:` inline button is rejected outright by Telegram, and the copyable-text-in-the-message-body workaround it had was more clutter than it was worth). The bot never sees, stores or handles a phone number here either (rule 2) — the recipient is chosen in the player's own phone/app. This is **not** step 9's flow: no `pending_external_invites` row, no "they joined" callback, nothing tournament- or player-specific. The same two buttons and share text are reused (still with no named player in the text — see "Pre-invitation checks") when a player names someone who exists in PZT's rankings but has no CourtDuo account yet, so that dead end isn't a total one either.

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
[Zatwierdź]  [Odrzuć]  [Nie jadę na ten turniej]
```

Peter's persistent reply keyboard (see "Navigation") is still there below the input box the whole time, so he can check something else first — look at Moje deble — without answering; the invitation stays PENDING and is answerable later from there (step 8.3).

**On Zatwierdź** — both see 🟢 with tournament, date and partner name. Adam gets an alert: *"Peter Lorenz przyjął zaproszenie."*

**On Odrzuć** — Peter sees 🔴 *"Odrzuciłeś zaproszenie od Adam Smith — <tournament>"*. Adam's status flips to 🔴 *odmowa* with the name and tournament.

**On Nie jadę na ten turniej** — Peter sees *"Odpowiedziałeś, że nie jedziesz na ten turniej."* Adam's status flips to 🔴 *"Peter Lorenz nie jedzie na ten turniej."* — the same colour as odmowa (step 8.3: "not happening" either way), the wording is what tells them apart. This closes that one invitation only — see "Spec change: a third invitation response" under Invitation engine — but per step 8.3's re-invite block, Adam may not send Peter a second invitation for this tournament; he's free to invite someone else immediately.

### Scenario 2 — the invited player is not on CourtDuo

Identical until the name is entered. Then:

```
Bot:   Peter Lorenz nie używa CourtDuo. Wyślij mu zaproszenie:
       [WhatsApp]  [Telegram]
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
> *[Zatwierdź]  [Odrzuć]  [Nie jadę na ten turniej]*

Reuses the exact invitation, the exact wording, and the exact three-button keyboard the original notification carries — the player can simply accept it. Enforced twice: once here as a friendly pre-check, and again inside the send transaction itself (`SendFailure.ALREADY_INVITED_BY_INVITEE`), since the other player may have sent their invitation moments after this check ran.

**If the named player's gender does not match the event:** refuse and explain.

**If the named player's own age category is older than the tournament's** — a player may play up but never down (see "Tournament selection"):

> *Amelia Nowak nie może grać w kategorii U14.*
> *Wpisz imię i nazwisko innej osoby.*

Checked **before** the "does not use CourtDuo yet" refusal (scenario 2) — live testing showed a too-old player being told "nie używa jeszcze CourtDuo", which is true but not the reason that matters; the age reason is the real one and must be shown first. If the named player has no ranking rows at all, don't block on age — fall through to the rest of the checks; never guess an age.

**"Does not use CourtDuo yet" isn't a total dead end either (step 8.5, PROBLEM 4).** Scenario 2's own flow (a stored pending invite, the "they joined" notification) is still build order step 9 — until then, this message carries the same WhatsApp/Telegram share buttons as "Zaproś na CourtDuo" (same generic share text, same link built from `get_me()`). The named player's name never goes into that share text or its buttons: the message could end up sent to anyone, and the bot must not be the one revealing who it was really meant for (rule 2). Since the share buttons sit right below it (step 8.6, CHANGE 1), the message points at them rather than asking the inviter to type another name — *"{Imię Nazwisko} nie używa jeszcze CourtDuo. Zaproś {ją/go} poniżej przez wybraną aplikację."* — with the pronoun matched to the **named player's own** gender (`players.gender`, the only gender CourtDuo has for someone with no account of their own), via two locale keys chosen at runtime.

**If the named player already answered REJECTED or NOT_ATTENDING to an invitation from this same inviter for this same tournament** — refuse a re-invite:

> *Ta osoba już odpowiedziała na zaproszenie na ten turniej.*
> *Wpisz imię i nazwisko innej osoby.*

"Rejection is instant and free — the inviter may immediately invite someone else" (see "Invitation engine") still holds, but for someone **else** — not the same person again, for the same tournament. This applies to NOT_ATTENDING too, even though NOT_ATTENDING otherwise carries no other memory (see "Spec change: a third invitation response"): it still blocks *this one inviter* from re-asking *this one player* for *this one tournament*. It does not block anyone else from inviting that player, and does not stop the named player from turning around and inviting the original inviter back — the block is directional, one ordered pair, one tournament. Enforced twice: once here as a friendly pre-check, and again inside the send transaction (`SendFailure.ALREADY_ANSWERED`), since the answer may have landed moments after this check ran.

**CANCELLED is not part of this block (step 8.6, CHANGE 3).** `db.crud.get_answered_invitation` only matches REJECTED and NOT_ATTENDING — a PENDING invitation the inviter withdrew themselves (see "Invitation engine", "A PENDING invitation may be withdrawn by its own sender") never enters that set, so the inviter may immediately re-invite the same person for the same tournament. The distinction is who decided: REJECTED/NOT_ATTENDING are the *other* player's decision and re-asking is pestering; CANCELLED is the inviter's own change of mind, so a fresh attempt is reasonable.

These checks are a courtesy, not a guarantee — the named player may accept someone else a second later. The atomic lock at accept time is what protects the data. Both are required.

---

## Invitation engine

The part most likely to break. Be careful.

**States:** `PENDING` → `ACCEPTED` | `REJECTED` | `NOT_ATTENDING` | `CANCELLED` | `EXPIRED`

**Rules:**

- A player may have up to **3 pending outgoing invitations** per tournament.
- **First accept wins.** On acceptance, all other pending invitations for **both** players at that tournament are cancelled. Each cancelled recipient is told: *"Ten zawodnik znalazł już partnera."*
- **Atomic locking is mandatory.** The accept transaction must `SELECT … FOR UPDATE` the relevant invitation rows, re-verify neither player is already matched at that tournament, then commit. Without this you will eventually double-book someone.
- **A confirmed match is locked.** Neither side can cancel or change partner. Both are warned of this *before* confirming — the inviter on the confirmation screen, the invitee in the invitation itself. This still holds after step 8.6: cancellation only ever reaches a PENDING invitation, never an ACCEPTED one — `bot.invitation_engine.cancel_invitation` re-verifies the state inside its own lock and refuses (reporting the real outcome instead) if the invitee accepted a moment before the cancel transaction started. **The one exception (step 12):** when a player deletes their own CourtDuo account, their confirmed matches are deliberately *not* cancelled by that deletion — but the player left behind may release the pairing themselves, manually, once they've actually confirmed in person that they're no longer playing together. See "Account deletion and blocking" below for why this doesn't weaken the rule: it exists to stop one party unilaterally walking away from a commitment, and that reasoning doesn't hold once one party no longer exists in the system to walk away from anything.
- **A PENDING invitation may be withdrawn by its own sender (step 8.6).** Only the inviter, and only while it is still PENDING — the invitee answers, they do not cancel, and gets no cancel button of their own. Re-verified inside the cancel transaction's own single-row lock (the same shape as Odrzuć/"Nie jadę na ten turniej"), since the invitee may answer it a moment before the cancel lands; if that happens the inviter is told what the answer was instead of a silent no-op. The invitee is notified (`<Imię Nazwisko> wycofał/wycofała zaproszenie — <tournament>`, gendered on the *inviter*), and if their original invitation message is still editable, its three answer buttons are stripped via `edit_message_reply_markup` — best-effort only, since Telegram refuses to edit messages past a certain age; the transaction's own re-check is what actually prevents a stale answer, not the edit. A cancelled invitation frees the slot it held: it no longer counts toward the inviter's 3-pending limit, and — unlike REJECTED or NOT_ATTENDING — does **not** block the inviter from re-inviting the same person for the same tournament, since a cancellation is the inviter's own change of mind rather than the other player's decision (see "Pre-invitation checks", the re-invite block). Cancelled invitations stay hidden from Moje deble, same as any other CANCELLED row.
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

One place a player sees every invitation they have sent or received, and what happened to it. Reachable two ways: the `/moje_deble` command and the "Moje deble" label on the persistent reply keyboard (see "Navigation"). **Step 12.1, PROBLEM 6** removed the third: the age-category screen's own inline "Moje deble" (and "Znajdź partnera") button, added by build order step 8 — live testing found it duplicating the persistent keyboard while sitting inside a grid of real choices (the category buttons), where a mis-tap could lose the player's place. See "Navigation" and "Tournament selection" below.

The summary message opens with a short heading (`Moje deble`) as its first line, so a player scrolling back through the chat knows what they're looking at without having to reread it — the age-category screen gets the same treatment, headed `Znajdź partnera`. A heading, not a paragraph.

Two collapsing rules apply before anything is rendered:

- **A match hides everything else.** If a tournament has a confirmed partner, show ONLY that line for that tournament — the match is locked, so an older rejection or an invitation to a third player that never went anywhere is dead history, not something to leave on screen underneath it.
- **Repeats collapse to the latest.** Two players can invite each other back and forth at the same tournament (a rejection or "nie jadę" is free and instant) — collapse to one line per (tournament, other player), showing only the most recent state, whichever direction it happened to be in.

**Ordering is activity order, oldest first, newest last** — not tournament date. The most recently touched thing sits at the bottom, nearest the input box the player is looking at. Tournament groups are ordered by their own most recent activity; within a group, whatever survives collapsing is ordered the same way. "Activity" means the last state change on a row (`updated_at`), not when it was created — a fresh PENDING send and a just-answered REJECTED both count as "recent" the same way.

```
Moje deble

OTK Zielona Góra - 29.08.2026
🟠 Maja Nowak — wysłane
🔴 Bartosz Nowak — odmowa

WTK Uniejów - 22.08.2026
🟢 Jagoda Szewczyk — gracie razem
```

*(Groups above are ordered by their own last activity, oldest first — not by the tournament dates shown, which happen to run the other way in this example. A still-open* received *invitation — say, one from Wiktoria Wójcik at SS Kraków — is never part of this body at all, no matter how recent: see "A pending received invitation can't hang its buttons off the summary" just below. If SS Kraków had nothing else going on, its heading would not appear here either.)*

Colours — one lookup (`bot.formatting.STATUS_EMOJI`), every message routes through it, no literal status emoji anywhere else:

- 🟠 pending (sent or received, not yet answered)
- 🔴 not happening (rejected, or not attending — the wording carries which, the colour doesn't need to)
- 🟢 matched

**No button icons.** The three invitation answers — Zatwierdź, Odrzuć, Nie jadę na ten turniej — are plain text, same as every other button (Znajdź partnera, Moje deble, Zmień miejscowość, Zmień kategorię wiekową, the tournament/category lists). Status colour lives in the message *text* (🟠/🔴/🟢 via `STATUS_EMOJI`, above) — decorating the buttons too just crowds the keyboard without adding information.

Both directions are shown — invitations this player sent and ones they received — and the name leads every line, status word after it: `{name} — wysłane` for a sent one, `{name} — zaprasza` for a received one, `{name} — odmowa` when they refused a sent invitation, and so on — name first, status last, one line each. The name is what a player scans for; direction still reads unambiguously off the status word alone. A matched line (`{name} — gracie razem`) is symmetric regardless of who invited whom. This same name-first order applies anywhere else a name and status appear together, not just here.

**A pending received invitation can't hang its buttons off the summary.** There can be more than one, and a single message can't carry more than one invitation's worth of buttons unambiguously. So: every still-open received invitation gets its own follow-up message, carrying the same three-button invitation keyboard the original notification carries — Zatwierdź / Odrzuć / "Nie jadę na ten turniej" — reusing step 7's own callback classes and handlers unchanged. No follow-up messages at all when there is nothing pending to answer. A player who dismissed the original notification is not stuck hunting for it — the persistent reply keyboard (see "Navigation") gets them back to Moje deble any time.

**Step 8.8 (no-duplicate-lines fix):** live testing found a still-open received invitation's line rendered twice — once in the summary body, once again as the whole text of its own follow-up message just below it, there purely so the follow-up had something to say. `bot.moje_deble.summary_groups` now leaves a still-open received entry out of the summary body entirely — its follow-up message is the only place its line appears. If that omission leaves a tournament group with no lines left under its heading, the group is dropped from the summary too (a heading with nothing under it is never rendered) — so a tournament whose only entry is a received invitation doesn't appear in the summary at all, only in its own follow-up message. If it leaves the *whole* summary with no groups left, no summary message is sent at all — a heading-only or falsely-empty message would only confuse a player about to be asked, right below it, to answer something.

**A pending sent invitation (step 8.6, reworked by step 8.8) never gets a follow-up message.** Step 8.6 originally gave it the same follow-up-message treatment as a received one, with a single "Anuluj zaproszenie" button instead of the three answers. Step 8.8 found that follow-up message repeating the summary's own line purely to hang the button on it — the exact bug step 12.1, PROBLEM 4 had already fixed once for a stranded match's "Usuń" button (see "Account deletion and blocking" below) — and applied the same fix here: the line stays exactly where it already was, in the summary body, and its cancel button rides on the summary message's own keyboard instead (`bot.keyboards.navigation.moje_deble_summary_keyboard`), one per still-open sent invitation, labelled with the partner's name so several are unambiguous — `Anuluj: {name}` (`invitation.cancel_named_button`), name in "Imię Nazwisko" order like everywhere else. Reuses `CancelInvitationCallback` and its existing handler unchanged; only where the button lives changed, not what tapping it does. Never both kinds of button on the same invitation: a received pending entry gets only the follow-up message's answer keyboard, a sent pending entry gets only its named cancel button on the summary.

**What it hides.** Only tournaments that have not finished. Use `date_to` where present, otherwise `date_from`; a tournament is over at the end of that day, Europe/Warsaw. Nothing is deleted from the database — this is a display filter only, so past invitations stay available for the results-based verification planned later. Invitations cancelled automatically when someone else accepted are noise, not history, and are never listed — the player was already told at the time.

**Empty state (reworked by step 12.2).** If there is nothing to show, say so plainly — no inline keyboard at all. Earlier builds offered a "Znajdź partnera" inline button here (and the same button on the non-empty summary message too), reasoning it shouldn't be "Moje deble" since that would point back at the same screen; live testing found the real bug one level up — "Znajdź partnera" was *already* sitting right there on the always-visible persistent reply keyboard below the input box, so the inline button was never a safer alternative, it was a plain duplicate, stacked directly under the real one. Both are gone. See "No message needs a navigation button of its own" just below — the persistent keyboard is the only place any of these three actions live now, full stop.

**Never** reveals who a third party's partner is — only this player's own matches. If another player is matched with someone else at a tournament, this view never names that someone else.

**No message needs a navigation button of its own.** Earlier steps attached an inline `[Menu]` button to every terminal message — one that ended a flow with nothing else to tap — since a mid-flow prompt like "Wpisz imię i nazwisko osoby, z którą chcesz grać." followed by navigation buttons is clutter that invites mis-taps, and there was otherwise no way back. The persistent reply keyboard (see "Navigation") replaces that entirely: it is always visible below the input box, on both terminal and mid-flow messages alike, so no individual message — terminal or mid-flow — carries a navigation button any more. A message keeps whatever flow-specific buttons it already had (a tournament list, a category list, a disambiguation list, "Zmień miejscowość", "Zmień kategorię wiekową", "Pokaż wszystkie turnieje", a received invitation's three answer buttons) and nothing else is added. (Step 8.8 moved the sent-invitation "Anuluj" button off its own message onto the summary's own keyboard, named per invitation — see "Status display" above — so it is no longer an example of a message's own flow-specific button.)

Build order step 8 itself broke this rule without anyone noticing: it added "Moje deble" and "Znajdź partnera" as two more buttons on the age-category screen's own inline keyboard — a grid otherwise made entirely of real choices (the category buttons). Step 12.1, PROBLEM 6 removed them once live testing showed the mis-tap risk this rule already warned about, and used the same audit to confirm every other inline keyboard under `bot/keyboards/` is clean. That audit was itself incomplete: it skipped `bot/keyboards/navigation.py` on the theory that its two "Znajdź partnera" buttons — `find_partner_keyboard` (Moje deble's empty state) and `moje_deble_summary_keyboard` (Moje deble's non-empty summary) — were deliberate, documented exceptions rather than the same mistake in a different file. **Step 12.2** found otherwise: live testing showed a player looking at the non-empty Moje deble summary and seeing "Znajdź partnera" twice, once as the message's own inline button and once immediately below it on the persistent reply keyboard. Both were removed — `find_partner_keyboard` no longer exists, and `moje_deble_summary_keyboard` now carries only entry-specific buttons (one "Usuń" per stranded match, see "Account deletion and blocking" below, plus — since step 8.8 — one named "Anuluj: {name}" per still-open sent invitation, see "Status display" above), returning no keyboard at all when there's nothing stranded or still-open-sent to act on. `FindPartnerCallback` itself stays defined and handled, purely so a message sent before this change and still carrying the old button keeps working when tapped — no keyboard in this codebase builds one any more. The one keyboard that still deliberately duplicates a persistent-keyboard action is `invitation_sent_keyboard` (step 8.7's belt-and-braces inline "Moje deble" on "Zaproszenie zostało wysłane") — kept because the persistent keyboard itself can be collapsed by the player and this is the one screen they're most likely to need it right after. `tests/test_no_navigation_in_choice_keyboards.py` now audits every function in every file under `bot/keyboards/`, `navigation.py` included, against that one named exception, rather than exempting a whole file by name.

`/start` must never be the only way forward — it isn't: `Znajdź partnera` on the persistent keyboard returns the player straight to the age-category screen from anywhere.

`tests/test_no_dead_ends.py` checks mechanically that none of the old inline-`[Menu]` machinery (`MenuCallback`, `terminal_keyboard`, `menu_keyboard`, the literal "🔵 Menu" button text) has crept back in anywhere under `bot/`. Actual button contents on any given message are covered by the handler-level tests in `tests/test_*_db.py` and the keyboard-builder tests in `tests/test_*_keyboards.py`, which assert what a real handler call or keyboard builder actually produces.

---

## Account deletion and blocking

Deleting an account alone is not enough — a deleted player could re-register in seconds with the same PZT id, so blocking is a second, deliberately separate mechanism. GDPR erasure has to be possible, and the data involved is children's names.

### Self-service deletion

A player deletes their own account from inside the bot — `/usun_konto`. This must not depend on an operator being awake, so there is no operator-only path for the normal case (see "Blocking" below for the one thing that genuinely does require a human at psql).

Two-step confirmation, both screens inline-keyboard only (rule 1): the first states plainly what is about to happen — the account goes, pending invitations sent and received are cancelled and the other side told, confirmed matches are **not** cancelled — and ends with "Tej operacji nie można cofnąć." Only the second screen's tap actually deletes anything.

**Step 12.1, PROBLEM 2:** the viewer-access bullet is shown only when the account actually has at least one active viewer grant to lose (`db.crud.count_active_viewers`) — viewers are an allowlisted test feature almost nobody has, so stating its removal unconditionally read as a confusing line about a feature the player had never seen. An account with no active viewers never sees that bullet; an account with one or more still does, worded exactly as before.

On deletion:

- The `accounts` row is deleted, along with every `account_viewers` grant and `viewer_invite_tokens` row for it (both carry `ON DELETE CASCADE` foreign keys to `accounts.id`, so this is automatic).
- Every PENDING invitation this account **sent** is cancelled; each invitee is told, in the same wording regardless of direction: *"{Imię Nazwisko} usunął/usunęła swoje konto CourtDuo. Zaproszenie na {turniej} zostało anulowane."*
- Every PENDING invitation this account **received** gets the identical treatment, symmetrically — the inviter is told the same way.
- Every **CONFIRMED** (ACCEPTED) match is left exactly as it was — see below.
- Every `pending_external_invites` row where this account was the **inviter** (their own "invite a non-user" attempts) is deleted. A row where this pzt_id is instead the *invitee* — someone else's still-open attempt to invite them — is not this player's own data and is left alone.
- The `players` row (name, club, ranking history — scraped from PZT's own public pages) is **never** touched. It isn't CourtDuo's data to erase; it's public roster data that exists independently of whether this pzt_id ever had a CourtDuo account, and the scraper will simply re-write it again on its next run regardless.

### What happens to a confirmed partner

This is the part that touches a real family, so it gets its own careful treatment, not a side effect of the deletion above.

The remaining player is told:

> *{Imię Nazwisko} usunął/usunęła swoje konto CourtDuo.*
> *Potwierdź z nim/z nią osobiście, czy nadal gracie razem.*

— gendered on the *deleted* player's own gender (usunął/usunęła), which is the one thing the remaining player is entitled to be told about them. (Step 12.2 shortened the second line — "na tym turnieju" was dropped as redundant: this notification only ever fires for the one tournament the match belongs to, so naming it added nothing.)

The match's `Invitation` row is **not** cancelled, and the remaining player is **not** automatically freed to invite somebody else. Deleting a CourtDuo account is not the same as withdrawing from the tournament — the deleted player may well still be playing, having simply stopped using the bot, and if CourtDuo silently released the pairing and the remaining player found a new partner, the deleted player could show up at the tournament expecting their original one. The bot has no way to know which is true, so it says so and lets the human decide.

In Moje deble, that tournament keeps its match line, but with a distinct status instead of 🟢 — same emoji-driven convention as everything else in that view (see "Status display"):

> ⚠️ *Jagoda Szewczyk — potwierdź osobiście*

The remaining player gets exactly one manual escape: a "Usuń" button (renamed from "Zwolnij parę" by step 12.1, PROBLEM 4) on that entry, behind its own two-step confirmation — "Czy na pewno chcesz usunąć tego debla?", `[Tak, usuń]` `[Anuluj]` — cancelling it replies plainly "Anulowane". Tapping through moves the invitation to `CANCELLED` — the same state a normal step 8.6 inviter-cancel leaves behind, so nothing else needs to change for the tournament to count as free again and for the remaining player to invite someone else there.

**Step 12.1, PROBLEM 4:** live testing found this entry rendered twice — the summary message showed the "potwierdź osobiście" line, and a second, separate follow-up message repeated the identical line purely to have somewhere to hang the "Usuń" button, the same pattern `bot.handlers.moje_deble` used at the time for every still-open invitation (pending was thought to genuinely need its own message, since several can be open at once and buttons could otherwise be ambiguous). A stranded match doesn't have that problem — the button unambiguously carries its own invitation id — so the button now rides on the summary message's own keyboard (`bot.keyboards.navigation.moje_deble_summary_keyboard`), one "Usuń" per stranded match. The line appears exactly once, in the summary, where it already belonged. (That keyboard originally also carried a "Znajdź partnera" button alongside the "Usuń" ones — step 12.2 removed it as a duplicate of the persistent reply keyboard's own label; see "No message needs a navigation button of its own" above.) **Step 8.8** later found the "ambiguous buttons" reasoning didn't actually apply to a still-open *sent* invitation either — it only ever carries the one unambiguous cancel button, exactly like a stranded match's "Usuń" — and applied this same fix to it too (see "Status display" above). A still-open *received* invitation is the one case that genuinely keeps its own follow-up message: three answer buttons per invitation really would be ambiguous stacked on a shared keyboard.

This is the single, explicitly documented exception to "Invitation engine"'s "a confirmed match is locked" rule. That rule exists to stop one party unilaterally walking away from a commitment the other side is relying on; it does not hold once one party has actually left the system, which is exactly the situation account deletion creates and exactly why the escape is manual, gated on the deletion having genuinely happened (`bot.invitation_engine.release_deleted_partner_match` re-verifies the other side's account is actually gone before allowing it), and available only to the player left behind — never to the one who deleted their own account, and never automatically.

### What is actually erased, and what is kept — and why

Erased outright: `telegram_id`, the account's own copy of `full_name`/`gender`/`pzt_id` (all of it, by deleting the `accounts` row itself), every viewer grant and invite token, and every `pending_external_invites` row this player was the inviter of.

Kept, deliberately: `Invitation` rows for tournaments that have not yet finished, carrying a **name snapshot** of the deleted player (`invitations.inviter_name_snapshot` / `invitee_name_snapshot`) taken at the moment of deletion. The other child in a confirmed match made a real commitment and needs to know who they're paired with — a "potwierdź osobiście" line with no name attached is useless to them, and CourtDuo already has a permanent, independent copy of that name sitting in `players.full_name` (PZT's own roster, never erased — see above) that Moje deble could have kept reading forever. It deliberately does not: the snapshot exists specifically so that *this* trace — "CourtDuo once told this specific other child which specific player they were paired with" — has a bounded lifetime of its own, decoupled from `players`, rather than living as long as PZT happens to keep scraping that name. `bot.moje_deble` reads the snapshot in preference to the live `players` join whenever one is present; `bot.registration.register_by_pzt_id` clears any snapshot for a pzt_id that registers again before it's purged, so a player who comes back sees a normal 🟢 match again rather than a stale warning.

Snapshots are purged — set back to `NULL` — once the tournament they belong to has finished (same "finished" definition Moje deble already uses: `date_to` where present, otherwise `date_from`, over at the end of that Europe/Warsaw day). This runs off the same 6-hour periodic loop the staleness check already uses (`bot.staleness`), not a scheduler of its own — one more query per tick, not a new moving part.

*A note on the reasoning above: this is a considered decision with a stated rationale, not a legal ruling. Neither the author of this document nor the person implementing it is a lawyer.*

### Blocking

A separate mechanism from deletion, on purpose — blocking must survive the very deletion above, and a deleted account's row is gone the moment that happens. A standalone table:

```
blocked_pzt_ids
  pzt_id      text primary key
  blocked_at  timestamptz not null
  reason      text null
```

Checked at registration (`bot.registration.register_by_pzt_id`): a blocked pzt_id cannot create an account. The refusal is deliberately worded identically to "pzt_id not found" (`registration.not_found`) — a blocked child must not be able to tell a block apart from a typo, so there is nothing to interrogate the bot about.

Also checked on every invitation **send** and **accept** (`bot.invitation_engine.send_invitation` / `accept_invitation`), on both participants, so a block takes effect immediately for a pzt_id that already has an account — not only at its next registration attempt, which might never come. Both failures are mapped to the same neutral, already-existing wording the app uses for unrelated refusals (`partner_selection.cannot_send_invitation`, `invitation.no_longer_valid`) — never a message that reveals a block happened.

**No admin path in the bot. No Telegram command, for anyone, ever.** Writing or removing a row in `blocked_pzt_ids` is done in `psql`, deliberately, by a human at a keyboard — see `docs/RUNBOOK.md`. One compromised operator Telegram account must never be able to block or unblock anyone.

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

Both scrapers run from **systemd timers on the server** (step 13), not GitHub Actions cron. GitHub disables scheduled workflows automatically after 60 days with no commits to the default branch — silently, with no banner in the Actions tab, just one easily-missed email — which is a real risk for a low-commit-velocity public repo like this one. A `workflow_dispatch`-only GitHub workflow (no `schedule:` block) is kept as a manual fallback; manually-triggered workflows are exempt from the 60-day rule. Do not move scheduling back to GitHub Actions cron — that is the exact failure mode this step exists to avoid.

- **Tournaments:** 3× daily.
- **Rankings:** daily at 15:00 Europe/Warsaw during the first 10 days of each month, weekly otherwise. Each run reads the index first and re-scrapes the eight lists **only if the published month changed.**

Frequencies are unchanged from what this section always specified. Note for the record: the GitHub Actions cron described here before step 13 **was never actually created** — the only workflow in the repo has always been `test-scraper.yml`, `workflow_dispatch`-only and `--dry-run`, which writes nothing. Until step 13 the scrapers had only ever been run by hand, which is why the database sat empty for weeks while the spec described a schedule. The systemd timers are the first automated scraping this project has had. Unit files live in `deploy/` (`courtduo-tournaments.service`/`.timer`, `courtduo-rankings.service`, `courtduo-rankings.timer` + `courtduo-rankings-weekly.timer` for the two legs of the rankings schedule, `courtduo-logrotate` for the journald size cap); see `deploy/README.md` for install steps.

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
- Scrapers on systemd timers on the server; bot on a small always-on VM

**Scraping etiquette:** rate limit to ~1 request per 2 seconds, descriptive `User-Agent` with a contact email, cache aggressively, fail loudly rather than writing garbage.

---

## Operations

**Staleness alarm.** Without it a dead scraper is invisible: the bot keeps serving whatever is already in the database until every tournament ages out of the 28-day window (see "Tournament selection"), and then answers every search with "nothing found" — indistinguishable from a genuine empty result.

There is no `tournaments.scraped_at` column, and none should ever be added. `Tournament.updated_at` (`TimestampMixin`) cannot stand in for it either: `db.crud.upsert_tournament` writes via `INSERT ... ON CONFLICT DO UPDATE`, and SQLAlchemy does not apply a column's `onupdate` on that path, so `updated_at` freezes at whatever moment a tournament GUID was first inserted and never moves again on a re-scrape. The real mechanism is two tables:

```
scraper_runs
  id             integer primary key
  scraper        text not null        -- 'tournaments' or 'rankings'
  started_at     timestamptz not null
  finished_at    timestamptz not null
  ok             boolean not null
  items_seen     integer null
  items_written  integer null
  detail         text null            -- short failure summary when ok is false; never a stack trace, never a player name

alarm_state
  key            text primary key     -- the scraper name
  firing         boolean not null
  last_sent_at   timestamptz null
```

`python -m scrapers.tournaments` and `python -m scrapers.rankings` write exactly one `scraper_runs` row per real invocation — success or failure, in its own transaction separate from the data write, so a run that fails halfway through writing data still records that it failed. `--dry-run`, `--dump-html` and `--dump-index-html` write nothing. `ok` is false when the scrape raised, when rankings couldn't discover the published period, or when `items_seen`/`items_written` came back zero — a parser failure, not a quiet month. A run of failures never resets the clock: `bot.staleness` only ever measures against the newest `ok=true` row.

Thresholds (`bot.staleness`, module-level constants, each overridable by an environment variable): tournaments 36 hours (`STALENESS_TOURNAMENTS_HOURS`), rankings 216 hours / 9 days (`STALENESS_RANKINGS_HOURS`) — rankings run weekly outside the first ten days of a month (see "Scraper scheduling"), so a 36-hour threshold would false-alarm every week.

Checked 30 seconds after startup, then every 6 hours — not hourly. Each check wakes a scaled-to-zero Neon compute, and the free plan's compute-hours are shared across every branch; against a 36-hour threshold, a 6-hour cadence still catches a dead scraper within hours of it mattering, and the damage a slower alarm guards against takes weeks, not hours.

`alarm_state` is a table, not an in-memory flag, because the bot runs under `Restart=always` — in-memory state would send one fresh alert per restart during a crash loop instead of one alert followed by silence until recovery. Alerts go to every id in `ALARM_TELEGRAM_IDS` (comma-separated numeric Telegram ids, read fresh on every check, exactly like `entitlements._allowlisted_pzt_ids`; never a hardcoded id, `.env.example` ships it empty), with a reminder every 24 hours while still stale and one recovery message once a fresh successful run lands. Unset or empty is valid — the alarm still runs and still logs at WARNING, it just has nobody to tell. If the staleness check's own database query raises (exhausted Neon quota, wrong credentials, network), that IS an alarm condition and is sent too, deduped in memory at most once per 6 hours per scraper — the one place in-memory dedupe is correct here, since the table that would hold real dedupe state is by definition what's unreachable.

The alarm's message text is operator-facing English, hardcoded in `bot.staleness` rather than routed through `t()`/`locales/pl.json` — a deliberate, narrow exception to "never hardcode user-facing strings" above. These strings never reach a player: only an id in `ALARM_TELEGRAM_IDS` (an operator, never a child) ever sees them, and putting operator text in `locales/pl.json` would put it one bad lookup away from a child's screen.

**`/status`**, operator-only and gated on the same `ALARM_TELEGRAM_IDS`: plain text, no buttons, no reply keyboard, showing each scraper's last successful run and how long ago, its last run and outcome, and whether it is currently inside its threshold. Registered first in `bot.main` so no other router can intercept it. To anybody not on that list it does nothing at all — no reply, no error — a child typing it sees exactly what they'd see typing any other unknown command.

**The Telegram "/" command menu.** Set programmatically in `bot.main` (`set_bot_commands`, called on startup before polling begins) rather than left to whatever was configured by hand in BotFather. `BOT_COMMANDS`, a module-level constant pairing each command name with its `locales/pl.json` description key, is the only thing that needs to change to add another entry later. Exactly two commands are listed: `/start` and `/pomoc` (see "Support" immediately below). `/moje_deble`, `/usun_konto` and `/podglad` all keep working as typed commands — they're just not in the menu, the same "reachable without needing a button of its own" pattern `/status` already established.

**Support.** `/pomoc` is a two-way relay between a player and the operators in `ALARM_TELEGRAM_IDS` — the same list the staleness alarm and `/status` already read via `alarm_recipients()`. Non-negotiable rule 1 above forbids free-text messaging, but that rule is about messaging *between players*: no player's typed words ever reach another player, and no player can address anyone but an operator through it. This is the one place in CourtDuo where a player types free text, and it stays exactly that narrow — one player to the operators, one operator's reply back to that same one player, never routed sideways to anyone else.

- Works whether or not the Telegram account has an `Account` row — no gate on registration. The single most likely support message is "I could not register," sent by someone who by definition has no account yet.

**Step 14.1: an open conversation on both sides, not a one-shot relay.** Live testing found the original one-shot design (`/pomoc` → one FSM-gated message → relay → state clears) unusable for a single operator handling one conversation at a time on a phone: typing a plain reply didn't route, and it fell through to the registration handler instead, answering a support message with "Nie znaleziono zawodnika o takim loginie PZT". `bot.states.Support.waiting_message` is gone; the open/closed state now lives in two tables, evaluated lazily whenever a message arrives — no scheduler anywhere — because the bot runs under `Restart=always` and the `Dispatcher` uses `MemoryStorage`, so FSM state (or anything in memory) would silently reroute a child's next message after every restart, same reasoning `alarm_state` and `support_threads` already establish:

  ```
  support_conversations
    user_telegram_id   bigint primary key
    is_open            boolean not null
    last_activity_at   timestamptz not null

  support_operator_sessions
    operator_telegram_id  bigint primary key
    user_telegram_id      bigint not null
    last_activity_at      timestamptz not null
    state                  text null   -- 'open' | 'suspended' (step 14.2); NULL reads as 'open'
  ```

  Neither stores a message body, same as `support_threads` below — these three tables only ever answer "who is talking to whom right now", never "what did they say".

  All of this is implemented as one OUTER message middleware, `bot.middlewares.support_conversation.SupportConversationMiddleware`, registered in `bot.main` ahead of every router — it is what lets a player's or an operator's plain text be caught and relayed (or refused, or explained) before any router — including `/status`'s own, which still goes first among routers — ever sees it.

  *Player side.* `/pomoc` opens (or silently re-opens) this Telegram id's own conversation and says so plainly. From then on, every plain-text message this Telegram id sends is relayed to every id in `alarm_recipients()`, one DM each — exactly the original one-shot relay's own fan-out, just repeated for as long as the conversation stays open, with no need to retype `/pomoc`. **Step 14.2 removed the per-message confirmation the player used to get back** (`support.confirmation`, "Wiadomość została wysłana...") — live testing found it firing after every single line of a running conversation, pure noise; the conversation-opened message already tells the player their answer arrives here, so a player now gets no automatic reply to a support message at all — the next thing they see is the operator's own answer. A conversation closes — silently, no message about the close itself, since the player is the one who caused it — the moment its own Telegram id sends any command or taps any persistent-reply-keyboard label (both are "handled normally": the real command/label handler still runs, untouched); it also closes, this time *with* a message, when the operator taps "Close conversation" (below), or when it goes 30 minutes with no activity (`support.conversation_expired` — the message that triggered the check is not relayed, and the player is pointed back at `/pomoc`).
  - Non-text content (photo, sticker, voice, document, anything) is refused (`support.non_text_refusal`) and never relayed in either direction, exactly as the one-shot design already refused it.
  - Capped at 5 relayed messages per hour per Telegram account, reusing the shape of `bot.attempt_limiter.FailedAttemptLimiter` as its own separate instance — never sharing the registration limiter's counters, same "one process per bot instance, in-memory counter is fine" reasoning as everywhere else that class is used; over the cap, the player is told (`support.rate_limited`) and nothing is relayed.

  *Operator side.* Every incoming support message carries an inline button, English, `Reply: {name}` (`core.text.display_name`, or a plain "telegram id {id}" fallback for someone with no account yet). Tapping it opens that operator's own conversation in `state='open'`: the bot confirms in plain English, names the player and their pzt_id, states that everything typed from now on goes to them, and carries one inline button, `Close conversation`. While open, every plain-text message that operator sends — no reply-quoting, no button, just typing — is delivered to that one player, headed `support.reply_header` exactly as before, and now gets a one-line English delivery receipt back — `Sent to {name}.` — the moment `push()` confirms it landed (step 14.2, "DELIVERY RECEIPTS TO THE OPERATOR": what makes a misroute visible on the spot instead of several messages later, rather than only after the fact). No receipt is sent when `push()` itself reports the delivery failed (blocked bot, deleted chat) — a receipt promises delivery, not an attempt. **If a different player writes while a conversation is open, the open conversation never silently switches** — the new message gets its own `Reply: {name}` button like any other, and the operator's session keeps naming whoever it already named until they explicitly act.
  - A command from an operator (this includes `/status`) is never swallowed by an open session, regardless of how recently they typed — a command always falls straight through to its own handler, which is what keeps `/status`'s "nothing else gets a chance to intercept it first" guarantee true even for an operator mid-conversation.

**Step 14.2: a SUSPENDED session, failing closed.** Live testing on the test bot found the "never silently switches" promise above was true and still not enough: with an open session on player A, player B sent `/pomoc` and a message — B's own message correctly got its own `Reply: {name}` button, and the operator's session correctly stayed pointed at A — but the operator, not noticing the second incoming message, then typed a reply meant for B, and it went to A. Nothing in "never silently switches" actually stopped them from typing while the session still named someone else; that is a design gap, not a routing bug, in the mechanism step 14.1 built. The fix keeps "never silently switches" exactly as it is — the target still never changes on its own — and adds a second, independent guard on top: the moment any player *other than* the one an operator's own open session names gets a message relayed, that operator's session flips to `state='suspended'`, on every operator whose session currently names anyone else (not just the one this new message happens to be about). A suspended session still remembers `user_telegram_id` — it simply refuses to deliver.
  - While suspended, a plain-text message from that operator delivers to **nobody**. Instead the bot replies in English naming every player currently waiting (whoever the session was already with, plus everyone else sitting on an unexpired open conversation), with one `Reply: {name}` button per player — the exact same callback the original incoming-message button uses.
  - Tapping one resumes the session with that player (`state` back to `'open'`) and delivers nothing retroactively: whatever the operator typed while suspended is simply gone, never sent to anyone. They have to retype it once they know who they're actually answering — a message written for one child must never reach another just because a button was tapped afterwards.
  - A reply-to-message still works while suspended and still wins, completely untouched: it names its recipient unambiguously via `support_threads` regardless of any `state`, exactly as "explicit beats implicit" already required before this step.
  - The 30-/60-minute expiry windows are unchanged — a suspended session that goes stale on `last_activity_at` still expires exactly as an open one does.

  These three changes — no player-side confirmation, delivery receipts, and the SUSPENDED fail-closed state — are amendments to step 14.1's own design, not a new mechanism: the same two tables, the same middleware, the same buttons, one nullable column added.

  *Reply-to still works, and always wins.* An operator answering with Telegram's own native reply on the DM they received — rather than typing fresh — is untouched by any of the above: explicit beats implicit, so a reply-to is checked first and bypasses the open-conversation machinery entirely, exactly as it always has. The bot looks up which player that specific delivered copy belongs to (`support_threads`, below) and relays the reply back to that one player only, prefixed with `support.reply_header`. Only an id in `alarm_recipients()` may do this at all — a reply-to from anyone else produces no outbound message and no reply of any kind, the same "invisible, not merely locked" discipline `/status` and `/podglad` already use for a non-operator. If the replied-to message doesn't map to anything (too old, or a row that was never written), the operator is told plainly instead — never a silent no-op, and never a guessed recipient.

  *The registration fall-through, fixed.* An id in `alarm_recipients()` with no `Account` row, sending plain text with no open conversation and no reply-to, now gets a short English note — no open conversation, tap Reply on a support message to open one — instead of ever reaching the registration handler. The trade-off this implies, stated plainly: **an id on `ALARM_TELEGRAM_IDS` cannot register as a player while it is on that list.** That's correct for an operator account; anyone who genuinely needs to register removes the id from `ALARM_TELEGRAM_IDS`, registers, and adds it back.

- `support_threads` holds one row per (operator, delivered message) — a message relayed to three operators writes three rows, so whichever one actually answers still routes back to the right player:

  ```
  support_threads
    id                   integer primary key
    operator_chat_id     bigint not null
    operator_message_id  bigint not null
    user_telegram_id     bigint not null
    created_at           timestamptz not null
    unique (operator_chat_id, operator_message_id)
  ```

  Deliberately holds no message body, in either direction — this table only ever answers "which player does this operator's message belong to"; Telegram already holds the actual conversation, and CourtDuo has no reason to keep a second, stored copy of a child's words. Must be a table, not an in-memory dict, for the same reason `alarm_state` is one: the bot runs under `Restart=always` and the `Dispatcher` uses `MemoryStorage`, so anything kept only in memory would break every reply across a restart.
- Operator-facing text (who a message is from, the no-mapping notice, the two buttons' own labels, the expiry/reopen notice) is hardcoded English, exactly like the rest of this "Operations" section — the same narrow, deliberate exception to "never hardcode user-facing strings" above, for the same reason: it never reaches a player. Every player-facing string lives under `support.*` in `locales/pl.json`, through `t()`, same as anywhere else in the bot.
- Not on the persistent reply keyboard, and no FAQ or submenu of any kind — `/pomoc` is a command and a "/" menu entry only, reachable the same way `/status` and `/podglad` are reachable without a button of their own.

---

## Build order

Fourteen steps are built, merged, deployed and tested end-to-end against live PZT
data on the test bot. Sub-steps (4.5, 5.1–5.5, 7.1, 8.1–8.8, 10.1–10.2, 12.1–12.2, 14.1) were
corrections and refinements found by live testing; their behaviour is documented
in the relevant sections above, which are the authoritative description. Steps
11, 12, 13 and 14 were added after the original ten, once real users became imminent
rather than being part of the initial plan — see "Operations" and "Account
deletion and blocking" for their authoritative descriptions.

1. ~~Tournament scraper with doubles detection~~ **done**
2. ~~Ranking scraper, alphabetical lists~~ **done**
3. ~~Database schema and upserts~~ **done**
4. ~~Registration by PZT ID~~ **done**
5. ~~Tournament selection by place~~ **done** (age category first, 28-day window, ranga prefix, DD.MM.YYYY)
6. ~~Pre-invitation checks~~ **done** (incl. age eligibility, re-invite blocking, already-invited-by-them)
7. ~~Invitation send / accept / reject / not-attending with atomic locking~~ **done** (incl. sender cancellation)
8. ~~Status view and notifications — "Moje deble"~~ **done**
9. ~~Non-user invite flow and the "they joined" callback~~ **done** (incl. the inviter referrer token, recorded but never displayed)
10. ~~Read-only viewers (allowlisted test feature)~~ **done**
11. ~~Staleness alarm and `/status`~~ **done**
12. ~~Account deletion and blocking~~ **done**
13. ~~Scrapers onto systemd timers, with logrotate~~ **done**
14. ~~Telegram "/" command menu and `/pomoc` support relay~~ **done**

## Not yet built

Not part of the original build order, but required before real users:

- **Results-confirmed verification.** Scrape `TournamentResults.aspx` after
  tournaments end and check whether a matched pair actually appears in the
  doubles draw. Collect the data before showing any badge.
