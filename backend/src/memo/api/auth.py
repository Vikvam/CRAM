"""The bot gate (PLAN 1, PLAN 5): one shared password, then an open profile picker.

The password is stored only as an argon2 hash. A session is a signed cookie —
nothing to look up, nothing to store — and logins are rate-limited per client.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from memo.config import Settings

COOKIE = "memo_session"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


class Gate:
    def __init__(self, settings: Settings):
        self.settings = settings
        secret = settings.secret_key.get_secret_value() if settings.secret_key else secrets.token_hex(32)
        self._signer = TimestampSigner(secret, salt="memo.session")
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def open(self) -> bool:
        """No password configured → no gate. Meant for localhost development only."""
        return not self.settings.auth_password_hash

    # --- rate limiting ------------------------------------------------------

    def _recent_failures(self, client: str, now: float) -> deque[float]:
        window = self.settings.login_window_seconds
        failures = self._failures[client]
        while failures and now - failures[0] > window:
            failures.popleft()
        return failures

    def check_rate(self, client: str) -> None:
        with self._lock:
            if len(self._recent_failures(client, time.monotonic())) >= self.settings.login_attempts:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again in a few minutes."
                )

    def _fail(self, client: str) -> None:
        with self._lock:
            self._failures[client].append(time.monotonic())

    # --- sessions -----------------------------------------------------------

    def login(self, client: str, password: str, response: Response) -> None:
        self.check_rate(client)
        if not self.open:
            try:
                _hasher.verify(self.settings.auth_password_hash, password)
            except (VerificationError, InvalidHashError):
                self._fail(client)
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password.") from None
        with self._lock:
            self._failures.pop(client, None)
        token = self._signer.sign(secrets.token_urlsafe(16)).decode()
        response.set_cookie(
            COOKIE,
            token,
            max_age=self.settings.session_days * 86400,
            httponly=True,
            samesite="lax",
            secure=self.settings.cookie_secure,
        )

    def logout(self, response: Response) -> None:
        response.delete_cookie(COOKIE)

    def is_signed_in(self, request: Request) -> bool:
        if self.open:
            return True
        token = request.cookies.get(COOKIE)
        if not token:
            return False
        try:
            self._signer.unsign(token, max_age=self.settings.session_days * 86400)
        except (BadSignature, SignatureExpired):
            return False
        return True

    def require(self, request: Request) -> None:
        if not self.is_signed_in(request):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first.")


#: Hosts whose ``X-Forwarded-For`` is believed: a proxy on this machine, and
#: nothing else. ``tailscale serve`` terminates TLS and forwards from here, so
#: without this every device on the tailnet would share one rate-limit bucket.
_LOOPBACK = frozenset({"127.0.0.1", "::1"})


def client_id(request: Request) -> str:
    """Who is being rate-limited. One bucket per device, proxy or no proxy."""
    peer = request.client.host if request.client else None
    if peer in _LOOPBACK:
        forwarded = request.headers.get("x-forwarded-for", "")
        # The last hop is the one our own proxy added; earlier ones are the client's word.
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return peer or "unknown"
