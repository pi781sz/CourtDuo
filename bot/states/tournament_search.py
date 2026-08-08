"""FSM states for tournament search (CLAUDE.md, "Tournament selection";
build order step 5, revised by step 5.1 to ask age category first).

bot/handlers/tournament_search.start_tournament_search sets
waiting_category after a successful registration and on /start for a
returning player. Choosing a category moves to waiting_place; tapping a
tournament hands off to step 6 rather than moving the FSM forward itself.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class TournamentSearch(StatesGroup):
    waiting_category = State()
    waiting_place = State()
