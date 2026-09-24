"""
test_reset_admin_script.py
Automated tests for the emergency reset_admin CLI script:
1. Resets existing admin password in the DB and sets must_change_password to True.
2. The newly generated temporary password allows login via /api/auth/login.
3. Automatically creates an admin account if missing from the DB.
4. Verifies no HTTP route exists for admin password reset (strictly local CLI).
"""
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.db.models import User
from backend.db.crud import get_user_by_username, seed_sample_data_if_empty
from backend.scripts.reset_admin import reset_admin_password

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_db()
    db = SessionLocal()
    seed_sample_data_if_empty(db)
    db.close()


def test_reset_admin_password_existing_user():
    """
    Verifies that calling reset_admin_password on an existing admin
    generates a new password, hashes it, and resets must_change_password to True.
    """
    db = SessionLocal()
    test_uname = "test_admin_reset_account"
    admin = get_user_by_username(db, test_uname)
    if not admin:
        from backend.db.crud import create_user
        admin = create_user(
            db=db,
            username=test_uname,
            badge_id="ADM-TEST-ISOLATED",
            officer_name="Isolated Test Admin",
            password="InitialPass#2026!",
            role="admin",
            active=True
        )
    initial_hash = admin.hashed_password

    # Execute reset
    updated_admin, new_plaintext_pw, is_new = reset_admin_password(db, target_username=test_uname)
    assert is_new is False
    assert updated_admin.username == test_uname
    assert updated_admin.must_change_password is True
    assert updated_admin.active is True
    assert updated_admin.hashed_password != initial_hash
    assert len(new_plaintext_pw) >= 12
    db.close()

    # Verify login with the new temporary password
    login_resp = client.post("/api/auth/login", json={
        "username": test_uname,
        "password": new_plaintext_pw
    })
    assert login_resp.status_code == 200, "Must be able to authenticate with new temporary password"
    data = login_resp.json()
    assert data["must_change_password"] is True
    assert data["user"]["username"] == test_uname


def test_reset_admin_creates_when_missing():
    """
    Verifies that if target admin account is missing, it is created.
    """
    db = SessionLocal()
    test_missing_uname = "admin_missing_emergency"
    # Ensure not present
    existing = get_user_by_username(db, test_missing_uname)
    if existing:
        db.delete(existing)
        db.commit()

    created_admin, new_pw, is_new = reset_admin_password(db, target_username=test_missing_uname)
    assert is_new is True
    assert created_admin.username == test_missing_uname
    assert created_admin.role == "admin"
    assert created_admin.must_change_password is True
    assert created_admin.active is True
    db.close()

    # Clean up
    db = SessionLocal()
    to_delete = get_user_by_username(db, test_missing_uname)
    if to_delete:
        db.delete(to_delete)
        db.commit()
    db.close()


def test_no_http_route_for_reset_admin():
    """
    CRITICAL SECURITY CHECK:
    Verifies that there is NO HTTP endpoint exposed for reset-admin.
    Attempts to GET, POST, PUT to /api/auth/reset-admin or /api/admin/reset-admin must return 404/405.
    """
    routes_to_probe = [
        ("POST", "/api/auth/reset-admin"),
        ("GET", "/api/auth/reset-admin"),
        ("POST", "/api/admin/reset-admin"),
        ("GET", "/api/admin/reset-admin"),
        ("POST", "/api/admin/reset"),
        ("POST", "/reset-admin"),
    ]

    for method, path in routes_to_probe:
        if method == "POST":
            resp = client.post(path)
        else:
            resp = client.get(path)
        assert resp.status_code in (404, 405), f"Endpoint {path} must NOT exist on HTTP API (status: {resp.status_code})"
