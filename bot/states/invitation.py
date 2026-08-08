"""FSM state for the invitation confirmation screen (CLAUDE.md,
"Invitation engine"; build order step 7).

Only the inviter has a state here. The invitee is not in a conversation at
all when their invitation arrives — the bot pushes it to them — so the
Zatwierdź / Odrzuć / "Nie jadę na ten turniej" handlers are registered
without a state filter and leave whatever state the invitee was already in
untouched.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class InvitationSend(StatesGroup):
    waiting_confirmation = State()
