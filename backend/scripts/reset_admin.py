"""
backend/scripts/reset_admin.py
Emergency CLI utility to reset or recreate the bootstrap admin account password.

SECURITY NOTICE:
This utility connects directly to the database via local filesystem/DB socket.
It is intentionally NOT exposed through any HTTP API or network endpoint.
It must only be executed directly on the host server:
    python -m backend.scripts.reset_admin
"""
import sys
import argparse
from datetime import datetime
from sqlalchemy.orm import Session

from backend.db.database import SessionLocal, init_db
from backend.db.models import User
from backend.db.crud import hash_password
from backend.services.auth_service import generate_temporary_password, validate_password_strength


def reset_admin_password(
    db: Session, 
    target_username: str = "admin",
    custom_password: str = None
) -> tuple[User, str, bool]:
    """
    Finds the admin user (or creates one if missing),
    generates a compliant random temporary password (or uses compliant custom_password),
    hashes it with bcrypt, updates the database,
    and sets must_change_password back to True.

    Returns:
        (User, plaintext_password, is_new)
    """
    # 1. Look for target user by username
    admin_user = db.query(User).filter(User.username == target_username).first()
    if not admin_user and target_username == "admin":
        admin_user = db.query(User).filter(User.role == "admin").first()

    # 2. Generate secure high-entropy temporary password or validate custom password
    if custom_password:
        ok, err = validate_password_strength(custom_password)
        if not ok:
            raise ValueError(f"Password does not satisfy policy: {err}")
        new_plaintext_pw = custom_password
    else:
        new_plaintext_pw = generate_temporary_password(12)

    pw_hash = hash_password(new_plaintext_pw)

    if admin_user:
        # Update existing admin account
        admin_user.hashed_password = pw_hash
        admin_user.must_change_password = True
        admin_user.active = True
        is_new = False
    else:
        # Create missing admin account with unique badge
        badge = "ADM-ROOT-001" if target_username == "admin" else f"ADM-{target_username.upper()[:8]}-001"
        admin_user = User(
            username=target_username,
            badge_id=badge,
            officer_name="System Administrator" if target_username == "admin" else f"Admin ({target_username})",
            hashed_password=pw_hash,
            role="admin",
            station_id="hyderabad-rgia",
            must_change_password=True,
            active=True,
            created_at=datetime.utcnow()
        )
        db.add(admin_user)
        is_new = True

    db.commit()
    db.refresh(admin_user)

    # Signal running server instance to clear in-memory lockout for this user
    request_server_unlock(admin_user.username, admin_user.badge_id)

    return admin_user, new_plaintext_pw, is_new


def request_server_unlock(username: str, badge_id: str = None):
    """
    Signals running server instance to clear in-memory lockout tracker
    via IPC file backend/data/.unlock_requests.
    """
    try:
        import os
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)
        unlock_file = os.path.join(data_dir, ".unlock_requests")
        with open(unlock_file, "a", encoding="utf-8") as f:
            f.write(f"{username}\n")
            if badge_id:
                f.write(f"{badge_id}\n")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="SentinelAuth Emergency CLI: Reset bootstrap admin password directly on host."
    )
    parser.add_argument(
        "--username",
        default="admin",
        help="Target administrator username to reset (default: 'admin')"
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Optional compliant password (must be 12+ chars with upper/lower/digits/symbols). If omitted, a random temporary password is generated."
    )
    parser.add_argument(
        "--unlock",
        action="store_true",
        help="Unlock user account without resetting password."
    )
    args = parser.parse_args()

    # Ensure database schema is initialized and up to date
    init_db()
    db = SessionLocal()

    try:
        if args.unlock:
            request_server_unlock(args.username)
            print(f"\n[SENTINELAUTH CLI] Sent unlock request for user '{args.username}' to running server.\n")
            return 0

        admin_user, new_pw, is_new = reset_admin_password(
            db, 
            target_username=args.username,
            custom_password=args.password
        )
        border = "=" * 72
        action_str = "Created Missing Account" if is_new else "Password Reset Succeeded"

        print("\n" + border)
        print(f" [SENTINELAUTH CLI] Bootstrap Administrator {action_str}")
        print(border)
        print(f" Username:             {admin_user.username}")
        print(f" Badge ID:             {admin_user.badge_id}")
        print(f" Role:                 {admin_user.role}")
        print(f" New Temporary Pass:   {new_pw}")
        print(f" Must Change Pass:     {admin_user.must_change_password}")
        print(f" Active Status:        {admin_user.active}")
        print(border)
        print(" NOTICE:")
        print(" - This plaintext password is only displayed ONCE to this console.")
        print(" - The user MUST change their password upon first login.")
        print(" - This command does NOT run over HTTP; it is strictly local to this host.")
        print(border + "\n")
        return 0
    except Exception as exc:
        print(f"\n[ERROR] Failed to reset administrator password: {exc}\n", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
