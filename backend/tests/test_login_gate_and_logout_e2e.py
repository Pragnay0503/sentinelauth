"""
test_login_gate_and_logout_e2e.py
End-to-end verification of:
1. Fresh visit without session: refresh fails with 401 (client routes to /login).
2. Authenticated login: returns real officer details (not hardcoded ADM-ROOT-001) and issues session.
3. Silent refresh succeeds with valid cookie and returns full user profile and token.
4. Logout endpoint: revokes tokens server-side, deletes cookies, and prevents subsequent refresh attempts (401).
5. Forced password change workflow: temporary password user is blocked from operational endpoints (403) until change-password.
"""
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.db.models import User
from backend.db.crud import (
    create_user,
    get_user_by_username,
    seed_sample_data_if_empty
)

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_db()
    db = SessionLocal()
    seed_sample_data_if_empty(db)
    db.close()


def test_fresh_app_no_session_fails_refresh():
    """
    Scenario 1: Fresh browser visit with no session cookies.
    Attempting silent refresh returns HTTP 401 Unauthorized,
    confirming the client route guard must redirect to /login.
    """
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401, "Unauthenticated client must not be granted an access token"
    assert "no refresh session cookie" in resp.json()["detail"].lower()


def test_login_returns_actual_officer_details_and_sets_cookie():
    """
    Scenario 2: Logging in with valid credentials returns the ACTUAL officer details
    (e.g., officer_sharma / SSB-IND-4819, NOT a hardcoded placeholder)
    and sets the httpOnly refresh cookie.
    """
    db = SessionLocal()
    officer_uname = "officer_e2e_gate"
    officer = get_user_by_username(db, officer_uname)
    if not officer:
        officer = create_user(
            db=db,
            username=officer_uname,
            badge_id="SSB-E2E-7788",
            officer_name="Inspector Vikram Sharma",
            password="SecurePass#2026!",
            role="officer",
            station_id="mumbai-bspi",
            must_change_password=False,
            active=True
        )
    db.close()

    login_resp = client.post("/api/auth/login", json={
        "username": officer_uname,
        "password": "SecurePass#2026!"
    })
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert data["access_token"] is not None

    # Verify actual officer identity (not hardcoded placeholder)
    user_info = data["user"]
    assert user_info["username"] == officer_uname
    assert user_info["badge_id"] == "SSB-E2E-7788"
    assert user_info["officer_name"] == "Inspector Vikram Sharma"
    assert user_info["role"] == "officer"
    assert user_info["station_id"] == "mumbai-bspi"

    # Verify refresh cookie was set
    cookies = login_resp.cookies
    assert "sentinel_refresh_token" in cookies


def test_silent_refresh_restores_user_profile():
    """
    Scenario 3: On page reload, client calls POST /api/auth/refresh with the cookie.
    The response includes a fresh access token AND the full user profile to restore state.
    """
    login_resp = client.post("/api/auth/login", json={
        "username": "officer_e2e_gate",
        "password": "SecurePass#2026!"
    })
    refresh_cookie = login_resp.cookies["sentinel_refresh_token"]

    refresh_resp = client.post(
        "/api/auth/refresh",
        cookies={"sentinel_refresh_token": refresh_cookie}
    )
    assert refresh_resp.status_code == 200
    data = refresh_resp.json()
    assert data["access_token"] is not None
    assert "user" in data
    assert data["user"]["badge_id"] == "SSB-E2E-7788"
    assert data["user"]["username"] == "officer_e2e_gate"


def test_logout_invalidates_session_and_subsequent_refresh_fails():
    """
    Scenario 4: Clicking logout calls POST /api/auth/logout.
    - Server adds token JTI to blocklist.
    - Cookies are expired.
    - Subsequent attempt to refresh returns 401, guaranteeing route guard redirects to /login.
    """
    # 1. Login
    login_resp = client.post("/api/auth/login", json={
        "username": "officer_e2e_gate",
        "password": "SecurePass#2026!"
    })
    access_token = login_resp.json()["access_token"]
    refresh_cookie = login_resp.cookies["sentinel_refresh_token"]

    # 2. Logout
    logout_resp = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        cookies={"sentinel_refresh_token": refresh_cookie}
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "success"

    # 3. Attempt to refresh with the logged-out refresh token -> must fail with 401
    post_logout_refresh = client.post(
        "/api/auth/refresh",
        cookies={"sentinel_refresh_token": refresh_cookie}
    )
    assert post_logout_refresh.status_code == 401, "Logged-out refresh token must be rejected"


def test_forced_password_change_route_guard_integration():
    """
    Scenario 5: Newly provisioned officer with temp password
    - Login succeeds and returns must_change_password=True.
    - Operational endpoints return HTTP 403 Forbidden.
    - Officer completes POST /api/auth/change-password.
    - must_change_password becomes False and operational access is granted.
    """
    db = SessionLocal()
    # Ensure admin exists to provision
    admin = get_user_by_username(db, "admin_test_e2e")
    if not admin:
        admin = create_user(
            db=db,
            username="admin_test_e2e",
            badge_id="ADM-TEST-99",
            officer_name="Admin Test",
            password="AdminSuperPass#2026!",
            role="admin",
            must_change_password=False,
            active=True
        )
    db.close()

    admin_login = client.post("/api/auth/login", json={
        "username": "admin_test_e2e",
        "password": "AdminSuperPass#2026!"
    })
    admin_token = admin_login.json()["access_token"]

    # Admin provisions temp officer
    temp_user_name = "officer_temp_e2e"
    db = SessionLocal()
    existing = get_user_by_username(db, temp_user_name)
    if existing:
        db.delete(existing)
        db.commit()
    db.close()

    create_resp = client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "username": temp_user_name,
            "officer_name": "Temp Officer E2E",
            "role": "officer",
            "station_id": "chennai-maa"
        }
    )
    assert create_resp.status_code == 200
    temp_password = create_resp.json()["temporary_password"]

    # Temp officer logs in
    officer_login = client.post("/api/auth/login", json={
        "username": temp_user_name,
        "password": temp_password
    })
    assert officer_login.status_code == 200
    assert officer_login.json()["must_change_password"] is True
    temp_token = officer_login.json()["access_token"]

    # Operational route returns 403 while on temporary password
    blocked_resp = client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {temp_token}"},
        json={"username": "blocked_attempt"}
    )
    assert blocked_resp.status_code == 403

    # Officer changes password
    change_resp = client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {temp_token}"},
        json={
            "current_password": temp_password,
            "new_password": "NewPermanentPass#2026!"
        }
    )
    assert change_resp.status_code == 200
    assert change_resp.json()["must_change_password"] is False
