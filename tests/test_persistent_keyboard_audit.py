"""Static audit for CLAUDE.md step 8.7: nothing under bot/ may ever build
or send a ReplyKeyboardRemove. A single one landing on any code path would
permanently collapse the persistent reply keyboard for that chat -- worse
than the "never re-attached" bug this step fixes, and not something a
handler-level test can rule out for every path at once.

The behavioural side (the keyboard actually being attached, with the
right flags, at every real entry point) is covered where it can be
exercised for real: tests/test_start_handlers_db.py (both /start branches
and, since step 8.7, registration completion),
tests/test_invitation_handlers_db.py (every accept/reject/not-attending/
cancelled push, and the invitation-sent screen's belt-and-braces inline
button), and tests/test_navigation_keyboards.py (the keyboard's own
layout and flags in isolation).
"""

from __future__ import annotations

import pathlib

_BOT_ROOT = pathlib.Path(__file__).resolve().parent.parent / "bot"


def test_no_reply_keyboard_remove_anywhere_under_bot():
    violations = [
        str(path.relative_to(_BOT_ROOT.parent))
        for path in sorted(_BOT_ROOT.rglob("*.py"))
        if "ReplyKeyboardRemove" in path.read_text(encoding="utf-8")
    ]
    assert violations == [], "ReplyKeyboardRemove would collapse the persistent keyboard permanently:\n" + "\n".join(
        violations
    )
