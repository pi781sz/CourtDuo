"""Entitlement gate for invitation creation (CLAUDE.md, "Monetisation —
build now, enable later"). Every invitation send must route through
can_send_invitation, so that when paid tiers launch, exactly one
function changes.

Re-exported from db.crud rather than reimplemented here: db.crud already
defines this exact function (added alongside the invitation-engine
schema), and CLAUDE.md's own instruction — don't scatter quota logic
through the codebase — argues against a second, competing
implementation. This module exists to give the entitlement check a
stable, crud-independent import path, per Step 4's brief.
"""

from __future__ import annotations

from db.crud import can_send_invitation

__all__ = ["can_send_invitation"]
