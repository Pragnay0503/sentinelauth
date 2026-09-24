"""
blacklist.py — Watchlist & Blacklist verification engine.
Manages a mock SQLite database (data/mock_watchlist.db) with 20 seeded fake entries.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def get_db_path() -> Path:
    """Find or initialize the mock watchlist database path."""
    repo_root = Path(__file__).resolve().parents[3]
    candidate1 = repo_root / "data" / "mock_watchlist.db"
    candidate2 = repo_root / "backend" / "data" / "mock_watchlist.db"

    target = candidate1
    target.parent.mkdir(parents=True, exist_ok=True)
    candidate2.parent.mkdir(parents=True, exist_ok=True)
    return target


SEEDED_BLACKLIST_ENTRIES = [
    {
        "document_number": "J8923451",
        "name": "VIKTOR KOROLEV",
        "dob": "14/07/1978",
        "nationality": "RUS",
        "reason": "Interpol Red Notice - Wire Fraud & Cybercrime Syndicate",
        "category": "INTERPOL_RED_NOTICE",
    },
    {
        "document_number": "N7128945",
        "name": "CARLOS MENDEZ SILVA",
        "dob": "22/11/1984",
        "nationality": "COL",
        "reason": "International Narcotics Trafficking Conspiracy",
        "category": "ORGANIZED_CRIME",
    },
    {
        "document_number": "ABCDE1234F",
        "name": "RAJESH AGRAWAL",
        "dob": "05/03/1971",
        "nationality": "IND",
        "reason": "Financial Fraud & Tax Evasion Absconder Warrant",
        "category": "SANCTIONED_ENTITY",
    },
    {
        "document_number": "XYZPK9876Q",
        "name": "MEHUL CHOKSI",
        "dob": "12/09/1965",
        "nationality": "IND",
        "reason": "Bank Fraud & Fugitive Economic Offender",
        "category": "SANCTIONED_ENTITY",
    },
    {
        "document_number": "999900001111",
        "name": "DEVENDRA KUMAR",
        "dob": "01/01/1980",
        "nationality": "IND",
        "reason": "Forged UIDAI Identity Network Distribution",
        "category": "DOCUMENT_FRAUD",
    },
    {
        "document_number": "A1234567",
        "name": "ALEXEI VOLKOV",
        "dob": "18/05/1982",
        "nationality": "RUS",
        "reason": "Interpol Stolen & Lost Travel Documents (SLTD) Alert",
        "category": "STOLEN_PASSPORT",
    },
    {
        "document_number": "P4567890",
        "name": "FATIMA AL-MANSOOR",
        "dob": "09/10/1990",
        "nationality": "UAE",
        "reason": "Terrorism Financing & Sanctions Evader Watchlist",
        "category": "TERRORISM_FINANCING",
    },
    {
        "document_number": "DL1420110012345",
        "name": "AMIT SHARMA",
        "dob": "30/08/1985",
        "nationality": "IND",
        "reason": "Fatal Hit-and-Run Extradition Warrant",
        "category": "WARRANT",
    },
    {
        "document_number": "MH0220180098765",
        "name": "SUNIL PATIL",
        "dob": "15/04/1992",
        "nationality": "IND",
        "reason": "Commercial Driving License Fabrication Ring Leader",
        "category": "IDENTITY_THEFT",
    },
    {
        "document_number": "Z9876543",
        "name": "TARIQ HUSSAIN",
        "dob": "03/12/1976",
        "nationality": "GBR",
        "reason": "Extradition Request - Contraband Smuggling",
        "category": "EXTRADITION",
    },
    {
        "document_number": "V5544332",
        "name": "ELENA ROSTOVA",
        "dob": "27/02/1988",
        "nationality": "UKR",
        "reason": "Immigration Fraud & Unlawful Entry Conviction",
        "category": "IMMIGRATION_OVERSTAY",
    },
    {
        "document_number": "BCDFG8899K",
        "name": "HARPREET SINGH",
        "dob": "10/06/1983",
        "nationality": "IND",
        "reason": "Counterfeit National PAN Syndicate Coordinator",
        "category": "DOCUMENT_FRAUD",
    },
    {
        "document_number": "987654321098",
        "name": "MOHAMMED RAFIQ",
        "dob": "21/04/1979",
        "nationality": "IND",
        "reason": "Cross-Border Counterfeit Identity Distribution",
        "category": "DOCUMENT_FRAUD",
    },
    {
        "document_number": "K1122334",
        "name": "JOHN SMITH",
        "dob": "19/07/1981",
        "nationality": "USA",
        "reason": "Federal Wire Fraud Wanted Fugitive",
        "category": "WARRANT",
    },
    {
        "document_number": "W8877665",
        "name": "CHEN WEI",
        "dob": "08/08/1975",
        "nationality": "CHN",
        "reason": "Export Control & International Sanctions Violation",
        "category": "SANCTIONED_ENTITY",
    },
    {
        "document_number": "ABC1928374",
        "name": "RAMESH BABU",
        "dob": "14/03/1986",
        "nationality": "IND",
        "reason": "Multi-Identity Voter Registration Fraud",
        "category": "DOCUMENT_FRAUD",
    },
    {
        "document_number": "XYZ5647382",
        "name": "SURESH GUPTA",
        "dob": "02/11/1974",
        "nationality": "IND",
        "reason": "Electoral Fraud Investigation Arrest Warrant",
        "category": "WARRANT",
    },
    {
        "document_number": "F9081726",
        "name": "AHMED KHALIL",
        "dob": "17/09/1987",
        "nationality": "EGY",
        "reason": "Visa Overstay & Absconded Foreign National",
        "category": "IMMIGRATION_OVERSTAY",
    },
    {
        "document_number": "T3344556",
        "name": "MARC DUPONT",
        "dob": "25/12/1980",
        "nationality": "FRA",
        "reason": "Interpol Diffusion Notice - Money Laundering",
        "category": "INTERPOL_RED_NOTICE",
    },
    {
        "document_number": "223344556677",
        "name": "AJAY VERMA",
        "dob": "04/05/1995",
        "nationality": "IND",
        "reason": "Fabricated Biometric Data Investigation",
        "category": "DOCUMENT_FRAUD",
    },
]


def init_watchlist_db(db_path: Optional[Path] = None) -> Path:
    """Initialize SQLite database and seed 20 fake blacklisted records if empty."""
    target_path = db_path or get_db_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(target_path)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_number TEXT NOT NULL,
                name TEXT NOT NULL,
                dob TEXT,
                nationality TEXT,
                reason TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_num ON watchlist (document_number);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_name ON watchlist (name);")

        cursor.execute("SELECT COUNT(*) FROM watchlist")
        count = cursor.fetchone()[0]

        if count == 0:
            for entry in SEEDED_BLACKLIST_ENTRIES:
                cursor.execute(
                    """
                    INSERT INTO watchlist (document_number, name, dob, nationality, reason, category)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry["document_number"],
                        entry["name"],
                        entry.get("dob"),
                        entry.get("nationality"),
                        entry["reason"],
                        entry["category"],
                    ),
                )
            conn.commit()

    return target_path


def _clean_doc_number(doc_no: Optional[str]) -> str:
    """Remove whitespace, hyphens, and punctuation for strict alphanumeric matching."""
    if not doc_no:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(doc_no).upper())


def _normalize_name(name_str: Optional[str]) -> str:
    """Normalize names for matching."""
    if not name_str:
        return ""
    clean = re.sub(r"[^A-Z\s]", " ", str(name_str).upper())
    return " ".join(clean.split())


def _clean_dob(dob_str: Optional[str]) -> str:
    """Normalize date of birth string to pure digits."""
    if not dob_str:
        return ""
    return re.sub(r"\D", "", str(dob_str))


def check_blacklist(
    document_number: Optional[str] = None,
    name: Optional[str] = None,
    dob: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check if a document number, name, or DOB matches the mock watchlist database.

    Returns:
        (is_blacklisted: bool, match_details: Optional[Dict[str, Any]])
    """
    target_path = init_watchlist_db(db_path)

    clean_doc = _clean_doc_number(document_number)
    clean_name = _normalize_name(name)
    clean_dob_digits = _clean_dob(dob)

    if not clean_doc and not clean_name:
        return False, None

    with sqlite3.connect(str(target_path)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 1. Check Document Number Match
        if clean_doc:
            cursor.execute("SELECT * FROM watchlist")
            rows = cursor.fetchall()
            for row in rows:
                db_doc = _clean_doc_number(row["document_number"])
                if db_doc and (db_doc == clean_doc or clean_doc.endswith(db_doc) or db_doc.endswith(clean_doc)):
                    return True, {
                        "matched_by": "document_number",
                        "matched_document_number": row["document_number"],
                        "matched_name": row["name"],
                        "dob": row["dob"],
                        "nationality": row["nationality"],
                        "reason": row["reason"],
                        "category": row["category"],
                    }

        # 2. Check Name (+ DOB) Match
        if clean_name:
            cursor.execute("SELECT * FROM watchlist")
            rows = cursor.fetchall()
            name_tokens = set(clean_name.split())

            for row in rows:
                db_name = _normalize_name(row["name"])
                db_name_tokens = set(db_name.split())
                db_dob_digits = _clean_dob(row["dob"])

                shared_tokens = name_tokens.intersection(db_name_tokens)
                is_name_match = (
                    clean_name == db_name
                    or len(shared_tokens) >= 2
                    or (len(name_tokens) == 1 and clean_name in db_name)
                )

                if is_name_match:
                    if clean_dob_digits and db_dob_digits:
                        if clean_dob_digits == db_dob_digits or clean_dob_digits[-4:] == db_dob_digits[-4:]:
                            return True, {
                                "matched_by": "name_and_dob",
                                "matched_document_number": row["document_number"],
                                "matched_name": row["name"],
                                "dob": row["dob"],
                                "nationality": row["nationality"],
                                "reason": row["reason"],
                                "category": row["category"],
                            }
                    elif len(shared_tokens) >= 2 and clean_name == db_name:
                        return True, {
                            "matched_by": "name",
                            "matched_document_number": row["document_number"],
                            "matched_name": row["name"],
                            "dob": row["dob"],
                            "nationality": row["nationality"],
                            "reason": row["reason"],
                            "category": row["category"],
                        }

    return False, None
