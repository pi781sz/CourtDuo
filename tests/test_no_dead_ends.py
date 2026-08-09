"""Static audit for CLAUDE.md build order step 8.4: the inline [Menu]
button step 8.2 attached to every terminal message is gone, replaced by
the persistent reply keyboard attached once at the start of a session
(bot.keyboards.navigation.persistent_menu_keyboard). No message anywhere
in bot/ may build or reference the old MenuCallback / terminal_keyboard /
menu_keyboard machinery -- if a future change reintroduces an inline Menu
button, this fails instead of shipping.

This replaces step 8.2's terminal/mid-flow classification test, which no
longer has anything to classify: neither kind of message carries an inline
navigation button any more.
"""

from __future__ import annotations

import pathlib
import re

_BOT_ROOT = pathlib.Path(__file__).resolve().parent.parent / "bot"

# Anything that would reintroduce the old inline [Menu] button or its
# chooser -- CLAUDE.md step 8.4 removed all of these from
# bot.keyboards.navigation. Word-boundary matched so this doesn't also flag
# persistent_menu_keyboard, the reply keyboard that replaced menu_keyboard.
_FORBIDDEN_NAMES = ("MenuCallback", "terminal_keyboard", "handle_menu")
_FORBIDDEN_PATTERN = re.compile(r"\bmenu_keyboard\b")


def test_no_inline_menu_button_machinery_remains_anywhere():
    violations: list[str] = []
    for path in sorted(_BOT_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in _FORBIDDEN_NAMES:
            if name in text:
                violations.append(f"{path.relative_to(_BOT_ROOT.parent)}: found {name!r}")
        if _FORBIDDEN_PATTERN.search(text):
            violations.append(f"{path.relative_to(_BOT_ROOT.parent)}: found 'menu_keyboard'")

    assert violations == [], "inline [Menu] button machinery still referenced:\n" + "\n".join(violations)


def test_no_literal_menu_emoji_button_text_remains():
    # The button label itself ("🔵 Menu") must not appear literally anywhere
    # in bot/ or locales/ -- CLAUDE.md, "Never hardcode user-facing
    # strings" doubles as a second guard here.
    violations: list[str] = []
    for root in (_BOT_ROOT, _BOT_ROOT.parent / "locales"):
        for pattern in ("*.py", "*.json"):
            for path in sorted(root.rglob(pattern)):
                if "🔵 Menu" in path.read_text(encoding="utf-8"):
                    violations.append(str(path.relative_to(_BOT_ROOT.parent)))

    assert violations == [], "literal '🔵 Menu' button text still present:\n" + "\n".join(violations)
