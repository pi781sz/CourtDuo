"""FSM state for PZT-id registration (CLAUDE.md, "Identity"; build order
step 4)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    waiting_pzt_id = State()
