"""Every string the account-deletion and match-release flows show,
composed here and nowhere else (CLAUDE.md, "Never hardcode user-facing
strings" -- text itself lives in locales/pl.json; this module only
decides which key and which arguments, the same split
bot.invitation_text follows).

The explanation and confirmation screens deliberately avoid second-person
past-tense verbs ("usunąłeś", "zwolniłeś") wherever the subject is the
account owner making the choice, since those inflect for gender and would
otherwise need an M/W pair for nearly every line. Passive/impersonal
phrasing ("zostanie usunięte", "zostaną anulowane") reads naturally in
Polish and sidesteps that -- only the handful of lines that genuinely
can't avoid an inflected verb (the confirmed-partner notification, the
release outcome) are split into gendered pairs via gendered().

One gendering shortcut is safe here and only here: every doubles match in
this bot is a same-gender event (CLAUDE.md, "Eligibility": "Gender must
match"), so a player's partner is always the same gender as the player
themselves. explain_screen_text can therefore gender its one inflected
clause ("będzie mógł/mogła zwolnić parę", about a not-yet-known partner)
on the *account owner's own* gender code and be correct for every match
they might have -- nowhere else in this bot could get away with that.
"""

from __future__ import annotations

from bot.i18n import t
from bot.invitation_text import gendered
from core.text import display_name


def explain_screen_text(gender_code: str, lang: str) -> str:
    """CLAUDE.md step 12, "Self-service deletion": "the confirmation
    screen must state plainly what will happen, including the effect on
    any confirmed match." Screen one of two."""
    return "\n".join(
        (
            t("deletion.explain_heading", lang),
            "",
            t("deletion.explain_intro", lang),
            t("deletion.explain_bullet_account", lang),
            t("deletion.explain_bullet_invitations", lang),
            gendered("deletion.explain_bullet_matches", gender_code, lang),
            t("deletion.explain_bullet_viewers", lang),
            "",
            t("deletion.explain_irreversible", lang),
        )
    )


def confirm_screen_text(lang: str) -> str:
    # Screen two of two -- CLAUDE.md step 12: "Two-step confirmation."
    return "\n".join((t("deletion.confirm_prompt", lang), "", t("deletion.explain_irreversible", lang)))


def partner_notified_text(deleted_full_name: str, deleted_gender: str, lang: str) -> str:
    """CLAUDE.md step 12, "What happens to a confirmed partner" -- the
    exact wording given there, gendered on the *deleted* player's own
    gender (usunął/usunęła)."""
    return gendered("deletion.partner_notified", deleted_gender, lang, name=display_name(deleted_full_name))


def release_confirm_text(remaining_gender_code: str, lang: str) -> str:
    """CLAUDE.md step 12: "a confirmation that says clearly this cannot be
    undone and they should only use it if they have actually spoken to the
    other person" -- gendered on the *remaining* player's own gender, the
    one actually typing/tapping this screen."""
    return gendered("deletion.release_confirm_prompt", remaining_gender_code, lang)


def release_done_text(remaining_gender_code: str, tournament: str, lang: str) -> str:
    return gendered("deletion.release_done", remaining_gender_code, lang, tournament=tournament)


def pending_cancelled_by_deletion_text(deleted_full_name: str, deleted_gender: str, tournament: str, lang: str) -> str:
    """CLAUDE.md step 12: "pending invitations they SENT are cancelled;
    each invitee is notified normally" and, symmetrically, "pending
    invitations they RECEIVED are cancelled; each inviter is notified
    normally." One wording covers both directions -- gendered on the
    *deleted* player, the only participant whose gender both notified
    parties are entitled to be told (their own counterparty's)."""
    return gendered(
        "deletion.invitation_cancelled_by_deletion",
        deleted_gender,
        lang,
        name=display_name(deleted_full_name),
        tournament=tournament,
    )
