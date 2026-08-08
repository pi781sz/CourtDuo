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

from bot.invitation_text import (
    accepted_inviter_text,
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


def test_not_attending_seen_by_inviter_is_neutral_and_not_a_refusal():
    text = not_attending_inviter_text("Testowa Jagoda", "pl")

    # 🟠, distinct from the 🔴 of a refusal (CLAUDE.md), and the same
    # sentence whoever the player is -- "nie jedzie" does not inflect.
    assert text == "🟠 Jagoda Testowa nie jedzie na ten turniej."
    assert "🔴" not in text
    assert text == not_attending_inviter_text("Testowa Jagoda", "pl")


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

    assert text == f"Zaproszenie zostało wysłane. Czekaj na odpowiedź.\n⚪ Jagoda Testowa — {_LABEL}"


def test_matched_line_names_the_partner_and_the_tournament():
    assert matched_text("Testowa Jagoda", _LABEL, "pl") == f"🟢 Partner: Jagoda Testowa — {_LABEL}"
