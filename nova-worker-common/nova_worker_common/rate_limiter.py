"""Per-domain async rate limiter."""
import asyncio
import time


class RateLimiter:
    """Token-bucket-style rate limiter with per-domain overrides.

    Usage::

        limiter = RateLimiter(default_rate=1.0)  # 1 req/s default
        limiter.set_domain_rate("api.github.com", 0.5)

        async with limiter.acquire("api.github.com"):
            await fetch(...)
    """

    def __init__(self, default_rate: float = 1.0) -> None:
        self._default_rate = default_rate
        self._domain_rates: dict[str, float] = {}
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_domain_rate(self, domain: str, rate: float) -> None:
        """Set a per-domain request rate (requests per second)."""
        self._domain_rates[domain] = rate

    def _get_lock(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    def _interval(self, domain: str) -> float:
        rate = self._domain_rates.get(domain, self._default_rate)
        return 1.0 / rate if rate > 0 else 0.0

    class _AcquireContext:
        """Async context manager returned by :meth:`RateLimiter.acquire`."""

        def __init__(self, limiter: "RateLimiter", domain: str) -> None:
            self._limiter = limiter
            self._domain = domain

        async def __aenter__(self) -> None:
            lock = self._limiter._get_lock(self._domain)
            await lock.acquire()
            interval = self._limiter._interval(self._domain)
            last = self._limiter._last_request.get(self._domain, 0.0)
            elapsed = time.monotonic() - last
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
            self._limiter._last_request[self._domain] = time.monotonic()

        async def __aexit__(self, *exc: object) -> None:
            lock = self._limiter._get_lock(self._domain)
            lock.release()

    def acquire(self, domain: str) -> "_AcquireContext":
        """Return an async context manager that blocks until the rate allows."""
        return self._AcquireContext(self, domain)
