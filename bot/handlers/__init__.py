from .account_deletion import router as account_deletion_router
from .invitations import router as invitations_router
from .invite_friend import router as invite_friend_router
from .moje_deble import router as moje_deble_router
from .navigation import router as navigation_router
from .partner_selection import router as partner_selection_router
from .pending_external_invites import router as pending_external_invites_router
from .start import router as start_router
from .status import router as status_router
from .tournament_search import router as tournament_search_router
from .viewers import router as viewers_router

__all__ = [
    "status_router",
    "start_router",
    "tournament_search_router",
    "partner_selection_router",
    "invitations_router",
    "navigation_router",
    "moje_deble_router",
    "invite_friend_router",
    "pending_external_invites_router",
    "viewers_router",
    "account_deletion_router",
]
