"""One admin password, login sessions and login rate limiting.

The password comes from PORTAL_PASSWORD when set, otherwise from the first-run setup page (stored as an scrypt
hash). Sessions are random tokens in a cookie; "remember me" keeps one for 30 days, otherwise it lasts until the
browser closes (and at most a day on the server side). Every request goes through `current_user`, so roles can be
added later by returning more than a name.
"""
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request

from . import config, db

COOKIE = "portal_session"
REMEMBER_SECONDS = 30 * 24 * 3600
BROWSER_SESSION_SECONDS = 24 * 3600

# Rate limiting: after MAX_FAILURES failed logins from one address within WINDOW seconds, refuse for LOCKOUT.
MAX_FAILURES, WINDOW, LOCKOUT = 5, 60, 60
_failures: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1).hex()


def is_configured() -> bool:
    return config.ENV_PASSWORD is not None or db.get_setting("password") is not None


def set_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(400, "The password must be at least 8 characters.")
    salt = secrets.token_bytes(16)
    db.set_setting("password", {"salt": salt.hex(), "hash": _hash(password, salt)})
    db.execute("DELETE FROM sessions")  # a new password signs everyone out


def check_password(password: str) -> bool:
    if config.ENV_PASSWORD is not None:
        return hmac.compare_digest(password.encode(), config.ENV_PASSWORD.encode())
    stored = db.get_setting("password")
    if not stored:
        return False
    return hmac.compare_digest(_hash(password, bytes.fromhex(stored["salt"])), stored["hash"])


def client_address(request: Request) -> str:
    return request.client.host if request.client else "?"


def check_rate_limit(address: str) -> None:
    now = time.time()
    if _locked_until.get(address, 0) > now:
        raise HTTPException(429, f"Too many attempts. Try again in {int(_locked_until[address] - now) + 1} seconds.")


def record_failure(address: str) -> None:
    now = time.time()
    recent = [t for t in _failures.get(address, []) if now - t < WINDOW] + [now]
    _failures[address] = recent
    if len(recent) >= MAX_FAILURES:
        _locked_until[address] = now + LOCKOUT
        _failures[address] = []


def new_session(remember: bool) -> tuple[str, int | None]:
    """A session token and the cookie max-age (None: until the browser closes)."""
    token = secrets.token_urlsafe(32)
    lifetime = REMEMBER_SECONDS if remember else BROWSER_SESSION_SECONDS
    db.execute("INSERT INTO sessions VALUES (?, ?)", (token, time.time() + lifetime))
    db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
    return token, (REMEMBER_SECONDS if remember else None)


def end_session(token: str | None) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token=?", (token,))


def valid_session(token: str | None) -> bool:
    if not token:
        return False
    rows = db.execute("SELECT expires FROM sessions WHERE token=?", (token,))
    return bool(rows) and rows[0][0] > time.time()


def current_user(request: Request) -> str:
    if not valid_session(request.cookies.get(COOKIE)):
        raise HTTPException(401, "Not signed in.")
    return "admin"
