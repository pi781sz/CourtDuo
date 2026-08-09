"""Entitlement gates (CLAUDE.md, "Monetisation — build now, enable
later"). Every invitation send must route through can_send_invitation,
and every read-only-viewers action through can_use_viewers, so that when
paid tiers launch, exactly one function each changes.

can_send_invitation is re-exported from db.crud rather than reimplemented
here: db.crud already defines this exact function (added alongside the
invitation-engine schema), and CLAUDE.md's own instruction — don't
scatter quota logic through the codebase — argues against a second,
competing implementation. This module exists to give the entitlement
check a stable, crud-independent import path, per Step 4's brief.

can_use_viewers lives here directly instead: it's pure (an env var and a
pzt_id comparison, no database access), unlike can_send_invitation, so
there's nothing for db.crud to own. Step 10 ("Read-only viewers") gates
the feature behind an allowlist of PZT ids while it's a free test
feature — CLAUDE.md rule 4: no PZT id may ever appear in a committed
file, so the allowlist is read from the VIEWER_ALLOWLIST_PZT_IDS
environment variable, never hardcoded, and .env.example ships it empty.
"""

from __future__ import annotations

import os

from db.crud import can_send_invitation
from db.models import Account

__all__ = ["can_send_invitation", "can_use_viewers"]


def _allowlisted_pzt_ids() -> frozenset[str]:
    # Read fresh on every call, not cached at import time: a test needs to
    # be able to monkeypatch the environment and see the effect
    # immediately, and this is cheap enough to not need caching.
    raw = os.environ.get("VIEWER_ALLOWLIST_PZT_IDS", "")
    return frozenset(pzt_id.strip().upper() for pzt_id in raw.split(",") if pzt_id.strip())


def can_use_viewers(account: Account) -> bool:
    """Whether `account` may see the Podgląd option and create viewer
    invite tokens (CLAUDE.md step 10). Only gates *creating* new grants —
    a grant already made keeps working (notifications keep forwarding,
    Moje deble stays readable) even if the account later drops off the
    allowlist; revocation is exclusively the player's own action.
    """
    return account.pzt_id.upper() in _allowlisted_pzt_ids()
