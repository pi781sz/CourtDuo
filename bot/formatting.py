"""Small display helpers shared by more than one handler/keyboard, kept
out of bot/i18n.py since they decide *which* string to use, not how to
look one up.
"""

from __future__ import annotations

from bot.i18n import t
from db.models import InvitationState


def format_position(position: int | None, lang: str) -> str:
    if position is None:
        return t("player.position_unknown", lang)
    return t("player.position_known", lang, position=position)


# CLAUDE.md step 8.3, PROBLEM 2: the single lookup every status message
# routes through -- "Put the emoji for each state in ONE lookup and have
# every message use it. No literal status emoji anywhere else." Only the
# four states bot.moje_deble ever displays (its own _VISIBLE_STATES) have a
# colour; CANCELLED/EXPIRED are never shown with one.
STATUS_EMOJI: dict[InvitationState, str] = {
    InvitationState.PENDING: "🟠",
    InvitationState.ACCEPTED: "🟢",
    InvitationState.REJECTED: "🔴",
    InvitationState.NOT_ATTENDING: "🔴",
}

# CLAUDE.md step 12, "What happens to a confirmed partner": an ACCEPTED
# invitation whose other side deleted their CourtDuo account keeps its
# match line, but with this colour instead of STATUS_EMOJI[ACCEPTED] --
# "confirm this in person" is a different situation from a live match, not
# a fifth InvitationState (CLAUDE.md forbids inventing states for what is
# really a display concern -- see the NOT_ATTENDING precedent).
PARTNER_DELETED_EMOJI = "⚠️"
