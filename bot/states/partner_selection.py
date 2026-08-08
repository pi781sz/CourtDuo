"""FSM state for partner name entry (CLAUDE.md, "Pre-invitation checks";
build order step 6). One state covers both the typed name and any
disambiguation button tap that follows it -- the same shape as
TournamentSearch.waiting_place, which already handles a message handler
and several callback handlers side by side.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class PartnerSelection(StatesGroup):
    waiting_name = State()
