"""FSM state for /pomoc (CLAUDE.md, "Operations" > "Support"): one state
covers the single message a player is asked to type after running the
command. Non-text content leaves this state set so the player can simply
try again with text; a text message clears it, whether the message is
relayed or refused for being over the rate cap.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Support(StatesGroup):
    waiting_message = State()
