from typing import TYPE_CHECKING, Any

from finscrape.engine.scrapling.engines.toolbelt import ProxyRotator

if TYPE_CHECKING:
    from finscrape.engine.scrapling.engines.static import (
        FetcherSession,
    )
    from finscrape.engine.scrapling.fetchers.chrome import (
        AsyncDynamicSession,
        DynamicFetcher,
        DynamicSession,
    )
    from finscrape.engine.scrapling.fetchers.requests import (
        AsyncFetcher,
        Fetcher,
    )
    from finscrape.engine.scrapling.fetchers.stealth_chrome import (
        AsyncStealthySession,
        StealthyFetcher,
        StealthySession,
    )


# Lazy import mapping
_LAZY_IMPORTS = {
    "Fetcher": ("finscrape.engine.scrapling.fetchers.requests", "Fetcher"),
    "AsyncFetcher": ("finscrape.engine.scrapling.fetchers.requests", "AsyncFetcher"),
    "FetcherSession": ("finscrape.engine.scrapling.engines.static", "FetcherSession"),
    "DynamicFetcher": ("finscrape.engine.scrapling.fetchers.chrome", "DynamicFetcher"),
    "DynamicSession": ("finscrape.engine.scrapling.fetchers.chrome", "DynamicSession"),
    "AsyncDynamicSession": ("finscrape.engine.scrapling.fetchers.chrome", "AsyncDynamicSession"),
    "StealthyFetcher": ("finscrape.engine.scrapling.fetchers.stealth_chrome", "StealthyFetcher"),
    "StealthySession": ("finscrape.engine.scrapling.fetchers.stealth_chrome", "StealthySession"),
    "AsyncStealthySession": ("finscrape.engine.scrapling.fetchers.stealth_chrome", "AsyncStealthySession"),
}

__all__ = [
    "AsyncDynamicSession",
    "AsyncFetcher",
    "AsyncStealthySession",
    "DynamicFetcher",
    "DynamicSession",
    "Fetcher",
    "FetcherSession",
    "ProxyRotator",
    "StealthyFetcher",
    "StealthySession",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        module_path, class_name = _LAZY_IMPORTS[name]
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Support for dir() and autocomplete."""
    return sorted(list(_LAZY_IMPORTS.keys()))
