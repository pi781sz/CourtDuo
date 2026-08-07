"""FSM state for tournament search by place (CLAUDE.md build order step
5 — not built yet).

Only the entry state exists so far: bot/tournament_search.py sets it
after a successful registration and on /start for a returning player;
bot/handlers/tournament_search.py has a temporary stub handler for it.
TODO(step 5): the real place-search handler replaces the stub; this
state itself stays.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class TournamentSearch(StatesGroup):
    waiting_place = State()
