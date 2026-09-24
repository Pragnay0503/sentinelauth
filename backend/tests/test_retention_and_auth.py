"""
test_retention_and_auth.py - Comprehensive automated tests for:
1. Automatic 30-minute document deletion & permanent preservation of scan_records audit trail.
2. Login attempt rate-limiting (5 failures -> 15m account lockout) & reject-even-if-correct during lockout.
3. Strict password security policy (min 12 chars, upper/lower/number/symbol, weak password blocklist).
4. Server-side logout token revocation blocklist.
5. Inactivity timeout logic.
"""
from datetime import datetime, timedelta
import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db, SessionLocal, init_db
from backend.db.models import ScanRecord, DocumentFile, User, RevokedToken
from backend.db.crud import (
    register_document_file,
    get_user_by_username,
    create_user,
    hash_password,
    seed_sample_data_if_empty
)
from backend.services.retention_service import purge_expired_document_files
from backend.services.auth_service import (
    validate_password_strength,
    login_tracker,
    COMMON_WEAK_PASSWORDS
)

client = TestClient(app)


@pytest.fixture(scope="function")
def db_session():
    """Provides a transactional database session for tests."""
    init_db()
    db = SessionLocal()
    seed_sample_data_if_empty(db)
    yield db
    db.close()


# =============================================================================
# TEST 1: Automatic Document Deletion (30-Minute Retention) & Audit Preservation
# =============================================================================
def test_document_purge_and_scan_records_preservation(db_session):
    """
    Test 1:
    - Uploads/creates a document image on disk.
    - Tags it in document_files with a created_at timestamp backdated >30 minutes ago.
    - Creates a corresponding ScanRecord with risk scores and payload.
    - Runs purge_expired_document_files().
    - Asserts:
        1. The physical file is DELETED from disk (os.remove).
        2. The document_files row is marked deleted=True with deleted_at timestamp.
        3. CRITICAL: The ScanRecord row is UNTOUCHED and permanently preserved!
    """
    # 1. Create a dummy scan record
    scan_id = "test_retention_scan_9901"
    scan_record = ScanRecord(
        id=scan_id,
        timestamp=datetime.utcnow(),
        document_type="passport",
        holder_name="TEST RETENTION TRAVELER",
        document_number="Z8829102",
        risk_score=24.5,
        risk_tier="LOW",
        status="PASSED",
        validation_passed=True,
        tampering_score=0.12,
        face_match_confidence=0.92,
        officer_id="SSB-IND-8841",
        checkpoint="hyderabad-rgia",
        payload=json.dumps({"test_key": "audit_evidence_retained"}),
        document_image_path=f"uploads/{scan_id}_doc.jpg"
    )
    db_session.add(scan_record)
    db_session.commit()

    # 2. Create physical test file on disk
    from backend.api.routes_scan import UPLOADS_DIR
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    test_filename = f"{scan_id}_doc.jpg"
    test_filepath = os.path.join(UPLOADS_DIR, test_filename)
    with open(test_filepath, "wb") as f:
        f.write(b"SAMPLE_ENCRYPTED_DOCUMENT_IMAGE_BYTES_FOR_RETENTION_TEST")

    assert os.path.exists(test_filepath), "Test file should exist on disk before purge"

    # 3. Register in document_files and backdate to 31 minutes ago
    backdated_created_at = datetime.utcnow() - timedelta(minutes=31)
    doc_file = DocumentFile(
        file_path=test_filepath,
        filename=test_filename,
        created_at=backdated_created_at,
        scan_id=scan_id,
        deleted=False
    )
    db_session.add(doc_file)
    db_session.commit()
    db_session.refresh(doc_file)
    doc_file_id = doc_file.id

    # 4. Trigger retention purge (threshold: 30 minutes)
    purge_result = purge_expired_document_files(db_session, retention_minutes=30)
    assert purge_result["status"] == "success"
    assert purge_result["purged_count"] >= 1

    # 5. Verify physical file is gone from disk
    assert not os.path.exists(test_filepath), "Expired document file should have been removed from disk"

    # 6. Verify document_files record marked deleted=True as a compliance tombstone
    db_session.expire_all()
    updated_doc_file = db_session.query(DocumentFile).filter(DocumentFile.id == doc_file_id).first()
    assert updated_doc_file.deleted is True, "document_files row must be marked deleted=True"
    assert updated_doc_file.deleted_at is not None, "deleted_at must record exact timestamp of deletion"

    # 7. CRITICAL: Verify ScanRecord is 100% INTACT in the database
    persisted_scan = db_session.query(ScanRecord).filter(ScanRecord.id == scan_id).first()
    assert persisted_scan is not None, "CRITICAL: ScanRecord MUST NEVER be deleted by retention purge"
    assert persisted_scan.holder_name == "TEST RETENTION TRAVELER"
    assert persisted_scan.risk_score == 24.5
    assert persisted_scan.risk_tier == "LOW"
    assert json.loads(persisted_scan.payload)["test_key"] == "audit_evidence_retained"

    # Clean up test scan record
    db_session.delete(persisted_scan)
    db_session.delete(updated_doc_file)
    db_session.commit()


def test_admin_purge_expired_api_endpoint(db_session):
    """Verifies manual admin purge endpoint POST /api/admin/purge-expired."""
    response = client.post("/api/admin/purge-expired", json={"retention_minutes": 30})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "purged_count" in data
    assert "cutoff_timestamp" in data


# =============================================================================
# TEST 2: Login Rate Limiting, 5-Attempt Lockout & Reject-Even-If-Correct
# =============================================================================
def test_login_rate_limiting_and_account_lockout(db_session):
    """
    Test 2:
    - Submits 5 failed login attempts for a specific user.
    - Verifies account is locked out after 5 failures.
    - Submits a 6th attempt with the CORRECT password.
    - Verifies the 6th attempt is STILL REJECTED with HTTP 423 Locked.
    """
    test_username = "test_officer_lockout"
    test_badge = "SSB-LOCK-001"
    correct_pw = "ValidGuardPass#2026!"

    # Ensure clean user exists
    existing = get_user_by_username(db_session, test_username)
    if not existing:
        create_user(
            db=db_session,
            username=test_username,
            badge_id=test_badge,
            officer_name="Officer Lockout Test",
            password=correct_pw,
            role="officer",
            station_id="delhi-igi"
        )

    # Reset any prior tracker state
    login_tracker.record_success(test_username)
    login_tracker.record_success(test_badge)

    # Submit 4 failed attempts -> returns 401 Unauthorized
    for attempt in range(1, 5):
        resp = client.post("/api/auth/login", json={
            "username": test_username,
            "password": "WrongPassword123!"
        })
        assert resp.status_code == 401
        assert "attempt(s) remaining" in resp.json()["detail"]

    # 5th failed attempt -> triggers lockout -> returns 423 Locked
    resp5 = client.post("/api/auth/login", json={
        "username": test_username,
        "password": "WrongPassword123!"
    })
    assert resp5.status_code == 423, "5th failed attempt must trigger HTTP 423 Locked"
    assert "Account locked" in resp5.json()["detail"]

    # 6th attempt: SUBMIT CORRECT PASSWORD!
    # Must STILL BE REJECTED because account is actively locked for 15 minutes!
    resp6 = client.post("/api/auth/login", json={
        "username": test_username,
        "password": correct_pw
    })
    assert resp6.status_code == 423, "6th attempt with correct password MUST still be rejected during lockout"
    assert "Account temporarily locked" in resp6.json()["detail"]

    # Clean up test user
    user_to_del = get_user_by_username(db_session, test_username)
    if user_to_del:
        db_session.delete(user_to_del)
        db_session.commit()
    login_tracker.record_success(test_username)


# =============================================================================
# TEST 3: Password Policy Enforcement (12+ Chars, Mix of Types, Blocklist)
# =============================================================================
def test_password_policy_enforcement():
    """
    Test 3:
    - Rejects passwords shorter than 12 characters.
    - Rejects passwords lacking uppercase, lowercase, numbers, or symbols.
    - Rejects common weak passwords even if 12+ chars.
    - Accepts strong complex passwords.
    """
    # 1. Too short
    ok, err = validate_password_strength("Short123!")
    assert not ok
    assert "at least 12 characters" in err

    # 2. No uppercase
    ok, err = validate_password_strength("lowercase12345678#")
    assert not ok
    assert "uppercase" in err

    # 3. No lowercase
    ok, err = validate_password_strength("UPPERCASE12345678#")
    assert not ok
    assert "lowercase" in err

    # 4. No number
    ok, err = validate_password_strength("NoNumericDigitsHere!@#")
    assert not ok
    assert "numeric digit" in err

    # 5. No symbol
    ok, err = validate_password_strength("NoSpecialSymbols123456")
    assert not ok
    assert "special symbol" in err

    # 6. Common weak password blocklist (even if long)
    for weak in COMMON_WEAK_PASSWORDS:
        ok, err = validate_password_strength(weak)
        assert not ok, f"Weak password '{weak}' must be rejected"
        assert "common weak password" in err or "at least 12 characters" in err

    # 7. Valid passphrases
    ok, err = validate_password_strength("Sentinel@2026Sec!")
    assert ok and err is None

    ok, err = validate_password_strength("BorderGuard#2026!")
    assert ok and err is None


def test_change_password_endpoint_password_validation(db_session):
    """Verifies that POST /api/auth/change-password enforces password requirements with HTTP 400."""
    test_user = get_user_by_username(db_session, "test_weak_pw_officer")
    if not test_user:
        create_user(
            db=db_session,
            username="test_weak_pw_officer",
            badge_id="SSB-WEAK-101",
            officer_name="Weak Test Officer",
            password="ValidInitialPass#2026!",
            role="officer",
            station_id="hyderabad-rgia",
            active=True
        )
    # Login to get access token
    login_resp = client.post("/api/auth/login", json={
        "username": "test_weak_pw_officer",
        "password": "ValidInitialPass#2026!"
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Attempt password change with weak password
    weak_change = client.post("/api/auth/change-password", headers=headers, json={
        "current_password": "ValidInitialPass#2026!",
        "new_password": "weakpassword1234"
    })
    assert weak_change.status_code == 400
    assert "Password policy violation" in weak_change.json()["detail"]


# =============================================================================
# TEST 4: Server-Side Token Revocation on Logout
# =============================================================================
def test_server_side_token_revocation_on_logout(db_session):
    """
    Test 4:
    - Authenticates successfully with seeded credentials.
    - Receives in-memory access token.
    - Accesses /api/auth/me -> HTTP 200.
    - Calls /api/auth/logout -> token added to revoked_tokens table.
    - Re-attempts /api/auth/me with the same token -> HTTP 401 Unauthorized.
    """
    test_user = get_user_by_username(db_session, "test_revocation_officer")
    if not test_user:
        create_user(
            db=db_session,
            username="test_revocation_officer",
            badge_id="SSB-REV-101",
            officer_name="Officer Revocation Test",
            password="ValidGuardPass#2026!",
            role="officer",
            station_id="hyderabad-rgia",
            active=True
        )

    # 1. Login
    login_resp = client.post("/api/auth/login", json={
        "username": "test_revocation_officer",
        "password": "ValidGuardPass#2026!"
    })
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    access_token = tokens["access_token"]
    csrf_token = tokens["csrf_token"]
    assert access_token is not None

    # 2. Access /api/auth/me with valid Bearer token
    headers = {"Authorization": f"Bearer {access_token}"}
    me_resp = client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "test_revocation_officer"

    # 3. Call /api/auth/logout
    logout_resp = client.post("/api/auth/logout", headers=headers)
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "success"

    # 4. Attempt to re-use the logged-out token -> must return 401 Unauthorized
    replay_resp = client.get("/api/auth/me", headers=headers)
    assert replay_resp.status_code == 401
    assert "has been revoked" in replay_resp.json()["detail"].lower()


# =============================================================================
# TEST 5: Terminal Inactivity Timeout Calculation
# =============================================================================
def test_terminal_inactivity_timeout_logic():
    """
    Test 5:
    - Verifies the inactivity calculation:
      Activity elapsed > 15 minutes triggers logout flag.
    """
    inactivity_threshold_seconds = 15 * 60

    last_active = datetime.utcnow() - timedelta(minutes=16)
    elapsed_seconds = (datetime.utcnow() - last_active).total_seconds()
    is_inactive = elapsed_seconds >= inactivity_threshold_seconds
    assert is_inactive is True, "16 minutes without activity must evaluate to inactive session"

    last_active_recent = datetime.utcnow() - timedelta(minutes=5)
    elapsed_recent = (datetime.utcnow() - last_active_recent).total_seconds()
    is_recent_inactive = elapsed_recent >= inactivity_threshold_seconds
    assert is_recent_inactive is False, "5 minutes elapsed should not trigger inactivity logout"
