"""
auth_service.py - Authentication, Password Security, Lockout Tracker & JWT Token Services.
Enforces security requirements for SentinelAuth border terminal console:
1. 12+ char password minimum with weak password blocklist.
2. Max 5 failed attempts per username per 15 minutes -> 15-minute account lockout.
3. Short-lived in-memory access tokens (~15 min) + httpOnly refresh tokens.
4. CSRF token generation and verification.
5. Server-side token blocklist checking.
"""
from datetime import datetime, timedelta
import logging
import os
import secrets
from typing import Any, Dict, List, Optional, Set, Tuple
import jwt
from sqlalchemy.orm import Session

from ..db.models import User
from ..db.crud import (
    get_user_by_username,
    get_user_by_badge_id,
    verify_password,
    is_token_revoked,
    revoke_token
)

logger = logging.getLogger("sentinel.auth")

# Secret key for signing JWTs
JWT_SECRET_KEY = os.environ.get("SENTINEL_JWT_SECRET", "sentinel-auth-secure-jwt-key-2026-mha-ssb")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 1

# Common weak passwords blocklist (rejected even if 12+ chars)
COMMON_WEAK_PASSWORDS: Set[str] = {
    "password1234",
    "password12345",
    "password123456",
    "admin12345678",
    "administrator1",
    "sentinelauth1",
    "sentinelauth2026",
    "qwerty12345678",
    "123456789012",
    "1234567890123",
    "welcome123456",
    "letmein123456",
    "passcode12345",
    "ssbpolice2026",
    "bordersecurity",
    "checkpoint2026",
    "iloveyou12345"
}


def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    """
    Enforces strict border terminal security password requirements:
    - Minimum length: 12+ characters
    - Mix of uppercase, lowercase, numbers, and special symbols
    - Not present in the common weak passwords blocklist
    """
    if not password or len(password) < 12:
        return False, "Password must be at least 12 characters long."
    
    clean_pw = password.strip().lower()
    if clean_pw in COMMON_WEAK_PASSWORDS:
        return False, "Password matches a common weak password. Please choose a stronger passphrase."

    if not any(c.isupper() for c in password):
        return False, "Password must include at least one uppercase letter (A-Z)."

    if not any(c.islower() for c in password):
        return False, "Password must include at least one lowercase letter (a-z)."

    if not any(c.isdigit() for c in password):
        return False, "Password must include at least one numeric digit (0-9)."

    if not any(not c.isalnum() for c in password):
        return False, "Password must include at least one special symbol (e.g. !@#$%^&*)."

    return True, None


def generate_temporary_password(length: int = 12) -> str:
    """
    Generates a secure, cryptographically random temporary password.
    Enforces mix of uppercase, lowercase, numeric digits, and symbols,
    guaranteeing it satisfies validate_password_strength.
    """
    uppers = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # exclude confusing I, O
    lowers = "abcdefghjkmnpqrstuvwxyz"   # exclude confusing l, o
    digits = "23456789"                  # exclude confusing 0, 1
    symbols = "!@#$%^&*"

    # Guarantee at least one character from each class
    pw_chars = [
        secrets.choice(uppers),
        secrets.choice(lowers),
        secrets.choice(digits),
        secrets.choice(symbols)
    ]

    all_chars = uppers + lowers + digits + symbols
    for _ in range(max(0, length - 4)):
        pw_chars.append(secrets.choice(all_chars))

    secrets.SystemRandom().shuffle(pw_chars)
    pw = "".join(pw_chars)
    if pw.lower() in COMMON_WEAK_PASSWORDS:
        return generate_temporary_password(length)
    return pw



class LoginAttemptTracker:
    """
    In-memory tracking for failed login attempts and account lockout.
    Enforces: max 5 failed attempts per username within 15 minutes.
    After 5 failures, locks the account for 15 minutes.
    """
    def __init__(self, max_attempts: int = 5, lockout_minutes: int = 15):
        self.max_attempts = max_attempts
        self.lockout_minutes = lockout_minutes
        # username -> list of failure datetimes
        self._failures: Dict[str, List[datetime]] = {}
        # username -> lockout expiration datetime
        self._lockouts: Dict[str, datetime] = {}

    def _process_unlock_requests(self):
        """
        Processes external unlock requests written by CLI tools (e.g. reset_admin.py)
        to clear lockouts without requiring a server reboot.
        """
        try:
            unlock_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", ".unlock_requests")
            if os.path.exists(unlock_path):
                with open(unlock_path, "r", encoding="utf-8") as f:
                    usernames = [l.strip().lower() for l in f if l.strip()]
                for u in usernames:
                    self._failures.pop(u, None)
                    self._lockouts.pop(u, None)
                try:
                    os.remove(unlock_path)
                except OSError:
                    pass
        except Exception as exc:
            logger.debug(f"Failed processing unlock requests: {exc}")

    def is_locked(self, username: str) -> Tuple[bool, Optional[int]]:
        """
        Checks if the username is currently locked.
        Returns: (is_locked, remaining_seconds_or_none)
        """
        self._process_unlock_requests()
        user_key = username.strip().lower()
        now = datetime.utcnow()

        if user_key in self._lockouts:
            lockout_expiry = self._lockouts[user_key]
            if now < lockout_expiry:
                remaining = int((lockout_expiry - now).total_seconds())
                return True, max(1, remaining)
            else:
                # Lockout expired
                del self._lockouts[user_key]
                self._failures[user_key] = []
                return False, None

        return False, None

    def record_failure(self, username: str) -> Tuple[bool, int, Optional[int]]:
        """
        Records a failed login attempt for username.
        Returns: (is_now_locked, total_recent_failures, lockout_remaining_seconds)
        """
        user_key = username.strip().lower()
        now = datetime.utcnow()
        window_start = now - timedelta(minutes=self.lockout_minutes)

        # Clean old failures outside 15-min window
        recent_failures = [t for t in self._failures.get(user_key, []) if t > window_start]
        recent_failures.append(now)
        self._failures[user_key] = recent_failures

        if len(recent_failures) >= self.max_attempts:
            # Lock the account for 15 minutes
            lockout_expiry = now + timedelta(minutes=self.lockout_minutes)
            self._lockouts[user_key] = lockout_expiry
            logger.warning(
                f"[Security Alert] Account '{user_key}' locked out for {self.lockout_minutes} minutes "
                f"due to {len(recent_failures)} failed login attempts."
            )
            return True, len(recent_failures), int(self.lockout_minutes * 60)

        return False, len(recent_failures), None

    def record_success(self, username: str):
        """Clears failed attempts and lockouts upon successful authentication."""
        user_key = username.strip().lower()
        self._failures.pop(user_key, None)
        self._lockouts.pop(user_key, None)


# Global singleton instance
login_tracker = LoginAttemptTracker(max_attempts=5, lockout_minutes=15)


def create_access_token(user: User) -> Tuple[str, str, int]:
    """
    Generates a short-lived access JWT (15 minutes).
    Returns: (encoded_jwt, jti, expires_in_seconds)
    """
    jti = secrets.token_hex(16)
    expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    now = datetime.utcnow()
    exp = now + timedelta(seconds=expires_in)

    payload = {
        "sub": user.username,
        "badge_id": user.badge_id,
        "officer_name": user.officer_name,
        "role": user.role,
        "station_id": user.station_id,
        "must_change_password": bool(getattr(user, "must_change_password", False)),
        "token_type": "access",
        "jti": jti,
        "iat": now,
        "exp": exp
    }

    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, jti, expires_in


def create_refresh_token(user: User) -> Tuple[str, str, datetime]:
    """
    Generates a longer-lived refresh JWT (24 hours) for httpOnly cookie storage.
    Returns: (encoded_jwt, jti, expires_at_datetime)
    """
    jti = secrets.token_hex(16)
    now = datetime.utcnow()
    exp = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": user.username,
        "badge_id": user.badge_id,
        "token_type": "refresh",
        "jti": jti,
        "iat": now,
        "exp": exp
    }

    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, jti, exp


def decode_and_validate_token(db: Session, token: str, expected_type: str = "access") -> Dict[str, Any]:
    """
    Decodes and validates a JWT token:
    - Checks expiration and signature.
    - Confirms token_type matches expected_type.
    - Verifies token JTI is NOT in the revocation blocklist.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired. Please re-authenticate.")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid authentication token: {str(e)}")

    if payload.get("token_type") != expected_type:
        raise ValueError(f"Expected {expected_type} token, got {payload.get('token_type')}")

    jti = payload.get("jti")
    if jti and is_token_revoked(db, jti):
        raise ValueError("Session token has been revoked / logged out.")

    return payload


def generate_csrf_token() -> str:
    """Generates a cryptographically secure random CSRF token."""
    return secrets.token_urlsafe(32)


def verify_csrf_token(header_token: Optional[str], cookie_token: Optional[str]) -> bool:
    """Validates CSRF token using constant-time string comparison."""
    if not header_token or not cookie_token:
        return False
    return secrets.compare_digest(header_token, cookie_token)
