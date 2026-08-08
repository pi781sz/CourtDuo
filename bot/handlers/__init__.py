from .invitations import router as invitations_router
from .navigation import router as navigation_router
from .partner_selection import router as partner_selection_router
from .start import router as start_router
from .tournament_search import router as tournament_search_router

__all__ = [
    "start_router",
    "tournament_search_router",
    "partner_selection_router",
    "invitations_router",
    "navigation_router",
]
