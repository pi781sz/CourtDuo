"""Every string the invitation flow shows, composed here and nowhere else
(CLAUDE.md, "Never hardcode user-facing strings" — the text itself lives in
locales/pl.json; this module only decides which key and which arguments).

Polish inflects past-tense verbs for gender, so "przyjął zaproszenie" is
wrong for half the players. Every such string is stored as a pair of keys
under an `M` / `W` suffix and picked by `gendered()` from the gender
CourtDuo already stores on the account (derived at registration from which
ranking list the player appears in — CLAUDE.md, "Identity"). Genderless
strings stay flat keys; only verbs that actually inflect are split.

Two of these forms — "Odrzuciłeś zaproszenie od ..." and "Odpowiedziałeś,
że nie jedziesz na ten turniej." — appear in CLAUDE.md as flat masculine
sentences. They are split here rather than reproduced verbatim, with the
masculine member left character-for-character as CLAUDE.md writes it, so
a girl is not addressed in the masculine.

Nothing here is a message *between* players: every string is pre-defined
and every screen is buttons (CLAUDE.md, non-negotiable rule 1). No
composition path ever interpolates player-supplied text — only names,
tournament labels and dates that came from PZT.

Every name interpolated below goes through core.text.display_name first:
PZT stores "Nazwisko Imię" (surname first), and every user-facing message
must show "Imię Nazwisko" instead (CLAUDE.md, step 7.1, "Name order").
Callers pass the raw stored full_name in; this module is where it gets
reordered for display, once, so nobody downstream double-applies it.
"""

from __future__ import annotations

import logging

from bot.formatting import STATUS_EMOJI
from bot.i18n import t
from core.text import display_name
from db.models import InvitationState

logger = logging.getLogger(__name__)

_GENDER_KEYS = ("M", "W")
_FALLBACK_GENDER_KEY = "M"


def gendered(key: str, gender_code: str | None, lang: str, **kwargs: object) -> str:
    """`t()` for a key stored as an `M`/`W` pair.

    An unknown code falls back to the masculine form rather than raising:
    a missing gender must never cost a player their invitation, and the
    log line is enough to find it. accounts.gender is a NOT NULL 'M'/'W'
    column, so this should not happen.
    """
    code = gender_code if gender_code in _GENDER_KEYS else _FALLBACK_GENDER_KEY
    if code != gender_code:
        logger.warning("Unexpected gender code %r for %s; using %s", gender_code, key, _FALLBACK_GENDER_KEY)
    return t(f"{key}.{code}", lang, **kwargs)


# --- Inviter side, before the invitation exists --------------------------------


def confirmation_text(partner_name: str, tournament: str, lang: str) -> str:
    """The screen shown before anything is written (CLAUDE.md: the
    "cannot change partner" warning must come *before* confirming)."""
    return "\n".join(
        (
            t("invitation.confirm_partner", lang, name=display_name(partner_name)),
            t("invitation.confirm_tournament", lang, tournament=tournament),
            t("invitation.warning_cannot_change", lang),
        )
    )


def sent_text(partner_name: str, tournament: str, lang: str) -> str:
    return "\n".join(
        (
            t("invitation.sent", lang),
            t(
                "invitation.status_pending",
                lang,
                emoji=STATUS_EMOJI[InvitationState.PENDING],
                name=display_name(partner_name),
                tournament=tournament,
            ),
        )
    )


def already_invited_text(inviter_full_name: str, tournament: str, lang: str) -> str:
    """PROBLEM 3 (CLAUDE.md, "Pre-invitation checks"): shown instead of a
    confirmation screen when the named player already has a pending
    invitation to this player for this tournament -- redirects to the
    answer already owed rather than creating a second invitation chasing
    the same pair. Paired with the same invitation_answer_keyboard() the
    original notification carries.
    """
    return "\n".join(
        (
            t("partner_selection.already_invited_by", lang, name=display_name(inviter_full_name)),
            tournament,
            t("invitation.warning_cannot_change", lang),
        )
    )


# --- Invitee side, the invitation itself ---------------------------------------


def invitation_text(inviter_full_name: str, tournament: str, lang: str) -> str:
    """What the invited player receives.

    `inviter_full_name` is the full name (reordered to "Imię Nazwisko" via
    display_name()), never core.text.first_name(): the invitee is agreeing
    to something neither side can undo, so they must know exactly who is
    asking. first_name() is for greeting a player about themselves.
    """
    return "\n".join(
        (
            t("invitation.received", lang, name=display_name(inviter_full_name)),
            tournament,
            t("invitation.warning_cannot_change", lang),
        )
    )


# --- Answers -------------------------------------------------------------------


def matched_text(partner_full_name: str, tournament: str, lang: str) -> str:
    """The 🟢 line both sides see once an invitation is accepted."""
    return t(
        "invitation.status_matched",
        lang,
        emoji=STATUS_EMOJI[InvitationState.ACCEPTED],
        name=display_name(partner_full_name),
        tournament=tournament,
    )


def accepted_inviter_text(invitee_full_name: str, invitee_gender: str | None, tournament: str, lang: str) -> str:
    """The inviter's alert plus their new 🟢 status, in one message."""
    return "\n".join(
        (
            gendered("invitation.accepted_inviter", invitee_gender, lang, name=display_name(invitee_full_name)),
            matched_text(invitee_full_name, tournament, lang),
        )
    )


def rejected_invitee_text(
    inviter_full_name: str, invitee_gender: str | None, tournament: str, lang: str
) -> str:
    """What the invitee sees after tapping Odrzuć — second person, so it
    inflects for the invitee's own gender."""
    return gendered(
        "invitation.rejected_invitee",
        invitee_gender,
        lang,
        emoji=STATUS_EMOJI[InvitationState.REJECTED],
        name=display_name(inviter_full_name),
        tournament=tournament,
    )


def rejected_inviter_text(invitee_full_name: str, invitee_gender: str | None, tournament: str, lang: str) -> str:
    """What the inviter sees — third person about the invitee, so it
    inflects for the invitee's gender."""
    return gendered(
        "invitation.rejected_inviter",
        invitee_gender,
        lang,
        emoji=STATUS_EMOJI[InvitationState.REJECTED],
        name=display_name(invitee_full_name),
        tournament=tournament,
    )


def not_attending_invitee_text(invitee_gender: str | None, lang: str) -> str:
    return gendered("invitation.not_attending_invitee", invitee_gender, lang)


def not_attending_inviter_text(invitee_full_name: str, lang: str) -> str:
    """CLAUDE.md step 8.3, PROBLEM 2: 🔴, same as a refusal -- not gendered,
    since "nie jedzie" is the same for everyone."""
    return t(
        "invitation.not_attending_inviter",
        lang,
        emoji=STATUS_EMOJI[InvitationState.NOT_ATTENDING],
        name=display_name(invitee_full_name),
    )


# --- Cancelling (CLAUDE.md step 8.6) --------------------------------------------


def cancelled_inviter_text(invitee_full_name: str, tournament: str, lang: str) -> str:
    """The inviter's own confirmation after withdrawing a PENDING
    invitation they sent -- names the person and the tournament, per
    CLAUDE.md step 8.6."""
    return t("invitation.cancelled_inviter", lang, name=display_name(invitee_full_name), tournament=tournament)


def cancelled_invitee_text(inviter_full_name: str, inviter_gender: str | None, tournament: str, lang: str) -> str:
    """What the invitee is told when the inviter withdraws. Gendered on the
    *inviter's* gender (wycofał/wycofała) -- it's the inviter's action
    being described, third person, same shape as rejected_inviter_text."""
    return gendered(
        "invitation.cancelled_invitee",
        inviter_gender,
        lang,
        name=display_name(inviter_full_name),
        tournament=tournament,
    )
