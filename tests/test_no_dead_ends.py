"""Static audit for CLAUDE.md build order step 8.2, "Buttons only at the
end": a terminal message -- the journey has ended and the player has no
next step in the current flow -- carries the [Menu] navigation button
(bot.keyboards.navigation.terminal_keyboard); a mid-flow message -- the
next thing expected is the player typing or tapping something in the flow
they're already in -- carries none.

This replaces step 8.1's blanket "every message needs a keyboard" rule,
which produced exactly the clutter step 8.2 undoes: a prompt like "Wpisz
imię i nazwisko osoby..." followed by buttons that abandon the flow.

Classification here is by locale key, extracted from a direct `t("some.key",
...)` call passed straight to a message-sending call -- the one shape this
can trace statically without a database or Telegram. Composed text
(sent_text(), matched_text(), an f-string built from two locale strings,
...) isn't classified here; those call sites are covered by the
behavioural, handler-level tests in tests/test_*_db.py instead, which check
the actual reply_markup a real handler call produces.

A key that later moves between the two sets below, or a terminal_keyboard()
call newly attached to a key that belongs in the mid-flow set (or vice
versa), fails the test instead of shipping.
"""

from __future__ import annotations

import ast
import pathlib

_BOT_ROOT = pathlib.Path(__file__).resolve().parent.parent / "bot"
_SEND_METHODS = {"answer", "edit_text", "send_message"}

# CLAUDE.md build order step 8.2, "Terminal -- these get buttons": the
# subset reachable through a direct, statically-traceable `t("key", ...)`
# call. (Most terminal messages in bot/handlers/invitations.py are chosen
# through a dict keyed by an enum -- e.g. `t(_RESPOND_FAILURE_KEYS[failure],
# ...)` -- which this audit cannot trace back to a literal key; those are
# covered by tests/test_invitation_handlers_db.py instead.)
_TERMINAL_KEYS = frozenset(
    {
        "partner_selection.inviter_already_matched",
        "partner_selection.cannot_send_invitation",
        "invitation.no_longer_valid",
        "tournament_search.none_eligible",
    }
)

# CLAUDE.md build order step 8.2, "Mid-flow -- these get NO navigation
# buttons": every message where the next thing expected is the player
# typing or tapping something in the flow they're already in, reachable
# through a direct `t("key", ...)` call.
_MID_FLOW_KEYS = frozenset(
    {
        "start.greeting",
        "registration.ask_pzt_id",
        "registration.welcome",
        "registration.not_found",
        "registration.already_bound",
        "registration.too_many_attempts",
        "registration.error_try_later",
        "tournament_search.ask_place",
        "tournament_search.place_too_short",
        "tournament_search.no_place_matches",
        "tournament_search.tournament_gone",
        "partner_selection.ask_name",
        "partner_selection.name_too_short",
        "partner_selection.not_found",
        "partner_selection.too_many_matches",
        "partner_selection.disambiguation_prompt",
        "invitation.invitee_not_on_courtduo",
        "invitation.delivery_failed",
        "invitation.send_cancelled",
        "moje_deble.not_registered",
    }
)

assert _TERMINAL_KEYS.isdisjoint(_MID_FLOW_KEYS), "a key cannot be both terminal and mid-flow"


def _is_send_call(node: ast.AST) -> bool:
    """A message-sending call -- `message.answer(text, ...)`,
    `callback.message.edit_text(...)`, `bot.send_message(chat_id, text,
    ...)`. Never `callback.answer()`: that dismisses a tap's loading
    spinner, takes no positional argument, and isn't a message at all --
    excluded here by requiring at least one positional argument, which
    every real send call has (the text) and a bare `callback.answer()`
    never does.
    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _SEND_METHODS
        and len(node.args) >= 1
    )


def _literal_locale_key(call: ast.Call) -> str | None:
    """The locale key this send call's text argument resolves to, when
    that argument is directly `t("some.key", ...)` with a literal string
    key -- the only shape traceable without evaluating the module."""
    if not call.args:
        return None
    first = call.args[0]
    if (
        isinstance(first, ast.Call)
        and isinstance(first.func, ast.Name)
        and first.func.id == "t"
        and first.args
        and isinstance(first.args[0], ast.Constant)
        and isinstance(first.args[0].value, str)
    ):
        return first.args[0].value
    return None


def _is_terminal_keyboard_call(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "terminal_keyboard"


def _carries_navigation(node: ast.expr | None) -> bool:
    """Some non-None reply_markup is attached -- terminal_keyboard()
    itself, or a flow-specific keyboard (e.g. none_eligible_keyboard())
    that has [Menu] folded into it alongside its own buttons."""
    return node is not None and not (isinstance(node, ast.Constant) and node.value is None)


def _reply_markup_value(call: ast.Call) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == "reply_markup":
            return kw.value
    return None


def _check_call(call: ast.Call, filename: str, lineno: int, violations: list[str]) -> None:
    key = _literal_locale_key(call)
    if key is None:
        return
    markup = _reply_markup_value(call)
    if key in _TERMINAL_KEYS and not _carries_navigation(markup):
        violations.append(f"{filename}:{lineno}: terminal key {key!r} sent with no navigation keyboard")
    elif key in _MID_FLOW_KEYS and _is_terminal_keyboard_call(markup):
        violations.append(f"{filename}:{lineno}: mid-flow key {key!r} sent with [Menu] (terminal_keyboard) attached")


def test_terminal_and_mid_flow_messages_carry_navigation_correctly():
    """CLAUDE.md build order step 8.2: every statically-traceable message
    using one of the curated locale keys above must (terminal) or must not
    (mid-flow) carry the [Menu] button -- so a future call site that
    reclassifies a message without updating its reply_markup, in either
    direction, fails this test instead of shipping.
    """
    violations: list[str] = []
    for path in sorted(_BOT_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = str(path.relative_to(_BOT_ROOT.parent))
        for node in ast.walk(tree):
            if _is_send_call(node):
                _check_call(node, relative, node.lineno, violations)

    assert violations == [], "terminal/mid-flow navigation mismatch:\n" + "\n".join(violations)
