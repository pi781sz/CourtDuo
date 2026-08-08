"""Partner name entry and pre-invitation checks (CLAUDE.md, "Pre-invitation
checks"; build order step 6). start_partner_selection() is the single
entry point step 5 (bot.handlers.tournament_search) calls once a player
has tapped a tournament button.

Name matching is whole-name only, never a substring (CLAUDE.md: a
single-token or substring search over the `players` roster is exactly the
browsable directory CLAUDE.md forbids). Matching/labelling logic is pure
and unit-tested without a database in tests/test_partner_selection.py; the
DB-touching functions below it (candidate search, ranking lookups, the
pre-invitation checks themselves) are exercised against a real Postgres in
tests/test_partner_selection_db.py. bot.handlers.partner_selection is the
Telegram plumbing (the typed-name message handler and the disambiguation
button handler) wired around this module, the same split as
bot.tournament_search / bot.handlers.tournament_search.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum, auto
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import t
from bot.invitation_send import start_invitation_send
from bot.keyboards.tournament_search import category_keyboard
from bot.states import PartnerSelection, TournamentSearch
from core.text import display_name, fold_diacritics
from db import crud
from db.models import Account, AgeCategory, Player, Tournament
from entitlements import can_send_invitation
from scrapers.tournaments.models import resolve_ranking_code

# CLAUDE.md, "Name matching": "Cap candidates at 3. If more than 3 match,
# ask the player to check the spelling rather than listing them." A
# different concept from db.crud.MAX_PENDING_INVITATIONS_PER_TOURNAMENT,
# which happens to share the same value.
MAX_CANDIDATES = 3

_WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def _warsaw_today_and_utc_now() -> tuple[date, datetime]:
    """Mirrors bot.handlers.tournament_search's private helper of the same
    name. Duplicated rather than imported: that module already imports
    start_partner_selection from here, so importing back from it would be
    a circular import; this is the small piece it needs for the
    "inviter already matched" refusal, which re-shows the category screen
    without asking for a name at all (CLAUDE.md, "Pre-invitation checks").
    """
    now = datetime.now(timezone.utc)
    return now.astimezone(_WARSAW_TZ).date(), now


# --- Pure name matching (no DB, no Telegram) -------------------------------


def split_name_tokens(text: str) -> list[str]:
    return text.split()


def name_query_variants(tokens: list[str]) -> list[str]:
    """Both plausible whole-name readings of typed tokens. PZT stores
    "Nazwisko Imię" (surname first -- see core.text.first_name); a player
    usually types "Imię Nazwisko" instead. Swapping only makes sense for
    exactly two tokens -- for anything else there's no unambiguous
    reordering, so only the as-typed reading is offered.
    """
    variants = [" ".join(tokens)]
    if len(tokens) == 2:
        variants.append(" ".join(reversed(tokens)))
    return variants


def matches_full_name(full_name: str, tokens: list[str]) -> bool:
    """Whole-name match only, never a substring (CLAUDE.md, "Name
    matching": "Match on the whole name, not a substring. 'Kow' must
    return nothing."). Diacritic- and case-insensitive via fold_diacritics;
    whitespace is collapsed on both sides so a stray double space in
    either the typed query or PZT's own data can't cause a false miss.
    """
    folded_name = fold_diacritics(" ".join(full_name.split()))
    return any(fold_diacritics(variant) == folded_name for variant in name_query_variants(tokens))


class MatchOutcome(Enum):
    NOT_FOUND = auto()
    SINGLE = auto()
    DISAMBIGUATE = auto()
    TOO_MANY = auto()


def classify_matches(matches: list) -> MatchOutcome:
    """How to act on a whole-name search's results (CLAUDE.md,
    "Disambiguation" and "Cap candidates at 3")."""
    if not matches:
        return MatchOutcome.NOT_FOUND
    if len(matches) == 1:
        return MatchOutcome.SINGLE
    if len(matches) > MAX_CANDIDATES:
        return MatchOutcome.TOO_MANY
    return MatchOutcome.DISAMBIGUATE


# --- Candidate search and disambiguation labelling (DB) ---------------------


async def find_matching_players(session: AsyncSession, tokens: list[str]) -> list[Player]:
    """Whole-name search over the `players` table (the PZT roster, not
    `accounts` -- whether the named person uses CourtDuo is step 7's
    problem). Filtered in Python rather than in SQL: Postgres ILIKE can't
    fold Polish diacritics without the `unaccent` extension, and the
    roster is small enough (PZT's junior roster, ~1,900 players) that a
    full-table scan is fine -- see bot.player_search for the same
    reasoning applied to a different (substring) matching rule.
    """
    result = await session.execute(select(Player))
    players = result.scalars().all()
    return [player for player in players if matches_full_name(player.full_name, tokens)]


@dataclass(frozen=True)
class CandidateOption:
    pzt_id: str
    label: str


async def _resolve_candidate_ranking(
    session: AsyncSession,
    candidate: Player,
    tournament_age_category: AgeCategory,
    period: tuple[int, int] | None,
) -> tuple[str, int | None] | None:
    """The (ranking_list code, position) to show for one disambiguation
    candidate, or None if they have no ranking row at all in the newest
    period. Prefers the row matching the tournament's age category and the
    candidate's own gender; if the player has none there, falls back to
    any row they do have, labelled with its own list code (CLAUDE.md,
    "Disambiguation").
    """
    if period is None:
        return None
    year, month = period
    rankings = await crud.get_rankings_for_player_in_period(session, candidate.pzt_id.upper(), year, month)
    if not rankings:
        return None

    preferred_code = resolve_ranking_code(tournament_age_category, candidate.gender) if candidate.gender else None
    preferred = next((r for r in rankings if r.ranking_list.code == preferred_code), None)
    chosen = preferred or rankings[0]
    return chosen.ranking_list.code, chosen.position


def _candidate_label(full_name: str, ranking: tuple[str, int | None] | None, lang: str) -> str:
    name = display_name(full_name)
    if ranking is None:
        return t("partner_selection.candidate_no_ranking", lang, name=name)
    list_code, position = ranking
    if position is None:
        return t("partner_selection.candidate_label_no_position", lang, name=name, list=list_code)
    return t("partner_selection.candidate_label", lang, name=name, list=list_code, position=position)


async def build_candidate_options(
    session: AsyncSession, candidates: list[Player], tournament_age_category: AgeCategory, lang: str
) -> list[CandidateOption]:
    """One button per name-matched candidate, labelled with enough to tell
    them apart -- their ranking-list position, never club or school
    (CLAUDE.md, "Disambiguation": "position is enough to disambiguate and
    is already public on PZT's ranking pages").
    """
    period = await crud.get_latest_ranking_period_overall(session)
    options = []
    for candidate in candidates:
        ranking = await _resolve_candidate_ranking(session, candidate, tournament_age_category, period)
        options.append(
            CandidateOption(pzt_id=candidate.pzt_id, label=_candidate_label(candidate.full_name, ranking, lang))
        )
    return options


# --- Pre-invitation checks (DB) ---------------------------------------------


class CheckFailure(Enum):
    SELF_INVITE = auto()
    GENDER_MISMATCH = auto()
    INVITEE_ALREADY_MATCHED = auto()
    PENDING_INVITATION_EXISTS = auto()
    MAX_PENDING_REACHED = auto()


async def run_pre_invitation_checks(
    session: AsyncSession, account: Account, tournament: Tournament, candidate: Player
) -> CheckFailure | None:
    """CLAUDE.md, "Pre-invitation checks", run against an already-resolved
    candidate -- checks 1, 2, 4, 5 and 6 in that order. Check 3 ("the
    inviter is already matched") runs earlier, in start_partner_selection,
    before a name is even asked for.
    """
    if candidate.pzt_id == account.pzt_id:
        return CheckFailure.SELF_INVITE

    event_gender = crud.gender_for_account_code(account.gender)
    if candidate.gender != event_gender:
        return CheckFailure.GENDER_MISMATCH

    if await crud.get_matched_invitation(session, candidate.pzt_id, tournament.guid) is not None:
        return CheckFailure.INVITEE_ALREADY_MATCHED

    if await crud.get_pending_invitation(session, account.pzt_id, candidate.pzt_id, tournament.guid) is not None:
        return CheckFailure.PENDING_INVITATION_EXISTS

    pending_count = await crud.count_pending_outgoing_invitations(session, account.pzt_id, tournament.guid)
    if pending_count >= crud.MAX_PENDING_INVITATIONS_PER_TOURNAMENT:
        return CheckFailure.MAX_PENDING_REACHED

    return None


_CHECK_FAILURE_MESSAGE_KEYS: dict[CheckFailure, str] = {
    CheckFailure.SELF_INVITE: "partner_selection.self_invite",
    CheckFailure.GENDER_MISMATCH: "partner_selection.gender_mismatch",
    CheckFailure.INVITEE_ALREADY_MATCHED: "partner_selection.invitee_already_matched",
    CheckFailure.PENDING_INVITATION_EXISTS: "partner_selection.pending_invitation_exists",
    CheckFailure.MAX_PENDING_REACHED: "partner_selection.max_pending_reached",
}


async def handle_partner_candidate(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    lang: str,
    account: Account,
    tournament: Tournament,
    candidate: Player,
) -> None:
    """Runs every remaining pre-invitation check against a resolved
    candidate (whether resolved directly from a single name match or via a
    disambiguation tap) and, if all pass, hands off to step 7. Every
    refusal leaves the player in PartnerSelection.waiting_name so they can
    type another name -- CLAUDE.md, "Never dead-end".
    """
    failure = await run_pre_invitation_checks(session, account, tournament, candidate)
    if failure is not None:
        await message.answer(t(_CHECK_FAILURE_MESSAGE_KEYS[failure], lang, name=display_name(candidate.full_name)))
        return

    # CLAUDE.md, "Monetisation": every invitation must route through this
    # seam even though it always returns True until paid tiers launch. The
    # send transaction asks again at the moment it writes the row; this
    # call is what keeps a player from reaching a confirmation screen they
    # are not entitled to act on.
    if not await can_send_invitation(account, tournament):
        await message.answer(t("partner_selection.cannot_send_invitation", lang))
        return

    await start_invitation_send(message, state, lang, session, account, tournament, candidate)


# --- Entry point -------------------------------------------------------------


async def start_partner_selection(
    message: Message, state: FSMContext, lang: str, session: AsyncSession, account: Account, tournament: Tournament
) -> None:
    """Entry point step 5 calls once a tournament has been picked
    (CLAUDE.md build order step 6). Runs check 3 ("the inviter is already
    matched at this tournament") before asking for a name at all, per
    CLAUDE.md's "Pre-invitation checks" -- there's no point asking who to
    invite when the player already has a partner here.
    """
    matched = await crud.get_matched_invitation(session, account.pzt_id, tournament.guid)
    if matched is not None:
        partner_pzt_id = (
            matched.invitee_pzt_id if matched.inviter_pzt_id == account.pzt_id else matched.inviter_pzt_id
        )
        partner = await crud.get_player_by_pzt_id(session, partner_pzt_id)
        await message.answer(t("partner_selection.inviter_already_matched", lang, name=display_name(partner.full_name)))

        # No name to ask for -- CLAUDE.md, "Never dead-end": offer a way
        # back to the tournament list rather than leaving nothing to tap.
        gender = crud.gender_for_account_code(account.gender)
        today, now = _warsaw_today_and_utc_now()
        counts = await crud.get_eligible_tournament_counts_by_category(session, gender, today, now)
        await message.answer(t("tournament_search.ask_category", lang), reply_markup=category_keyboard(counts, lang))
        await state.set_state(TournamentSearch.waiting_category)
        return

    await message.answer(t("partner_selection.ask_name", lang))
    await state.set_state(PartnerSelection.waiting_name)
