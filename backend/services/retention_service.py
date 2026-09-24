"""
retention_service.py - Automated document image retention and cleanup service.
Uses APScheduler running inside the FastAPI application lifecycle.

CRITICAL DATA PROTECTION & RETENTION POLICY:
- Uploaded and encrypted document image files on disk are automatically deleted
  after the configured retention window (RETENTION_MINUTES) to ensure traveler privacy and data minimization.
- The document_files DB row is preserved with deleted=True as a compliance audit tombstone.
- IMPORTANT: The structured investigative audit log in `scan_records` (risk scores,
  decisions, forensic metadata, cryptographic hashes) is PERMANENTLY RETAINED.
  Only raw image binary files are purged.
"""
from datetime import datetime, timedelta
import logging
import os
from typing import Any, Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from ..config import RETENTION_MINUTES
from ..db.database import SessionLocal
from ..db.crud import (
    get_unpurged_document_files,
    mark_document_file_deleted,
    cleanup_expired_revoked_tokens
)

logger = logging.getLogger("sentinel.retention")

# Background scheduler instance
retention_scheduler = AsyncIOScheduler()


def purge_expired_document_files(db: Session, retention_minutes: int = RETENTION_MINUTES) -> Dict[str, Any]:
    """
    Finds all document image files created more than `retention_minutes` ago,
    securely removes the physical file from disk, and marks the DB record deleted=True.
    
    =========================================================================
    CRITICAL RETENTION DISTINCTION:
    Under national border security and investigative data minimization policy:
    - The RAW IMAGE FILES on disk (tracked in document_files) are purged
      after the configured retention window to protect traveler privacy.
    - The STRUCTURED AUDIT TRAIL in `scan_records` (risk score, risk tier,
      tampering analysis, validation checks, and hashed identifiers) is
      PERMANENTLY RETAINED for investigative audit logging and statistics.
    - DO NOT DELETE or truncate scan_records during this retention purge!
    =========================================================================
    """
    cutoff = datetime.utcnow() - timedelta(minutes=retention_minutes)
    expired_files = get_unpurged_document_files(db, cutoff_time=cutoff)
    
    purged_records: List[Dict[str, Any]] = []
    failed_purges: List[str] = []

    for doc_file in expired_files:
        file_path = doc_file.file_path
        file_id = doc_file.id
        filename = doc_file.filename

        try:
            # 1. Securely remove the physical file from disk if it exists
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(
                    f"[Data Retention] Auto-deleted expired document image file: "
                    f"'{filename}' (scan_id={doc_file.scan_id}, created_at={doc_file.created_at.isoformat()})"
                )
            else:
                logger.warning(
                    f"[Data Retention] Target file was already absent on disk: {file_path} (id={file_id})"
                )

            # 2. Mark DB row deleted=True (keep row as compliance tombstone)
            mark_document_file_deleted(db, file_id)
            purged_records.append({
                "id": file_id,
                "filename": filename,
                "scan_id": doc_file.scan_id,
                "created_at": doc_file.created_at.isoformat(),
                "deleted_at": datetime.utcnow().isoformat()
            })

        except Exception as err:
            logger.error(f"[Data Retention] Failed to delete file {file_path}: {err}", exc_info=True)
            failed_purges.append(filename)

    # Also clean up expired tokens from blocklist table during retention cycle
    try:
        cleanup_expired_revoked_tokens(db)
    except Exception as tok_err:
        logger.warning(f"[Data Retention] Token blocklist cleanup warning: {tok_err}")

    return {
        "status": "success",
        "retention_minutes": retention_minutes,
        "cutoff_timestamp": cutoff.isoformat(),
        "purged_count": len(purged_records),
        "purged_files": purged_records,
        "failed_purges": failed_purges
    }


async def scheduled_retention_job():
    """Periodic task executed by APScheduler every 1-2 minutes."""
    db = SessionLocal()
    try:
        logger.debug(f"[Data Retention Scheduler] Running automated {RETENTION_MINUTES}-minute document retention check...")
        result = purge_expired_document_files(db, retention_minutes=RETENTION_MINUTES)
        if result["purged_count"] > 0:
            logger.info(
                f"[Data Retention Scheduler] Purged {result['purged_count']} expired document image(s) from disk."
            )
    except Exception as exc:
        logger.error(f"[Data Retention Scheduler] Scheduled purge error: {exc}", exc_info=True)
    finally:
        db.close()


def start_retention_scheduler():
    """Initializes and starts the APScheduler background retention job."""
    if not retention_scheduler.running:
        # Run every 1 minute
        retention_scheduler.add_job(
            scheduled_retention_job,
            trigger=IntervalTrigger(minutes=1),
            id="document_retention_purge_job",
            name=f"Purge expired document images older than {RETENTION_MINUTES} minutes",
            replace_existing=True,
            coalesce=True,
            max_instances=1
        )
        retention_scheduler.start()
        logger.info(f"[Data Retention] APScheduler started: {RETENTION_MINUTES}-minute document retention job scheduled every 1 minute.")


def stop_retention_scheduler():
    """Shuts down the retention scheduler gracefully on application shutdown."""
    if retention_scheduler.running:
        retention_scheduler.shutdown(wait=False)
        logger.info("[Data Retention] APScheduler shutdown complete.")
