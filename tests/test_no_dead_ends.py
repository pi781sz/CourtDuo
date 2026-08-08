"""Static audit: every message-sending call site in bot/ must carry a
reply_markup (CLAUDE.md, "A terminal message always carries a way back";
build order step 8.1's mechanical audit). This is the test that is
supposed to stop the problem step 8's original, by-hand audit missed --
so it inspects source with `ast`, not runtime behaviour: the point is to
catch a *future* call site that forgets a keyboard before it ships, not to
exercise every branch of every handler (which would only catch what a test
happens to drive).

The only call sites allowed to omit reply_markup are ones immediately
followed, in the same straight-line block, by another such call that does
carry one -- two message bubbles land together with nothing tappable in
between, and only the later one needs to be actionable (CLAUDE.md: "The
only exceptions are messages that are immediately followed by another
message that does carry a keyboard").
"""

from __future__ import annotations

import ast
import pathlib

_BOT_ROOT = pathlib.Path(__file__).resolve().parent.parent / "bot"
_SEND_METHODS = {"answer", "edit_text", "send_message"}


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


def _has_reply_markup(call: ast.Call) -> bool:
    return any(kw.arg == "reply_markup" for kw in call.keywords)


def _send_call_in_statement(stmt: ast.stmt) -> ast.Call | None:
    """The send call this statement directly performs -- a bare (possibly
    awaited) expression statement. Anything nested deeper -- inside a
    comprehension, a lambda, an argument to some other call -- doesn't
    count: only a call this exact statement always reaches matters for
    "immediately followed by".
    """
    value = stmt.value if isinstance(stmt, ast.Expr) else None
    if isinstance(value, ast.Await):
        value = value.value
    if isinstance(value, ast.Call) and _is_send_call(value):
        return value
    return None


def _nested_blocks(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """Every straight-line block nested in this statement, each checked
    independently -- a keyboarded call in one branch of an `if` says
    nothing about whether a bare call in the *other* branch dead-ends.
    """
    blocks: list[list[ast.stmt]] = []
    if isinstance(stmt, ast.If):
        blocks.append(stmt.body)
        if stmt.orelse:
            blocks.append(stmt.orelse)
    elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
        blocks.append(stmt.body)
        if stmt.orelse:
            blocks.append(stmt.orelse)
    elif isinstance(stmt, (ast.With, ast.AsyncWith)):
        blocks.append(stmt.body)
    elif isinstance(stmt, ast.Try):
        blocks.append(stmt.body)
        for handler in stmt.handlers:
            blocks.append(handler.body)
        if stmt.orelse:
            blocks.append(stmt.orelse)
        if stmt.finalbody:
            blocks.append(stmt.finalbody)
    return blocks


def _check_block(stmts: list[ast.stmt], filename: str, violations: list[str]) -> None:
    calls_in_order = [(stmt, _send_call_in_statement(stmt)) for stmt in stmts]
    for index, (stmt, call) in enumerate(calls_in_order):
        if call is None or _has_reply_markup(call):
            continue
        later_has_markup = any(
            later_call is not None and _has_reply_markup(later_call) for _, later_call in calls_in_order[index + 1 :]
        )
        if not later_has_markup:
            violations.append(f"{filename}:{stmt.lineno}")
    for stmt in stmts:
        for block in _nested_blocks(stmt):
            _check_block(block, filename, violations)


def test_no_message_send_without_a_keyboard():
    """A future handler that adds a bare `message.answer(...)` /
    `callback.message.edit_text(...)` / `bot.send_message(...)` with no
    reply_markup, and no follow-up call that has one, fails this test --
    CLAUDE.md build order step 8.1: "no message-sending call site in bot/
    lacks a keyboard ... the test that stops this recurring."
    """
    violations: list[str] = []
    for path in sorted(_BOT_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = str(path.relative_to(_BOT_ROOT.parent))
        _check_block(tree.body, relative, violations)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _check_block(node.body, relative, violations)

    assert violations == [], "message sent without reply_markup, and not immediately followed by one:\n" + "\n".join(
        violations
    )
