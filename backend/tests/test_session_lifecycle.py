"""
test_session_lifecycle.py - Automated tests for SentinelAuth Session Lifecycle Management.

Verifies:
1. Session boundaries: unique session IDs for each traveller check-in.
2. Isolation & Report scoping: generated reports only ever include documents belonging to the active session ID.
3. Finalization & Audit logging: completed sessions persist decision, risk score, risk tier, timestamp, and metadata.
4. Discard handling: unsaved sessions can be closed as DISCARDED with audit tracking.
5. Archived report retrieval: read-only archived reports can be retrieved by session ID.
6. Session listing API: GET /api/session returns completed traveller sessions.
"""
import os
import sys
from datetime import datetime
import pytest
from fastapi.testclient import TestClient

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.db.session_crud import (
    create_session,
    get_session,
    add_scan_to_session,
    save_cross_document_report,
    finalize_session,
    list_sessions,
    get_archived_session_report,
)
from backend.db.session_models import ScanSession, SessionScanLink

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    init_db()


def test_session_creation_unique_ids():
    """Verify each created session receives a distinct, uniquely generated session ID."""
    res1 = client.post("/api/session", data={"officer_id": "OFF-1", "station_id": "Station A", "documents_required": 1})
    res2 = client.post("/api/session", data={"officer_id": "OFF-2", "station_id": "Station B", "documents_required": 1})

    assert res1.status_code == 200
    assert res2.status_code == 200

    id1 = res1.json()["session_id"]
    id2 = res2.json()["session_id"]

    assert id1.startswith("SES-")
    assert id2.startswith("SES-")
    assert id1 != id2


def test_session_isolation_and_report_scoping():
    """Verify documents in Session A do NOT bleed into Session B, and report includes only scoped docs."""
    db = SessionLocal()
    try:
        sess_a = create_session(db, officer_id="OFF-A", station_id="Airport A", documents_required=1)
        sess_b = create_session(db, officer_id="OFF-B", station_id="Airport B", documents_required=1)

        payload_a = {
            "risk": {"risk_score": 10.0, "risk_tier": "LOW", "factors": [], "clear_factors": []},
            "ocr": {
                "extracted_fields": {
                    "name": {"value": "Alice Smith"},
                    "document_number": {"value": "P1234567"},
                    "nationality": {"value": "IND"},
                    "date_of_birth": {"value": "1990-01-01"},
                    "gender": {"value": "F"}
                },
                "document_type": "passport"
            },
            "validation": {"is_valid": True}
        }

        payload_b = {
            "risk": {"risk_score": 85.0, "risk_tier": "CRITICAL", "factors": ["FLAGGED"], "clear_factors": []},
            "ocr": {
                "extracted_fields": {
                    "name": {"value": "Bob Jones"},
                    "document_number": {"value": "P9999999"},
                    "nationality": {"value": "USA"},
                    "date_of_birth": {"value": "1980-05-15"},
                    "gender": {"value": "M"}
                },
                "document_type": "passport"
            },
            "validation": {"is_valid": False}
        }

        # Link document to session A only
        add_scan_to_session(
            db=db,
            session_id=sess_a.id,
            scan_id=f"SCAN-A-{sess_a.id[-6:]}",
            document_type="passport",
            document_label="Alice Passport",
            holder_name="Alice Smith",
            document_number="P1234567",
            scan_payload=payload_a,
        )

        # Link document to session B only
        add_scan_to_session(
            db=db,
            session_id=sess_b.id,
            scan_id=f"SCAN-B-{sess_b.id[-6:]}",
            document_type="passport",
            document_label="Bob Passport",
            holder_name="Bob Jones",
            document_number="P9999999",
            scan_payload=payload_b,
        )

        # Generate report for session A via API
        resp_a = client.get(f"/api/session/{sess_a.id}/report")
        assert resp_a.status_code == 200
        report_a = resp_a.json()

        # Strict scoping assertion: report must ONLY include session A data
        assert report_a["session_id"] == sess_a.id
        assert report_a["documents_submitted"] == 1
        assert len(report_a["document_details"]) == 1
        assert report_a["document_details"][0]["holder_name"] == "Alice Smith"
        assert report_a["document_details"][0]["document_number"] == "P1234567"
        assert "Bob Jones" not in str(report_a)

    finally:
        db.close()


def test_finalize_and_archive_session_to_audit_log():
    """Verify POST /api/session/{session_id}/complete writes session to audit log with decision and metadata."""
    db = SessionLocal()
    try:
        sess = create_session(db, officer_id="OFF-777", station_id="Mumbai Airport", documents_required=1)
        sess_id = sess.id
    finally:
        db.close()

    complete_payload = {
        "decision": "APPROVED",
        "officer_id": "OFF-777",
        "checkpoint": "Mumbai Airport",
        "status": "COMPLETE",
        "risk_score": 12.5,
        "risk_tier": "LOW",
        "findings": "All identity checks cleared."
    }

    res = client.post(f"/api/session/{sess_id}/complete", json=complete_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["session_id"] == sess_id
    assert data["decision"] == "APPROVED"
    assert data["session_status"] == "COMPLETE"
    assert data["completed_at"] is not None

    # Verify session appears in GET /api/session
    list_res = client.get("/api/session")
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    matching = [x for x in items if x["session_id"] == sess_id]
    assert len(matching) == 1
    assert matching[0]["decision"] == "APPROVED"
    assert matching[0]["status"] == "COMPLETE"
    assert matching[0]["risk_score"] == 12.5


def test_discard_session_with_audit_trail():
    """Verify discarding an unsaved session marks it DISCARDED in the audit trail."""
    db = SessionLocal()
    try:
        sess = create_session(db, officer_id="OFF-888", station_id="Delhi T3", documents_required=1)
        sess_id = sess.id
    finally:
        db.close()

    discard_payload = {
        "decision": "DISCARDED",
        "officer_id": "OFF-888",
        "checkpoint": "Delhi T3",
        "status": "DISCARDED",
        "findings": "Session discarded by officer with unsaved screening data."
    }

    res = client.post(f"/api/session/{sess_id}/complete", json=discard_payload)
    assert res.status_code == 200
    assert res.json()["decision"] == "DISCARDED"
    assert res.json()["session_status"] == "DISCARDED"

    # Verify reflected in database
    db2 = SessionLocal()
    try:
        record = get_session(db2, sess_id)
        assert record.status == "DISCARDED"
        assert record.decision == "DISCARDED"
        assert record.completed_at is not None
    finally:
        db2.close()


def test_get_archived_session_report():
    """Verify GET /api/session/{session_id}/archived-report returns the verified report."""
    db = SessionLocal()
    try:
        sess = create_session(db, officer_id="OFF-999", station_id="Goa Dabolim", documents_required=1)
        mock_report = {
            "session_id": sess.id,
            "session_risk_score": 5.0,
            "session_risk_tier": "LOW",
            "session_action": "CLEAR",
            "summary": "Verified traveler identity",
            "documents_submitted": 1
        }
        save_cross_document_report(db, sess.id, mock_report)
        sess_id = sess.id
    finally:
        db.close()

    res = client.get(f"/api/session/{sess_id}/archived-report")
    assert res.status_code == 200
    archived = res.json()
    assert archived["session_id"] == sess_id
    assert archived["session_risk_score"] == 5.0
    assert archived["session_risk_tier"] == "LOW"
    assert archived["session_action"] == "CLEAR"
