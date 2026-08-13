"""Static audit for CLAUDE.md step 12.1, PROBLEM 6: an inline keyboard
carries only the choices relevant to its own message; the three/four
persistent-reply-keyboard actions (Znajdź partnera, Moje deble, Zaproś na
CourtDuo, Podgląd konta) must never also appear as buttons on a *choice*
keyboard, where they duplicate the always-visible reply keyboard and risk
a mis-tap losing the player's place (found live in
bot.keyboards.tournament_search.category_keyboard, since fixed).

bot.keyboards.navigation is where the persistent reply keyboard itself
lives, along with two already-documented, deliberate exceptions that are
not "choice" keyboards at all:
- find_partner_keyboard / moje_deble_summary_keyboard: the single action
  offered on Moje deble's own empty/summary screens (CLAUDE.md, "Moje
  deble", "EMPTY STATE").
- invitation_sent_keyboard: the belt-and-braces inline "Moje deble" on
  "Zaproszenie zostało wysłane" (CLAUDE.md step 8.7), kept because the
  persistent keyboard itself can be collapsed by the player.

So this audit is scoped to every *other* file under bot/keyboards/ --
those must never reference the persistent-keyboard button text keys or
callback classes at all.
"""

from __future__ import annotations

import pathlib

_KEYBOARDS_ROOT = pathlib.Path(__file__).resolve().parent.parent / "bot" / "keyboards"

# The locale keys behind the persistent reply keyboard's own labels
# (bot.keyboards.navigation.persistent_menu_keyboard / viewer_menu_keyboard).
_NAV_TEXT_KEYS = (
    "common.find_partner_button",
    "common.moje_deble_button",
    "common.invite_button",
    "common.podglad_button",
)
_NAV_CALLBACKS = ("FindPartnerCallback", "MojeDebleCallback")


def test_no_choice_keyboard_references_persistent_keyboard_buttons():
    violations: list[str] = []
    for path in sorted(_KEYBOARDS_ROOT.glob("*.py")):
        if path.name == "navigation.py":
            # Owns the persistent keyboard itself plus the two documented
            # exceptions above -- audited by name in
            # tests/test_navigation_keyboards.py instead.
            continue
        text = path.read_text(encoding="utf-8")
        for key in _NAV_TEXT_KEYS:
            if key in text:
                violations.append(f"{path.name}: references {key!r}")
        for name in _NAV_CALLBACKS:
            if name in text:
                violations.append(f"{path.name}: references {name!r}")

    assert violations == [], (
        "a choice keyboard outside bot/keyboards/navigation.py references a "
        "persistent-reply-keyboard button -- CLAUDE.md step 12.1, PROBLEM 6:\n"
        + "\n".join(violations)
    )
