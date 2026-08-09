"""Wording tests for the invitation flow (CLAUDE.md, "Invitation engine";
build order step 7). Pure — no database, no Telegram.

Most of these exist for one reason: Polish inflects past-tense verbs for
gender, so a string that reads correctly for a boy is wrong for a girl.
CourtDuo already knows every player's gender (derived at registration from
which ranking list they appear in), so there is no excuse for getting it
wrong, and a regression here would be invisible to anyone reading the
code in English.

Names are passed in PZT's stored "Nazwisko Imię" (surname first) order,
e.g. "Testowa Jagoda" (surname "Testowa", given name "Jagoda") -- exactly
what accounts.full_name/players.full_name hold. Every assertion below
expects the "Imię Nazwisko" (given name first) order these functions must
display instead (CLAUDE.md, step 7.1, "Name order").

Invented names only, per CLAUDE.md.
"""

from __future__ import annotations

import logging

from bot.formatting import STATUS_EMOJI
from bot.invitation_text import (
    accepted_inviter_text,
    cancelled_invitee_text,
    cancelled_inviter_text,
    confirmation_text,
    gendered,
    invitation_text,
    matched_text,
    not_attending_invitee_text,
    not_attending_inviter_text,
    rejected_invitee_text,
    rejected_inviter_text,
    sent_text,
)
from db.models import InvitationState

_LABEL = "WTK Uniejów - 22.08.2026"


# --- gendered verb forms -------------------------------------------------------


def test_accepted_alert_uses_masculine_verb_for_a_boy():
    text = accepted_inviter_text("Testowy Marek", "M", _LABEL, "pl")

    assert text.startswith("Marek Testowy przyjął zaproszenie.")


def test_accepted_alert_uses_feminine_verb_for_a_girl():
    text = accepted_inviter_text("Testowa Jagoda", "W", _LABEL, "pl")

    assert text.startswith("Jagoda Testowa przyjęła zaproszenie.")


def test_rejection_seen_by_inviter_inflects_for_the_invitee():
    assert rejected_inviter_text("Testowy Marek", "M", _LABEL, "pl") == (
        f"🔴 Marek Testowy odrzucił zaproszenie — {_LABEL}."
    )
    assert rejected_inviter_text("Testowa Jagoda", "W", _LABEL, "pl") == (
        f"🔴 Jagoda Testowa odrzuciła zaproszenie — {_LABEL}."
    )


def test_rejection_seen_by_invitee_inflects_for_the_invitee_themselves():
    # Second person: the verb agrees with the person being addressed, not
    # with the inviter being named.
    assert rejected_invitee_text("Testowa Anna", "M", _LABEL, "pl") == (
        f"🔴 Odrzuciłeś zaproszenie od Anna Testowa — {_LABEL}."
    )
    assert rejected_invitee_text("Testowa Anna", "W", _LABEL, "pl") == (
        f"🔴 Odrzuciłaś zaproszenie od Anna Testowa — {_LABEL}."
    )


def test_not_attending_inflects_for_the_invitee():
    assert not_attending_invitee_text("M", "pl") == "Odpowiedziałeś, że nie jedziesz na ten turniej."
    assert not_attending_invitee_text("W", "pl") == "Odpowiedziałaś, że nie jedziesz na ten turniej."


def test_not_attending_seen_by_inviter_uses_the_same_colour_as_a_refusal():
    text = not_attending_inviter_text("Testowa Jagoda", "pl")

    # CLAUDE.md step 8.3, PROBLEM 2: same 🔴 as a refusal now -- the colour
    # only needs to say "not happening", the wording still carries the
    # distinction. Not gendered: "nie jedzie" is the same for everyone.
    assert text == "🔴 Jagoda Testowa nie jedzie na ten turniej."
    assert text == not_attending_inviter_text("Testowa Jagoda", "pl")


def test_cancelled_invitee_uses_masculine_verb_for_a_boy_inviter():
    text = cancelled_invitee_text("Testowy Marek", "M", _LABEL, "pl")

    assert text == f"Marek Testowy wycofał zaproszenie — {_LABEL}."


def test_cancelled_invitee_uses_feminine_verb_for_a_girl_inviter():
    text = cancelled_invitee_text("Testowa Jagoda", "W", _LABEL, "pl")

    assert text == f"Jagoda Testowa wycofała zaproszenie — {_LABEL}."


def test_unknown_gender_falls_back_to_masculine_and_logs(caplog):
    with caplog.at_level(logging.WARNING):
        text = gendered("invitation.accepted_inviter", None, "pl", name="Testowy Marek")

    assert text == "Testowy Marek przyjął zaproszenie."
    assert any("Unexpected gender code" in record.message for record in caplog.records)


# --- composition ---------------------------------------------------------------


def test_confirmation_warns_before_the_invitation_exists():
    text = confirmation_text("Testowa Jagoda", _LABEL, "pl")

    assert text == (
        "Zaproszenie do: Jagoda Testowa\n"
        f"Turniej: {_LABEL}\n"
        "Uwaga: po akceptacji nie można zmienić partnera."
    )


def test_invitation_names_the_inviter_in_full_and_carries_the_warning():
    # CLAUDE.md, step 7: the full name, never first_name() -- the invitee
    # is agreeing to something neither side can undo. Still reordered to
    # "Imię Nazwisko" via display_name() (CLAUDE.md, step 7.1).
    text = invitation_text("Testowa Anna", _LABEL, "pl")

    assert text == (
        "Anna Testowa zaprasza Cię do gry podwójnej.\n"
        f"{_LABEL}\n"
        "Uwaga: po akceptacji nie można zmienić partnera."
    )


def test_sent_confirmation_shows_the_pending_marker():
    text = sent_text("Testowa Jagoda", _LABEL, "pl")

    # CLAUDE.md step 8.3, PROBLEM 2: 🟠 pending, not the old ⚪.
    assert text == f"Zaproszenie zostało wysłane. Czekaj na odpowiedź.\n🟠 Jagoda Testowa — {_LABEL}"


def test_matched_line_names_the_partner_and_the_tournament():
    assert matched_text("Testowa Jagoda", _LABEL, "pl") == f"🟢 Partner: Jagoda Testowa — {_LABEL}"


def test_cancelled_inviter_names_the_withdrawn_partner_and_the_tournament():
    assert cancelled_inviter_text("Testowa Jagoda", _LABEL, "pl") == f"Anulowano zaproszenie do Jagoda Testowa — {_LABEL}."


# --- CLAUDE.md step 8.3, PROBLEM 2: every colour comes from STATUS_EMOJI ------


def test_every_status_message_uses_the_status_emoji_lookup_not_a_literal():
    assert sent_text("Testowa Jagoda", _LABEL, "pl").endswith(
        f"{STATUS_EMOJI[InvitationState.PENDING]} Jagoda Testowa — {_LABEL}"
    )
    assert matched_text("Testowa Jagoda", _LABEL, "pl") == (
        f"{STATUS_EMOJI[InvitationState.ACCEPTED]} Partner: Jagoda Testowa — {_LABEL}"
    )
    assert rejected_invitee_text("Testowa Anna", "W", _LABEL, "pl") == (
        f"{STATUS_EMOJI[InvitationState.REJECTED]} Odrzuciłaś zaproszenie od Anna Testowa — {_LABEL}."
    )
    assert rejected_inviter_text("Testowa Jagoda", "W", _LABEL, "pl") == (
        f"{STATUS_EMOJI[InvitationState.REJECTED]} Jagoda Testowa odrzuciła zaproszenie — {_LABEL}."
    )
    assert not_attending_inviter_text("Testowa Jagoda", "pl") == (
        f"{STATUS_EMOJI[InvitationState.NOT_ATTENDING]} Jagoda Testowa nie jedzie na ten turniej."
    )
    # CLAUDE.md step 8.3, PROBLEM 2: rejected and not-attending now share
    # the same colour -- "not happening" either way.
    assert STATUS_EMOJI[InvitationState.REJECTED] == STATUS_EMOJI[InvitationState.NOT_ATTENDING]
