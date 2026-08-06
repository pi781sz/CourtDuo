from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    choosing_role = State()
    entering_player_name = State()
    choosing_player = State()
    post_link = State()
