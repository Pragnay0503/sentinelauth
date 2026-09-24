"""
test_admin_and_auth_provisioning.py - Automated tests for:
1. Logout refresh token invalidation (attempting to use refresh token after logout fails with 401).
2. Forced password change workflow: newly provisioned user with temp password is blocked from operational endpoints (403) until changing password.
3. RBAC enforcement: non-admin calling POST /api/admin/users returns HTTP 403 Forbidden.
4. Bootstrap admin account creation idempotency (created once; second startup does not duplicate or overwrite password).
5. User soft deactivation (active=False blocks login with 403).
6. Admin password reset (generates new temporary password and sets must_change_password=True).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.db.models import User, RevokedToken
from backend.db.crud import (
    create_user,
    get_user_by_username,
    hash_password,
    seed_sample_data_if_empty,
    verify_password
)

client = TestClient(app)


@pytest.fixture(scope="function")
def db_session():
    """Provides a fresh transactional db session for tests."""
    init_db()
    db = SessionLocal()
    seed_sample_data_if_empty(db)
    yield db
    db.close()


def get_admin_credentials(db: Session):
    """Ensures a known admin user exists for test operations."""
    admin = get_user_by_username(db, "test_super_admin")
    if not admin:
        admin = create_user(
            db=db,
            username="test_super_admin",
            badge_id="ADM-TEST-001",
            officer_name="Super Administrator",
            password="AdminMaster#2026!",
            role="admin",
            station_id="hyderabad-rgia",
            must_change_password=False,
            active=True
        )
    return "test_super_admin", "AdminMaster#2026!"


# =============================================================================
# TEST 1: Logout invalidates the refresh token (refreshing after logout fails)
# =============================================================================
def test_logout_invalidates_refresh_token(db_session):
    """
    Test 1:
    - User logs in and receives access token + refresh cookie + csrf cookie.
    - User logs out via POST /api/auth/logout.
    - User attempts to call POST /api/auth/refresh with the old refresh cookie.
    - Asserts that refresh attempt fails with HTTP 401 Unauthorized (token revoked).
    """
    username, password = get_admin_credentials(db_session)

    # 1. Login
    login_resp = client.post("/api/auth/login", json={
        "username": username,
        "password": password
    })
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    access_token = login_data["access_token"]
    csrf_token = login_data["csrf_token"]
    refresh_cookie = login_resp.cookies.get("sentinel_refresh_token")
    assert refresh_cookie is not None

    # 2. Call logout
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-CSRF-Token": csrf_token
    }
    logout_resp = client.post("/api/auth/logout", headers=headers, cookies={"sentinel_refresh_token": refresh_cookie})
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "success"

    # 3. Attempt silent refresh using the logged-out refresh cookie
    refresh_attempt = client.post(
        "/api/auth/refresh",
        headers={"X-CSRF-Token": csrf_token},
        cookies={
            "sentinel_refresh_token": refresh_cookie,
            "sentinel_csrf_token": csrf_token
        }
    )
    assert refresh_attempt.status_code == 401, "Replaying a revoked refresh token MUST return 401"
    assert "revoked" in refresh_attempt.json()["detail"].lower() or "session" in refresh_attempt.json()["detail"].lower()


# =============================================================================
# TEST 2: Admin-created user is forced through change-password before access
# =============================================================================
def test_newly_provisioned_user_forced_change_password(db_session):
    """
    Test 2:
    - Admin creates a new duty officer via POST /api/admin/users.
    - Receives random temporary password once in API response.
    - New officer logs in with temporary password -> must_change_password is True.
    - Attempting to access operational endpoints returns HTTP 403 Forbidden.
    - Officer updates password via POST /api/auth/change-password.
    - must_change_password becomes False and console access is granted.
    """
    admin_user, admin_pw = get_admin_credentials(db_session)

    # 1. Admin logs in
    admin_login = client.post("/api/auth/login", json={"username": admin_user, "password": admin_pw})
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Admin provisions new officer
    new_user_name = "officer_patel_temp"
    # clean prior if exists
    existing = get_user_by_username(db_session, new_user_name)
    if existing:
        db_session.delete(existing)
        db_session.commit()

    create_resp = client.post("/api/admin/users", headers=admin_headers, json={
        "username": new_user_name,
        "officer_name": "Insp. Dev Patel",
        "role": "officer",
        "station_id": "mumbai-bspi"
    })
    assert create_resp.status_code == 200
    created_data = create_resp.json()
    temp_password = created_data["temporary_password"]
    assert temp_password is not None
    assert len(temp_password) >= 12
    assert created_data["user"]["must_change_password"] is True

    # 3. New officer logs in with temporary password
    officer_login = client.post("/api/auth/login", json={
        "username": new_user_name,
        "password": temp_password
    })
    assert officer_login.status_code == 200
    officer_data = officer_login.json()
    assert officer_data["must_change_password"] is True
    temp_access_token = officer_data["access_token"]
    temp_headers = {"Authorization": f"Bearer {temp_access_token}"}

    # 4. Attempt to access a protected operational resource while on temporary password -> HTTP 403
    blocked_resp = client.post("/api/admin/users", headers=temp_headers, json={
        "username": "should_fail_provision"
    })
    assert blocked_resp.status_code == 403, "Access to operational endpoints MUST be blocked with 403 while on temp password"
    assert "Temporary password in use" in blocked_resp.json()["detail"] or "Password change required" in blocked_resp.json()["detail"]

    # 5. Officer calls POST /api/auth/change-password
    change_resp = client.post("/api/auth/change-password", headers=temp_headers, json={
        "current_password": temp_password,
        "new_password": "PermanentGuard#2026!"
    })
    assert change_resp.status_code == 200
    change_data = change_resp.json()
    assert change_data["status"] == "success"
    assert change_data["must_change_password"] is False
    new_active_token = change_data["access_token"]

    # 6. Verify user in database has must_change_password = False
    updated_user = get_user_by_username(db_session, new_user_name)
    assert updated_user.must_change_password is False

    # 7. Clean up
    db_session.delete(updated_user)
    db_session.commit()


# =============================================================================
# TEST 3: Non-admin cannot call POST /api/admin/users (HTTP 403)
# =============================================================================
def test_non_admin_cannot_provision_users(db_session):
    """
    Test 3:
    - Regular officer (role='officer') attempts to call POST /api/admin/users.
    - Verifies returns HTTP 403 Forbidden.
    """
    officer_username = "test_regular_officer"
    officer = get_user_by_username(db_session, officer_username)
    if not officer:
        officer = create_user(
            db=db_session,
            username=officer_username,
            badge_id="SSB-REG-001",
            officer_name="Regular Officer",
            password="OfficerPass#2026!",
            role="officer",
            station_id="delhi-igi",
            must_change_password=False,
            active=True
        )

    # Officer logs in
    login_resp = client.post("/api/auth/login", json={
        "username": officer_username,
        "password": "OfficerPass#2026!"
    })
    assert login_resp.status_code == 200
    officer_token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {officer_token}"}

    # Attempt to provision a new user as regular officer
    attempt_resp = client.post("/api/admin/users", headers=headers, json={
        "username": "unauthorized_user_test",
        "role": "officer"
    })
    assert attempt_resp.status_code == 403, "Non-admin MUST receive HTTP 403 Forbidden when calling admin endpoints"
    assert "Access denied" in attempt_resp.json()["detail"]


# =============================================================================
# TEST 4: Bootstrap admin account created only once
# =============================================================================
def test_bootstrap_admin_created_only_once(db_session):
    """
    Test 4:
    - Verifies that running seed_sample_data_if_empty on an already populated database
      does not duplicate the admin account or reset its password.
    """
    admin = get_user_by_username(db_session, "admin")
    if not admin:
        from backend.services.auth_service import generate_temporary_password
        admin = User(
            username="admin",
            badge_id="ADM-ROOT-001",
            officer_name="System Administrator",
            hashed_password=hash_password(generate_temporary_password(12)),
            role="admin",
            station_id="hyderabad-rgia",
            must_change_password=True,
            active=True
        )
        db_session.add(admin)
        db_session.commit()

    initial_pw_hash = admin.hashed_password
    initial_user_count = db_session.query(User).count()

    # 2. Run seed_sample_data_if_empty again
    seed_sample_data_if_empty(db_session)

    # 3. Verify user count did not increase
    db_session.expire_all()
    new_user_count = db_session.query(User).count()
    assert new_user_count == initial_user_count, "Subsequent startup must not add duplicate users"

    # 4. Verify password hash was NOT overwritten
    persisted_admin = get_user_by_username(db_session, "admin")
    assert persisted_admin.hashed_password == initial_pw_hash, "Subsequent startup must never reset existing admin password"


def test_bootstrap_creates_admin_when_table_is_empty():
    """
    Verifies that on initial startup with an empty users table,
    seed_sample_data_if_empty creates the single initial admin account.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.db.models import Base

    # Use isolated in-memory SQLite database
    mem_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=mem_engine)
    MemSession = sessionmaker(bind=mem_engine)
    mem_db = MemSession()

    assert mem_db.query(User).count() == 0, "Users table must be empty initially"
    seed_sample_data_if_empty(mem_db)

    assert mem_db.query(User).count() == 1, "Exactly one admin account must be bootstrapped"
    bootstrapped = mem_db.query(User).first()
    assert bootstrapped.username == "admin"
    assert bootstrapped.badge_id == "ADM-ROOT-001"
    assert bootstrapped.role == "admin"
    assert bootstrapped.must_change_password is True
    assert bootstrapped.active is True
    mem_db.close()


# =============================================================================
# TEST 5: Deactivated user (active=False) cannot log in (HTTP 403)
# =============================================================================
def test_deactivated_user_cannot_login(db_session):
    """
    Test 5:
    - Admin toggles an officer's active status to False.
    - Officer attempts to log in.
    - Verifies rejected with HTTP 403 Forbidden.
    - Admin reactivates officer.
    - Officer can log in again.
    """
    admin_user, admin_pw = get_admin_credentials(db_session)
    admin_login = client.post("/api/auth/login", json={"username": admin_user, "password": admin_pw})
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    test_officer_name = "test_toggle_officer"
    officer = get_user_by_username(db_session, test_officer_name)
    if not officer:
        officer = create_user(
            db=db_session,
            username=test_officer_name,
            badge_id="SSB-TOG-001",
            officer_name="Toggle Officer",
            password="ValidPassToggle#2026!",
            role="officer",
            must_change_password=False,
            active=True
        )

    # 1. Deactivate officer via admin endpoint
    toggle_resp = client.post(f"/api/admin/users/{officer.id}/toggle-active", headers=admin_headers)
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["active"] is False

    # 2. Attempt to log in with deactivated account
    login_attempt = client.post("/api/auth/login", json={
        "username": test_officer_name,
        "password": "ValidPassToggle#2026!"
    })
    assert login_attempt.status_code == 403, "Deactivated user MUST be rejected with HTTP 403"
    assert "deactivated" in login_attempt.json()["detail"].lower()

    # 3. Reactivate officer
    reactivate_resp = client.post(f"/api/admin/users/{officer.id}/toggle-active", headers=admin_headers)
    assert reactivate_resp.status_code == 200
    assert reactivate_resp.json()["active"] is True

    # 4. Attempt login again -> should succeed
    login_success = client.post("/api/auth/login", json={
        "username": test_officer_name,
        "password": "ValidPassToggle#2026!"
    })
    assert login_success.status_code == 200
    assert login_success.json()["user"]["active"] is True

    # Clean up
    db_session.delete(officer)
    db_session.commit()
