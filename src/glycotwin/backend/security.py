"""Password hashing, session tokens and a small login throttle (standard library only; no secret key is needed).

Passwords: scrypt with a random 16-byte salt per password. The stored string is  scrypt$N$r$p$salt$hash  (base64), so the cost parameters can be raised
later and old hashes still verify (needs_rehash tells the caller to upgrade them at the next successful login). Plaintext passwords are never stored or logged.
Session tokens: 32 random bytes shown to the browser once (HttpOnly cookie); only the SHA-256 of the token is stored, so a copy of the database cannot be used to sign in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
import unicodedata
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2 ** 15, 8, 1, 32      # ~32 MiB and ~0.15 s per hash: slow for an attacker, fine for a person
SCRYPT_MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD, MAX_PASSWORD = 10, 128
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _prepare(password: str) -> bytes:
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def hash_password(password: str, *, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(_prepare(password), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=SCRYPT_DKLEN)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(dk)}"


def _parse(stored: str) -> Optional[Tuple[int, int, int, bytes, bytes]]:
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return None
        return int(n), int(r), int(p), base64.b64decode(salt), base64.b64decode(dk)
    except Exception:  # noqa: BLE001 - any malformed value simply fails verification
        return None


def verify_password(password: str, stored: Optional[str]) -> bool:
    parsed = _parse(stored) if stored else None
    if parsed is None:
        return False
    n, r, p, salt, dk = parsed
    try:
        cand = hashlib.scrypt(_prepare(password), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=len(dk))
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(cand, dk)


def needs_rehash(stored: str) -> bool:
    parsed = _parse(stored)
    return parsed is None or parsed[:3] != (SCRYPT_N, SCRYPT_R, SCRYPT_P)


# A real hash of a random password, used so that "no such account" takes as long as "wrong password" (no timing hint about which emails exist).
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def normalise_email(email: str) -> str:
    return email.strip().lower()


def password_problem(password: str, *, email: str = "", name: str = "") -> Optional[str]:
    """A short, honest policy (length, not trivially tied to the account); no composition rules. Returns the problem text or None."""
    if len(password) < MIN_PASSWORD:
        return f"password must be at least {MIN_PASSWORD} characters"
    if len(password) > MAX_PASSWORD:
        return f"password must be at most {MAX_PASSWORD} characters"
    low = password.strip().lower()
    if email and low == normalise_email(email):
        return "password must not be the same as the email address"
    if name and len(name.strip()) >= 4 and low == name.strip().lower():
        return "password must not be the same as the name"
    if len(set(password)) < 4:
        return "password is too repetitive"
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Throttle:
    """In-memory sliding-window limiter (per process; it resets when the server restarts). Used for failed logins and guest creation."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit, self.window = limit, window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> Deque[float]:
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def retry_after(self, key: str) -> int:
        """Seconds to wait if `key` is over the limit, else 0."""
        now = time.monotonic()
        q = self._prune(key, now)
        return int(self.window - (now - q[0])) + 1 if len(q) >= self.limit else 0

    def record(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now).append(now)

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)
