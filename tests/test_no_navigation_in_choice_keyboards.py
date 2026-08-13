"""Static audit for CLAUDE.md step 12.1, PROBLEM 6 (and step 12.2, which
found the audit hadn't actually been completed): an inline keyboard
carries only the choices relevant to its own message; the three/four
persistent-reply-keyboard actions (Znajdź partnera, Moje deble, Zaproś na
CourtDuo, Podgląd konta) must never also appear as buttons on an inline
keyboard, where they duplicate the always-visible reply keyboard and risk
a mis-tap losing the player's place, or -- the bug step 12.2 actually
found live -- simply show the player the same button twice, stacked, on
screen at once (bot.keyboards.tournament_search.category_keyboard, since
fixed; bot.keyboards.navigation.moje_deble_summary_keyboard, fixed by
step 12.2).

Step 12.1's version of this audit skipped bot/keyboards/navigation.py
entirely, on the theory that it owns two deliberate, documented
exceptions (find_partner_keyboard and moje_deble_summary_keyboard's own
"Znajdź partnera" button) alongside the persistent keyboard itself. Live
testing under step 12.2 found that theory wrong -- both were live
duplicates, not intentional reuse -- and the "audited by name in
tests/test_navigation_keyboards.py instead" carve-out let them go
unnoticed because nothing there actually cross-checked against the
persistent keyboard's own labels. This version replaces the file-level
skip with a per-function check across every function in
bot/keyboards/navigation.py too, so the one function that is still a
deliberate exception (invitation_sent_keyboard, CLAUDE.md step 8.7) has
to be named explicitly rather than the whole module waved through.
"""

from __future__ import annotations

import ast
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

# Functions that build the persistent reply keyboard itself -- they own
# these labels, rather than duplicating them, so they are not part of
# this audit at all.
_REPLY_KEYBOARD_BUILDERS = {"persistent_menu_keyboard", "viewer_menu_keyboard"}

# The single agreed exception (CLAUDE.md step 8.7): the belt-and-braces
# inline "Moje deble" on "Zaproszenie zostało wysłane", kept because the
# persistent reply keyboard can be collapsed by the player and this is
# the one screen they're most likely to need it right after.
_ALLOWED_DUPLICATES = {
    ("navigation.py", "invitation_sent_keyboard"): {"common.moje_deble_button", "MojeDebleCallback"},
}


def _violations_in_function(path: pathlib.Path, source: str, node: ast.FunctionDef) -> list[str]:
    allowed = _ALLOWED_DUPLICATES.get((path.name, node.name), set())
    body = ast.get_source_segment(source, node) or ""
    violations = []
    for key in _NAV_TEXT_KEYS:
        if key in body and key not in allowed:
            violations.append(f"{path.name}:{node.name} references {key!r}")
    for name in _NAV_CALLBACKS:
        if name in body and name not in allowed:
            violations.append(f"{path.name}:{node.name} references {name!r}")
    return violations


def test_no_inline_keyboard_duplicates_a_persistent_keyboard_button():
    violations: list[str] = []
    for path in sorted(_KEYBOARDS_ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name in _REPLY_KEYBOARD_BUILDERS:
                continue
            violations.extend(_violations_in_function(path, source, node))

    assert violations == [], (
        "an inline keyboard function duplicates a persistent-reply-keyboard "
        "button -- CLAUDE.md step 12.2 (the audit step 12.1 asked for and "
        "did not complete):\n" + "\n".join(violations)
    )
