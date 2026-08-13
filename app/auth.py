"""Admin password hashing and signed session tokens.

Stdlib only -- no new dependency. The password itself is hashed with
PBKDF2-HMAC-SHA256; a session is an HMAC-signed cookie value, so verifying a
request never has to touch disk. The password's hash is folded into the
signature input, so rotating the password invalidates every session issued
under the old one for free, with no separate revocation list to maintain.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

ITERATIONS = 200_000
SESSION_MAX_AGE = 30 * 24 * 3600  # 30 days


def hash_password(password: str) -> tuple[str, str]:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), ITERATIONS)
    return hmac.compare_digest(digest.hex(), hash_hex)


def _sign(secret_hex: str, issued: str, password_hash_hex: str) -> str:
    return hmac.new(bytes.fromhex(secret_hex), f"{issued}.{password_hash_hex}".encode(),
                    hashlib.sha256).hexdigest()


def make_session_token(secret_hex: str, password_hash_hex: str) -> str:
    issued = str(int(time.time()))
    return f"{issued}.{_sign(secret_hex, issued, password_hash_hex)}"


def verify_session_token(token: str, secret_hex: str, password_hash_hex: str) -> bool:
    try:
        issued, sig = token.split(".", 1)
        if time.time() - int(issued) > SESSION_MAX_AGE:
            return False
    except ValueError:
        return False
    return hmac.compare_digest(sig, _sign(secret_hex, issued, password_hash_hex))
