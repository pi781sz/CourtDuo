"""FSM state for tournament search by place (CLAUDE.md, "Tournament
selection"; build order step 5).

bot/tournament_search.py sets it after a successful registration and on
/start for a returning player; bot/handlers/tournament_search.py handles
both the typed place and the result buttons (pagination, "show all",
"change place") while staying in this one state, since tapping a
tournament hands off to step 6 rather than moving the FSM forward itself.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class TournamentSearch(StatesGroup):
    waiting_place = State()
