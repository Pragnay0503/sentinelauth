"""
routes_auth.py - Hardened Duty Officer Authentication, Session Management,
Admin User Provisioning, Password Lifecycle, CSRF Protection, and Data Retention.
"""
from datetime import datetime
import logging
import secrets
from typing import Any, Dict, List, Optional
import jwt
from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..db.models import User
from ..db.crud import (
    get_user_by_username,
    get_user_by_badge_id,
    get_user_by_id,
    verify_password,
    hash_password,
    revoke_token,
    create_user,
    list_users,
    update_user_password,
    set_user_active,
    record_user_login
)
from ..services.auth_service import (
    login_tracker,
    create_access_token,
    create_refresh_token,
    decode_and_validate_token,
    generate_csrf_token,
    verify_csrf_token,
    validate_password_strength,
    generate_temporary_password,
    JWT_SECRET_KEY,
    JWT_ALGORITHM
)
from ..services.retention_service import purge_expired_document_files
from ..config import RETENTION_MINUTES

logger = logging.getLogger("sentinel.routes_auth")

router = APIRouter(prefix="/api/auth", tags=["Authentication & Session Security"])


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(..., description="Officer Username or Badge ID (e.g., admin or SSB-IND-8841)")
    password: str = Field(..., description="Officer Security Passcode")
    station_id: Optional[str] = Field(None, description="Current checkpoint station")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., description="Current (or temporary) password")
    new_password: str = Field(..., min_length=12, description="New strong password (min 12 characters)")
    username: Optional[str] = Field(None, description="Officer username if not passing Bearer token")


class AdminCreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    role: str = Field("officer", description="officer, supervisor, or admin")
    checkpoint_id: Optional[str] = Field(None, description="Assigned border checkpoint / port")
    station_id: Optional[str] = Field(None, description="Alternative checkpoint identifier")
    officer_name: Optional[str] = Field(None, description="Officer full name")
    badge_id: Optional[str] = Field(None, description="Officer service / badge ID")


class PurgeRequest(BaseModel):
    retention_minutes: int = Field(RETENTION_MINUTES, description="Age threshold in minutes for purging document images")


# ---------------------------------------------------------------------------
# Authentication & RBAC Dependencies
# ---------------------------------------------------------------------------
def get_current_user_payload(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Validates the JWT access token from Authorization: Bearer <token>.
    Raises HTTP 401 if token is absent, expired, revoked, or invalid.
    Raises HTTP 403 if the user account is deactivated.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_and_validate_token(db, token, expected_type="access")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify user exists and is active
    user = get_user_by_username(db, payload.get("sub"))
    if user and not user.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Access revoked."
        )

    return payload


# Alias used by screening and history routers
require_auth = get_current_user_payload


def require_role(allowed_roles: List[str]):
    """
    Role-Based Access Control (RBAC) dependency.
    Verifies that the authenticated duty officer possesses one of the allowed roles.
    """
    def role_dependency(
        user_payload: Dict[str, Any] = Depends(get_current_user_payload),
        db: Session = Depends(get_db)
    ) -> User:
        user = get_user_by_username(db, user_payload.get("sub"))
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated officer record not found."
            )
        if not user.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated. Contact an administrator."
            )
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Required role in {allowed_roles}, but current role is '{user.role}'."
            )
        return user
    return role_dependency


# ---------------------------------------------------------------------------
# Auth Endpoints (/api/auth)
# ---------------------------------------------------------------------------
@router.post("/login", summary="Duty Officer Authentication with 5-Attempt Lockout")
async def login_endpoint(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Authenticates duty officer:
    - Enforces max 5 failed attempts per username within 15 minutes.
    - If 5 failed attempts reached, locks account for 15 minutes.
    - Rejects deactivated accounts.
    - On success:
      * Issues short-lived access token (kept in React memory only).
      * Sets httpOnly, SameSite=Strict cookie for refresh token.
      * Flags must_change_password for newly provisioned or reset accounts.
    """
    username_input = login_data.username.strip()
    password_input = login_data.password

    # 1. Check if account is currently locked out
    is_locked, remaining_seconds = login_tracker.is_locked(username_input)
    if is_locked:
        mins_remaining = max(1, remaining_seconds // 60)
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account temporarily locked due to 5 consecutive failed login attempts. Try again in {mins_remaining} minute(s)."
        )

    # 2. Look up officer by username or badge ID
    user = get_user_by_username(db, username_input) or get_user_by_badge_id(db, username_input)

    # Check deactivated status before credentials verification
    if user and not user.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact an administrator."
        )

    # 3. Verify credentials
    if not user or not verify_password(password_input, user.hashed_password):
        is_now_locked, attempts, lockout_sec = login_tracker.record_failure(username_input)
        if is_now_locked:
            mins = lockout_sec // 60
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Account locked! Maximum 5 failed login attempts reached. Locked for {mins} minutes."
            )
        remaining_attempts = 5 - attempts
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid credentials. {remaining_attempts} attempt(s) remaining before 15-minute account lockout."
        )

    # 4. Successful login -> reset lockout tracker & update last login
    login_tracker.record_success(user.username)
    login_tracker.record_success(user.badge_id)
    record_user_login(db, user.id)

    # 5. Generate tokens
    access_token, access_jti, expires_in = create_access_token(user)
    refresh_token, refresh_jti, refresh_exp = create_refresh_token(user)
    csrf_token = generate_csrf_token()

    # 6. Set httpOnly, SameSite=Strict refresh token cookie
    is_https = request.url.scheme == "https"
    response.set_cookie(
        key="sentinel_refresh_token",
        value=refresh_token,
        httponly=True,
        secure=is_https,
        samesite="strict",
        path="/api/auth",
        max_age=24 * 3600
    )

    response.set_cookie(
        key="sentinel_csrf_token",
        value=csrf_token,
        httponly=False,
        secure=is_https,
        samesite="strict",
        path="/",
        max_age=24 * 3600
    )

    logger.info(f"[Auth] Officer {user.badge_id} ({user.username}) logged in successfully.")

    return {
        "status": "success",
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "csrf_token": csrf_token,
        "must_change_password": bool(user.must_change_password),
        "user": {
            "id": user.id,
            "username": user.username,
            "badge_id": user.badge_id,
            "officer_name": user.officer_name,
            "role": user.role,
            "station_id": user.station_id,
            "must_change_password": bool(user.must_change_password),
            "active": bool(user.active),
            "last_login": user.last_login.isoformat() if user.last_login else None
        }
    }


@router.post("/change-password", summary="Update Password & Clear Temporary Password Requirement")
async def change_password_endpoint(
    change_data: ChangePasswordRequest,
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Changes officer password:
    - Requires current (or temporary) password + new compliant password.
    - Validates 12+ chars, character classes, weak password blocklist.
    - Ensures new password differs from current.
    - Clears must_change_password flag upon success and issues fresh in-memory tokens.
    """
    # 1. Identify user via Bearer token or username
    user = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = decode_and_validate_token(db, token, expected_type="access")
            user = get_user_by_username(db, payload.get("sub"))
        except Exception:
            pass

    if not user and change_data.username:
        user = get_user_by_username(db, change_data.username.strip()) or get_user_by_badge_id(db, change_data.username.strip())

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to update password. Provide Bearer token or valid username."
        )

    if not user.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact an administrator."
        )

    # 2. Verify current password
    if not verify_password(change_data.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password."
        )

    # 3. Disallow reusing same password
    if change_data.current_password == change_data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be identical to current password."
        )

    # 4. Enforce strict password policy
    is_valid, reason = validate_password_strength(change_data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password policy violation: {reason}"
        )

    # 5. Update user password and clear must_change_password
    new_hashed = hash_password(change_data.new_password)
    update_user_password(db, user.id, new_hashed, must_change_password=False)
    db.refresh(user)

    # 6. Issue refreshed access token and cookies
    new_access_token, _, expires_in = create_access_token(user)
    new_refresh_token, _, _ = create_refresh_token(user)
    csrf_token = generate_csrf_token()

    is_https = request.url.scheme == "https"
    response.set_cookie(
        key="sentinel_refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=is_https,
        samesite="strict",
        path="/api/auth",
        max_age=24 * 3600
    )
    response.set_cookie(
        key="sentinel_csrf_token",
        value=csrf_token,
        httponly=False,
        secure=is_https,
        samesite="strict",
        path="/",
        max_age=24 * 3600
    )

    logger.info(f"[Auth] Officer {user.badge_id} successfully updated password. Full terminal access unlocked.")

    return {
        "status": "success",
        "message": "Password updated successfully. Full console access unlocked.",
        "access_token": new_access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "csrf_token": csrf_token,
        "must_change_password": False,
        "user": {
            "id": user.id,
            "username": user.username,
            "badge_id": user.badge_id,
            "officer_name": user.officer_name,
            "role": user.role,
            "station_id": user.station_id,
            "must_change_password": False,
            "active": user.active
        }
    }


@router.post("/refresh", summary="Silent Token Refresh via httpOnly Cookie")
async def refresh_endpoint(
    request: Request,
    response: Response,
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db)
):
    """
    Refreshes access token using httpOnly refresh token cookie:
    - Validates CSRF double-submit protection.
    - Validates refresh token signature, expiry, and revocation status.
    - Issues fresh 15-minute access token.
    """
    csrf_cookie = request.cookies.get("sentinel_csrf_token")
    if csrf_cookie and x_csrf_token and not verify_csrf_token(csrf_cookie, x_csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token validation failed. Possible Cross-Site Request Forgery attempt."
        )

    refresh_token = request.cookies.get("sentinel_refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh session cookie found. Please log in again."
        )

    try:
        payload = decode_and_validate_token(db, refresh_token, expected_type="refresh")
    except ValueError as err:
        response.delete_cookie(key="sentinel_refresh_token", path="/api/auth")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(err))

    user = get_user_by_username(db, payload["sub"])
    if not user or not user.active:
        response.delete_cookie(key="sentinel_refresh_token", path="/api/auth")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account no longer active.")

    access_token, _, expires_in = create_access_token(user)
    new_csrf_token = generate_csrf_token()

    is_https = request.url.scheme == "https"
    response.set_cookie(
        key="sentinel_csrf_token",
        value=new_csrf_token,
        httponly=False,
        secure=is_https,
        samesite="strict",
        path="/",
        max_age=24 * 3600
    )

    return {
        "status": "success",
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "csrf_token": new_csrf_token,
        "must_change_password": bool(user.must_change_password),
        "user": {
            "id": user.id,
            "username": user.username,
            "badge_id": user.badge_id,
            "officer_name": user.officer_name,
            "role": user.role,
            "station_id": user.station_id,
            "must_change_password": bool(user.must_change_password),
            "active": user.active
        }
    }


@router.post("/logout", summary="Invalidate Session & Revoke Tokens Server-Side")
async def logout_endpoint(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Revokes tokens server-side by adding their JTIs to `revoked_tokens` table.
    Clears httpOnly refresh token cookie and CSRF cookie with expired Max-Age.
    """
    revoked_count = 0

    # Revoke access token if present
    if authorization and authorization.startswith("Bearer "):
        access_tok = authorization.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(access_tok, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            jti = payload.get("jti")
            exp_ts = payload.get("exp", int(datetime.utcnow().timestamp()) + 900)
            if jti:
                revoke_token(db, jti, "access", datetime.utcfromtimestamp(exp_ts))
                revoked_count += 1
        except Exception as err:
            logger.warning(f"Failed to revoke access token on logout: {err}")

    # Revoke refresh token if cookie present
    refresh_tok = request.cookies.get("sentinel_refresh_token")
    if refresh_tok:
        try:
            payload_ref = jwt.decode(refresh_tok, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            jti_ref = payload_ref.get("jti")
            exp_ref = payload_ref.get("exp", int(datetime.utcnow().timestamp()) + 86400)
            if jti_ref:
                revoke_token(db, jti_ref, "refresh", datetime.utcfromtimestamp(exp_ref))
                revoked_count += 1
        except Exception as err:
            logger.warning(f"Failed to revoke refresh token on logout: {err}")

    # Clear cookies by setting expired Max-Age
    is_https = request.url.scheme == "https"
    response.set_cookie(
        key="sentinel_refresh_token",
        value="",
        httponly=True,
        secure=is_https,
        samesite="strict",
        path="/api/auth",
        max_age=0,
        expires=0
    )
    response.set_cookie(
        key="sentinel_csrf_token",
        value="",
        httponly=False,
        secure=is_https,
        samesite="strict",
        path="/",
        max_age=0,
        expires=0
    )
    response.delete_cookie(key="sentinel_refresh_token", path="/api/auth")
    response.delete_cookie(key="sentinel_csrf_token", path="/")

    return {
        "status": "success",
        "message": "Logged out successfully. Tokens added to server blocklist.",
        "revoked_tokens": revoked_count
    }


@router.get("/me", summary="Current Authenticated Duty Officer Details")
async def get_me_endpoint(
    user_payload: Dict[str, Any] = Depends(get_current_user_payload),
    db: Session = Depends(get_db)
):
    """Returns details of the currently authenticated officer from in-memory JWT."""
    user = get_user_by_username(db, user_payload["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="Officer record not found.")

    return {
        "id": user.id,
        "username": user.username,
        "badge_id": user.badge_id,
        "officer_name": user.officer_name,
        "role": user.role,
        "station_id": user.station_id,
        "must_change_password": bool(user.must_change_password),
        "active": bool(user.active),
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "created_at": user.created_at.isoformat() if user.created_at else None
    }


# ---------------------------------------------------------------------------
# Admin User Management & Data Retention Router (/api/admin)
# ---------------------------------------------------------------------------
admin_router = APIRouter(prefix="/api/admin", tags=["Security Administration & User Provisioning"])


@admin_router.get("/users", summary="List All Duty Officers & Admins (Admin Only)")
async def admin_list_users_endpoint(
    admin_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db)
):
    """Lists all users (officers, supervisors, admins) with status and last login timestamp."""
    users = list_users(db)
    return [
        {
            "id": u.id,
            "username": u.username,
            "badge_id": u.badge_id,
            "officer_name": u.officer_name,
            "role": u.role,
            "station_id": u.station_id,
            "must_change_password": bool(u.must_change_password),
            "active": bool(u.active),
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "created_at": u.created_at.isoformat() if u.created_at else None
        }
        for u in users
    ]


@admin_router.post("/users", summary="Provision New Duty Officer (Admin Only)")
async def admin_create_user_endpoint(
    req: AdminCreateUserRequest,
    admin_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db)
):
    """
    Admin-provisioned account creation:
    - Generates a random temporary password (never stored in plaintext).
    - Hashes with bcrypt and marks must_change_password = True.
    - Returns temporary password ONCE in API response so admin can relay it.
    """
    clean_username = req.username.strip().lower()
    if get_user_by_username(db, clean_username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{clean_username}' is already in use."
        )

    station = req.station_id or req.checkpoint_id or "hyderabad-rgia"
    badge = req.badge_id or f"SSB-{station[:3].upper()}-{secrets.randbelow(9000)+1000}"
    if get_user_by_badge_id(db, badge):
        badge = f"SSB-{station[:3].upper()}-{secrets.randbelow(9000)+1000}"

    officer_name = req.officer_name or clean_username.replace("_", " ").title()

    # Generate random temporary password
    temp_password = generate_temporary_password(12)

    user = create_user(
        db=db,
        username=clean_username,
        badge_id=badge,
        officer_name=officer_name,
        password=temp_password,
        role=req.role.lower(),
        station_id=station,
        must_change_password=True,
        active=True
    )

    logger.info(f"[Admin] Admin '{admin_user.username}' provisioned officer '{user.username}' ({user.badge_id}).")

    return {
        "status": "success",
        "user": {
            "id": user.id,
            "username": user.username,
            "badge_id": user.badge_id,
            "officer_name": user.officer_name,
            "role": user.role,
            "station_id": user.station_id,
            "must_change_password": True,
            "active": True,
            "created_at": user.created_at.isoformat() if user.created_at else None
        },
        "temporary_password": temp_password,
        "message": "User provisioned successfully. Relay this temporary password to the officer securely. It will not be shown again."
    }


@admin_router.post("/users/{user_id}/reset-password", summary="Reset Officer Password to New Temp Password (Admin Only)")
async def admin_reset_password_endpoint(
    user_id: int,
    admin_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db)
):
    """
    Resets an officer's password to a fresh temporary password:
    - Generates new random temporary password.
    - Sets must_change_password = True.
    - Returns temporary password ONCE.
    """
    target_user = get_user_by_id(db, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    temp_password = generate_temporary_password(12)
    new_hashed = hash_password(temp_password)
    update_user_password(db, target_user.id, new_hashed, must_change_password=True)

    # Clear any active lockout so the officer can log in with the new temp password immediately
    login_tracker.record_success(target_user.username)
    login_tracker.record_success(target_user.badge_id)

    logger.info(f"[Admin] Admin '{admin_user.username}' reset password for '{target_user.username}'.")

    return {
        "status": "success",
        "user_id": target_user.id,
        "username": target_user.username,
        "temporary_password": temp_password,
        "must_change_password": True,
        "message": "Password reset successfully. Relay this temporary password to the officer. It will not be shown again."
    }


@admin_router.post("/users/{user_id}/toggle-active", summary="Toggle User Active Status (Admin Only)")
async def admin_toggle_active_endpoint(
    user_id: int,
    admin_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db)
):
    """Soft deactivates or reactivates an officer account (preserves audit records)."""
    target_user = get_user_by_id(db, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    if target_user.id == admin_user.id and target_user.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrators cannot deactivate their own active account."
        )

    new_active = not target_user.active
    set_user_active(db, target_user.id, new_active)

    if new_active:
        login_tracker.record_success(target_user.username)
        login_tracker.record_success(target_user.badge_id)

    logger.info(f"[Admin] Admin '{admin_user.username}' changed active status of '{target_user.username}' to {new_active}.")

    return {
        "status": "success",
        "user_id": target_user.id,
        "username": target_user.username,
        "active": new_active,
        "message": f"User '{target_user.username}' has been {'reactivated' if new_active else 'deactivated'}."
    }


@admin_router.post("/purge-expired", summary="Manual Trigger for Document Image Purge")
async def manual_purge_endpoint(
    purge_req: Optional[PurgeRequest] = None,
    db: Session = Depends(get_db)
):
    """
    Manual on-demand purge endpoint for testing and compliance audits.
    Securely deletes document image files on disk older than retention_minutes (default configured window).
    NOTE: scan_records investigative audit data is strictly preserved.
    """
    retention_mins = purge_req.retention_minutes if purge_req else RETENTION_MINUTES
    result = purge_expired_document_files(db, retention_minutes=retention_mins)
    return result
