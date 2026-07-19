"""HTTP API routers for the AI Business Assistant backend.

Callers (see ``app.main``) import submodules by name::

    from .routers import auth, meetings, cli_api
    from .routers import media as media_router
    from .routers import permissions_api as permissions_router

This package intentionally does **not** eagerly import every router at
package load time. Eager imports enlarge the circular-import surface and
make a single broken optional module fail ``import app.routers`` for
everyone. Submodule imports resolve via the normal package import path
(``app.routers.<name>`` → ``app/routers/<name>.py``).

``__all__`` documents the public router modules; ``__getattr__`` provides
a clear error if a name is requested that is not a known router.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

# Keep in sync with modules under this package that main (or others) import.
__all__ = [
    "admin",
    "agents",
    "auth",
    "billing",
    "business",
    "business_products",
    "chat",
    "cli_api",
    "dashboard",
    "devices",
    "humans",
    "integrations",
    "keys",
    "marketplace",
    "media",
    "meetings",
    "ops",
    "org",
    "permissions_api",
    "templates",
    "training",
]


def __getattr__(name: str) -> Any:
    """Lazy-load known router submodules (PEP 562).

    Prefer ``from app.routers import meetings`` / ``from .routers import meetings``.
    Unknown names raise AttributeError (not a silent None).
    """
    if name in __all__:
        try:
            return import_module(f".{name}", __name__)
        except ModuleNotFoundError as e:
            raise AttributeError(
                f"router submodule {name!r} is listed in app.routers.__all__ "
                f"but could not be imported: {e}"
            ) from e
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
