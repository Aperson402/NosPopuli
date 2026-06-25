"""Shared circuit breaker for api.congress.gov.

When the Library of Congress API is unreachable, we trip a process-wide
breaker for a cooldown window so callers don't waste 10s of wall clock
on every request. Foreground paths get an instant `CongressOutageError`
they can convert to a clean user-facing message; background paths just
skip.

Usage:

    from congress_breaker import congress_get, CongressOutageError

    try:
        r = congress_get(url, params={"api_key": KEY, ...}, timeout=10)
    except CongressOutageError:
        # Skip cleanly; the breaker handled logging.
        return None
"""
import time
from threading import RLock

import requests
from requests.adapters import HTTPAdapter

_COOLDOWN_SECONDS = 15 * 60
_breaker_until = 0.0
_lock = RLock()

# Shared session so every Congress.gov call enjoys HTTP keep-alive.
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=0)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)


class CongressOutageError(Exception):
    """Raised when api.congress.gov is in cooldown or the live call fails."""


def is_tripped():
    with _lock:
        return time.time() < _breaker_until


def trip():
    global _breaker_until
    with _lock:
        new_until = time.time() + _COOLDOWN_SECONDS
        if new_until > _breaker_until:
            _breaker_until = new_until
            print(f"[CONGRESS] Breaker tripped — suspending api.congress.gov calls for {_COOLDOWN_SECONDS // 60} min")


def clear():
    global _breaker_until
    with _lock:
        if _breaker_until:
            print("[CONGRESS] Breaker cleared — api.congress.gov responded")
            _breaker_until = 0.0


def cooldown_remaining_seconds():
    with _lock:
        return max(0, int(_breaker_until - time.time()))


def congress_get(url, params=None, timeout=10, **kwargs):
    """Shared GET against api.congress.gov respecting the breaker.

    Raises CongressOutageError if the breaker is tripped (no network call)
    or if the live call fails (and trips the breaker).
    Returns the requests.Response on success and clears the breaker.
    """
    if is_tripped():
        raise CongressOutageError(f"breaker open ({cooldown_remaining_seconds()}s remaining)")
    try:
        r = _session.get(url, params=params, timeout=timeout, **kwargs)
    except Exception as e:
        trip()
        raise CongressOutageError(f"live call failed: {type(e).__name__}") from e
    if r.status_code in (500, 502, 503, 504):
        trip()
        raise CongressOutageError(f"upstream {r.status_code}")
    clear()
    return r
