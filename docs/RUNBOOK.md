# Operator runbook: blocking and deletion

Plain-English, copy-pasteable psql for the four things an operator has to do by hand (CLAUDE.md step 12, "Blocking": "No admin path in the bot. No Telegram command, for anyone, ever. This is done in psql, deliberately, by a human at a keyboard.").

Every `pzt_id` and name below is an obviously fake placeholder (`ABC1234`, "Testowy Zawodnik"). **Never paste a real PZT id or a real player's name into this file** — it lives in a public repository (CLAUDE.md rule 4).

Written for someone tired at 11pm. Read the whole section before running anything.

---

## Connecting

```bash
cd /opt/courtduo        # or /opt/courtduo-test — see DEPLOY.md
set -a; . ./.env; set +a
psql "$DATABASE_URL"
```

If `psql` complains about `sslmode`/`channel_binding`, see DEPLOY.md's "Managed-Postgres connection strings" section — strip `channel_binding` from the URL first.

Everything below assumes you are now at the `psql` prompt.

---

## 1. Block a pzt_id

Stops the pzt_id from registering a new account, and — if it already has one — stops that account from sending or accepting any invitation, immediately. It does **not** delete the account or touch any existing match. Pair this with section 3 (delete on request) if the person also needs their account gone.

```sql
INSERT INTO blocked_pzt_ids (pzt_id, blocked_at, reason)
VALUES ('ABC1234', now(), 'reported for harassment via WhatsApp share, 2026-08-13');
```

`reason` is optional — pass `NULL` if you don't want to record one:

```sql
INSERT INTO blocked_pzt_ids (pzt_id, blocked_at, reason)
VALUES ('ABC1234', now(), NULL);
```

`pzt_id` is the primary key, so blocking an id that's already blocked fails with a duplicate-key error rather than silently double-blocking — that's fine, it means you don't need to do anything.

**The bot never tells the blocked player why a registration or a send/accept failed** — by design (CLAUDE.md: "The refusal message must be plain and give no detail — a child on the receiving end of this should not be interrogated by the bot"). Don't expect them to be told, and don't tell them yourself unless your own reporting process calls for it.

---

## 2. Unblock a pzt_id

```sql
DELETE FROM blocked_pzt_ids WHERE pzt_id = 'ABC1234';
```

Takes effect immediately — the next registration attempt, invitation send, or accept for that pzt_id is no longer refused. If you want a record that it was *once* blocked, don't delete the row — there is currently no "revoked" flag, only present-or-absent, so deleting really does forget it happened. If that matters to you, copy the row somewhere else first (e.g. paste it into your own incident notes) before deleting.

---

## 3. Delete an account on request (player can't do it themselves)

Players should normally use `/usun_konto` in the bot themselves — it's self-service by design (CLAUDE.md: "Deleting alone is not enough... erasure must not depend on me being awake"). Use this section only when they genuinely can't — lost access to Telegram, a parent asking on a younger child's behalf, etc.

First, find the account:

```sql
SELECT id, telegram_id, pzt_id, full_name, gender, plan, created_at
FROM accounts
WHERE pzt_id = 'ABC1234';
```

There is no bot command that does this deletion for you (CLAUDE.md: "No admin path in the bot"). The `/usun_konto` flow's actual deletion (`bot.account_deletion.delete_account`) does more than a bare `DELETE` — it cancels pending invitations and notifies the people involved, snapshots names on any still-open confirmed match rather than leaving it silently orphaned, and gives the remaining partner (if any) their own copy in Moje deble. Reproducing all of that by hand in psql would either miss a step or double-notify people, and this is exactly the case where a human at a keyboard should **not** try to shortcut the app's own logic.

If you must remove the row without going through the bot at all (e.g. the bot itself is down and this can't wait), the minimum equivalent is:

```sql
BEGIN;

-- Cancel PENDING invitations this account sent or received. Skip this
-- if you plan to run the ordinary bot-side deletion once it's back up
-- instead — don't do both.
UPDATE invitations
SET state = 'CANCELLED'
WHERE state = 'PENDING'
  AND (inviter_pzt_id = 'ABC1234' OR invitee_pzt_id = 'ABC1234');

-- account_viewers and viewer_invite_tokens cascade automatically via
-- their own ON DELETE CASCADE foreign keys to accounts.id.
DELETE FROM accounts WHERE pzt_id = 'ABC1234';

COMMIT;
```

This does **not** notify anybody, and does **not** snapshot names on any confirmed (ACCEPTED) match — those rows are left exactly as they were, still pointing at a pzt_id with no account any more, and the other player's Moje deble will not show the "confirm in person" status until something (a future manual UPDATE, or the player re-registering) touches that row. **Prefer the real `/usun_konto` flow whenever the bot is reachable at all** — this raw-SQL path is a last resort, not a routine option.

The `players` row for this pzt_id (name, club, ranking history) is **not** deleted by any of this — it's PZT's own public roster data, scraped independently, and stays regardless (CLAUDE.md, "What is actually erased, and what is kept": "`players.full_name` itself is never erased"). If someone specifically wants that gone too, there is no path today — say so rather than improvising one.

---

## 4. Subject access request — what data exists for a given pzt_id

A parent, or the player themselves, asks "what do you have on me/my child". Run each query and share only what's relevant to what they asked.

```sql
-- The account itself, if one exists.
SELECT id, telegram_id, pzt_id, full_name, gender, plan, invitations_used, lang, created_at
FROM accounts
WHERE pzt_id = 'ABC1234';

-- Every invitation they've sent or received, in any state.
SELECT id, inviter_pzt_id, invitee_pzt_id, tournament_guid, state,
       inviter_name_snapshot, invitee_name_snapshot, created_at, updated_at
FROM invitations
WHERE inviter_pzt_id = 'ABC1234' OR invitee_pzt_id = 'ABC1234'
ORDER BY updated_at;

-- Read-only viewers they've granted access to, or been granted access by.
SELECT av.id, av.account_id, av.viewer_telegram_id, av.viewer_display_name,
       av.granted_at, av.revoked_at
FROM account_viewers av
JOIN accounts a ON a.id = av.account_id
WHERE a.pzt_id = 'ABC1234';

-- Whether they're currently blocked.
SELECT * FROM blocked_pzt_ids WHERE pzt_id = 'ABC1234';

-- Their public PZT roster entry (name, club, ranking history) — this is
-- scraped from PZT's own public pages, not something CourtDuo collected
-- independently, but it's still worth listing so the answer is complete.
SELECT pzt_id, full_name, club, age_category, gender FROM players WHERE pzt_id = 'ABC1234';
SELECT ranking_list, year, month, position FROM rankings WHERE player_pzt_id = 'ABC1234' ORDER BY year, month;
```

---

## 5. What to tell a parent who asks what you hold about their child

A short, honest answer, not a legal document (see the note at the bottom of this file):

- We store a link between their Telegram account and their PZT id, their name and gender as registered (from PZT's own public ranking list), and a record of the doubles invitations they've sent, received, or agreed to on CourtDuo.
- We do not store their phone number, ever — CourtDuo never asks for or sees one.
- We do not store free-text messages — every interaction is a fixed button (Zatwierdź / Odrzuć / etc.), so there's no chat log to hand over.
- Their name and PZT ranking are public information published by PZT itself; CourtDuo did not originate it and deleting a CourtDuo account does not remove it from PZT's own site.
- They (or their child, from inside the bot) can delete the CourtDuo account at any time via `/usun_konto`. Confirmed doubles matches are the one exception kept after deletion — the other child in a still-open match keeps a record of who they were paired with, gendered explanation in section 6 below.
- We can also block a specific PZT id from ever using CourtDuo again, if that's what's being asked for (section 1).

---

## 6. Why a confirmed match survives deletion (for your own understanding, if asked)

If a parent asks "why does the other child still see my child's name after I deleted the account" — this is deliberate, not a bug. CLAUDE.md documents the reasoning: a confirmed doubles pairing is a real commitment between two children for a real tournament. If CourtDuo silently erased every trace of it the moment one side deleted their account, the remaining player would be left with a blank "confirm this in person" line and no way to know who they were even supposed to ask. So the pairing record (state, and a copy of the deleted player's name as it was at the moment of deletion) is kept until the tournament itself finishes, then automatically cleared. This is a considered decision, not a legal ruling — CourtDuo's operator is not a lawyer, and this is the least-bad option: a temporary, bounded-in-time trace, not permanent, and not visible to anyone except the specific person who had already committed to playing alongside them.
