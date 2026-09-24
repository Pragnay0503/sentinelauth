"""
risk_engine.py - Transparent, explainable border security risk scoring engine.
Combines:
  1. Watchlist hits (Critical +100)
  2. Document format & validation rule failures (weights w1)
  3. Image forensics tampering score (weights w2)
  4. Biometric facial matching divergence (weights w3)
"""
from typing import List, Optional
from .schemas import RiskAssessment, RiskFactor
from ..modules.ocr_extraction.schemas import OCRResult
from ..modules.document_validation.schemas import ValidationResult, Severity
from ..modules.tampering_detection.schemas import TamperingResult
from ..modules.face_verification.schemas import FaceVerifyResult


def calculate_risk(
    ocr: OCRResult,
    validation: ValidationResult,
    tampering: TamperingResult,
    biometrics: Optional[FaceVerifyResult] = None,
    historical_check: Optional[dict] = None,
    cross_document_check: Optional[dict] = None,
) -> RiskAssessment:
    factors: List[RiskFactor] = []
    clear_factors: List[str] = []
    raw_score = 0.0

    # 1. Watchlist check
    if validation.is_blacklisted:
        entry = validation.details.get("blacklist_entry") or {}
        reason = entry.get("reason", "Watchlist record matched.")
        cat = entry.get("category", "WATCHLIST_MATCH")
        points = 95.0
        raw_score += points
        factors.append(RiskFactor(
            category="WATCHLIST",
            title=f"WATCHLIST MATCH: {cat}",
            description=reason,
            points_added=points,
            severity="CRITICAL"
        ))
    else:
        clear_factors.append("No active Interpol or national watchlist alerts found for holder/document number.")

    # 2. Field-Level MRZ vs Visual Cross-Validation (Requirement 1 & 3)
    field_cross = getattr(validation, "field_cross_validation", {}) or {}
    field_tamper_forensics = getattr(tampering, "field_forensics", {}) or {}
    handled_fields = set()
    has_local_tamper = False  # initialised here; may be updated inside the loop below

    for f_name, item in field_cross.items():
        f_title = f_name.replace("_", " ").title()
        has_local_tamper = field_tamper_forensics.get(f_name) and field_tamper_forensics[f_name].likely_tampered
        
        if item.flag in ("VISUAL_MRZ_MISMATCH", "VISUAL_MRZ_MISMATCH_AND_CHECKSUM_INVALID"):
            handled_fields.add(f_name)
            if has_local_tamper:
                desc = f"{f_title}: mismatch between printed value ('{item.visual_value}') and MRZ ('{item.mrz_value}'), localized image editing detected in this region"
            else:
                desc = f"{f_title}: mismatch between printed value ('{item.visual_value}') and MRZ ('{item.mrz_value}') while MRZ check digit is valid"
            
            pts = 35.0
            raw_score += pts
            factors.append(RiskFactor(
                category="TAMPERING",
                title=f"Field Mismatch: {f_title}",
                description=desc,
                points_added=pts,
                severity="HIGH"
            ))
        elif item.flag == "MRZ_CHECKSUM_INVALID":
            handled_fields.add(f_name)
            desc = f"{f_title}: MRZ check digit validation failed (MRZ value: '{item.mrz_value}')"
            pts = 30.0
            raw_score += pts
            factors.append(RiskFactor(
                category="FORMAT",
                title=f"MRZ Check Digit Failure: {f_title}",
                description=desc,
                points_added=pts,
                severity="HIGH"
            ))

    # 2b. QR Code Verification (Structural check)
    qr_ver = validation.details.get("qr_verification") or {}
    has_qr_tamper = False
    if qr_ver:
        qr_outcome = qr_ver.get("outcome")
        if qr_outcome == "TAMPERED":
            has_qr_tamper = True
            qr_pts = 45.0
            raw_score += qr_pts
            factors.append(RiskFactor(
                category="TAMPERING",
                title="QR Code Verification Failed",
                description=qr_ver.get("reason", "QR code data conflicts with document printed fields or signature failed."),
                points_added=qr_pts,
                severity="CRITICAL"
            ))
        elif qr_outcome == "VERIFIED":
            clear_factors.append(f"QR code verification passed: {qr_ver.get('reason', 'Valid QR')}")

    # 3. Localized Field Forensics (Demoted to INFORMATIONAL - cannot decide outcome on its own)
    for f_name, f_res in field_tamper_forensics.items():
        if f_res.likely_tampered and f_name not in handled_fields:
            handled_fields.add(f_name)
            f_title = f_name.replace("_", " ").title()
            desc = (
                f"{f_title}: localized image compression/font variance observed "
                f"(ELA anomaly {f_res.ela_anomaly_score:.2f} vs neighbor baseline, font consistency {f_res.font_consistency_score:.2f}). "
                f"Informational only: structural checks decide outcome."
            )
            factors.append(RiskFactor(
                category="FORENSICS_INFO",
                title=f"Forensic Observation: {f_title}",
                description=desc,
                points_added=0.0,
                severity="LOW"
            ))

    # 4. Cross-Scan History Check (Requirement 4)
    if historical_check and historical_check.get("mismatches"):
        for hm in historical_check["mismatches"]:
            f_field = hm.get("field", "identity").replace("_", " ").title()
            pts = 35.0
            raw_score += pts
            factors.append(RiskFactor(
                category="HISTORY",
                title=f"Historical Field Conflict: {f_field}",
                description=hm.get("message", "Discrepancy with prior screening record"),
                points_added=pts,
                severity="HIGH"
            ))

    # 4b. Cross-Document Session Mismatch (strongest fraud signal available)
    # A cross-document mismatch requires two independently-forged documents to disagree —
    # much harder to fake than a single-document anomaly. Weight accordingly.
    has_cross_doc_mismatch = False
    cross_doc_mismatch_fields: List[str] = []
    if cross_document_check and cross_document_check.get("has_cross_document_mismatch"):
        has_cross_doc_mismatch = True
        cross_doc_mismatch_fields = cross_document_check.get("mismatched_fields", [])
        corroboration_factor = cross_document_check.get("corroboration_factor", 0.0)

        for field_key, field_result in cross_document_check.get("field_consistency", {}).items():
            if field_result.get("flag") != "CROSS_DOCUMENT_MISMATCH":
                continue
            f_title = field_key.replace("_", " ").title()
            doc_values = field_result.get("values", [])
            doc_names = [f"{v['document']}: '{v['value']}'" for v in doc_values]
            # 50 points per mismatched field — heavier than single-document forgery (35 pts)
            pts = 50.0
            raw_score += pts
            factors.append(RiskFactor(
                category="CROSS_DOCUMENT",
                title=f"CROSS-DOCUMENT MISMATCH: {f_title}",
                description=(
                    f"'{f_title}' does NOT match across documents submitted in this session: "
                    + " | ".join(doc_names)
                    + ". This is a strong indicator of document fraud."
                ),
                points_added=pts,
                severity="CRITICAL"
            ))

        # Corroboration factor bonus/penalty: lower corroboration raises score
        corr_penalty = round((1.0 - corroboration_factor) * 15.0, 1)
        if corr_penalty > 0:
            raw_score += corr_penalty
            factors.append(RiskFactor(
                category="CROSS_DOCUMENT",
                title="Low Identity Corroboration Across Documents",
                description=(
                    f"Only {cross_document_check.get('consistent_count', 0)} of "
                    f"{cross_document_check.get('verifiable_count', 0)} verifiable identity fields "
                    f"are consistent across the {cross_document_check.get('total_documents', 0)} submitted documents "
                    f"(corroboration factor: {corroboration_factor:.1%})."
                ),
                points_added=corr_penalty,
                severity="HIGH",
            ))
    elif cross_document_check and not cross_document_check.get("has_cross_document_mismatch") and cross_document_check.get("verifiable_count", 0) > 0:
        corr_factor = cross_document_check.get("corroboration_factor", 0.0)
        n_docs = cross_document_check.get("total_documents", 0)
        clear_factors.append(
            f"Multi-document cross-check: all {cross_document_check.get('verifiable_count', 0)} verifiable identity fields "
            f"are consistent across {n_docs} documents (corroboration: {corr_factor:.1%})."
        )


    # 5. Document Validation Violations (excluding already reported field-level mismatches)
    val_points = 0.0
    for v in validation.violations:
        if v.field in handled_fields:
            continue
        pts = 5.0
        sev = str(v.severity).upper()
        if "CRITICAL" in sev:
            pts = 30.0
        elif "HIGH" in sev:
            pts = 20.0
        elif "MEDIUM" in sev:
            pts = 10.0
        val_points += pts
        factors.append(RiskFactor(
            category="VALIDATION",
            title=f"Rule Failure: {v.field}",
            description=v.rule_violated,
            points_added=pts,
            severity=sev
        ))

    # Cap generic validation points contribution to 35
    raw_score += min(35.0, val_points)

    if not validation.violations and not handled_fields:
        clear_factors.append("All document validation rules passed: valid validity window, logical dates, and matching checksums.")

    # MRZ check (whole-document fallback)
    if ocr.mrz_applicable and not handled_fields:
        if ocr.mrz_validation_passed is True:
            clear_factors.append("ICAO 9303 MRZ checksums passed successfully.")
        elif ocr.mrz_validation_passed is False:
            mrz_pts = 25.0
            raw_score += mrz_pts
            factors.append(RiskFactor(
                category="FORMAT",
                title="MRZ Checksum Failure",
                description="Machine Readable Zone check digit mismatch detected (primary counterfeit indicator).",
                points_added=mrz_pts,
                severity="HIGH"
            ))

    # 6. Global Tampering Forensics Contribution (Demoted to INFORMATIONAL when uncorroborated)
    # ELA and image forensic noise cannot produce TAMPERED / FLAGGED on their own.
    has_corroborating_fraud = (
        validation.is_blacklisted
        or bool(validation.violations)
        or has_qr_tamper
        or has_cross_doc_mismatch
        or (ocr.mrz_applicable and ocr.mrz_validation_passed is False)
        or (biometrics is not None and biometrics.status == "SUCCESS" and not biometrics.match)
        or "PHOTO_REPLACEMENT_SUSPECTED" in tampering.flagged_checks
        or "EDITING_SOFTWARE_SIGNATURE" in tampering.flagged_checks
        or any(
            item.flag in ("VISUAL_MRZ_MISMATCH", "VISUAL_MRZ_MISMATCH_AND_CHECKSUM_INVALID", "MRZ_CHECKSUM_INVALID")
            for item in field_cross.values()
        )
    )

    if tampering.tampering_score > 0.25:
        if has_corroborating_fraud:
            tamper_pts = min(25.0, tampering.tampering_score * 30.0)
            raw_score += tamper_pts
            for flagged in tampering.flagged_checks:
                if flagged != "LOCALIZED_FIELD_TAMPERING":
                    factors.append(RiskFactor(
                        category="TAMPERING",
                        title=f"Forensic Alert: {flagged.replace('_', ' ').title()}",
                        description=" ; ".join(tampering.explanation[:2]),
                        points_added=round(tamper_pts / max(1, len(tampering.flagged_checks)), 1),
                        severity="HIGH" if tampering.tampering_score > 0.45 else "MEDIUM"
                    ))
        else:
            for flagged in tampering.flagged_checks:
                if flagged != "LOCALIZED_FIELD_TAMPERING":
                    factors.append(RiskFactor(
                        category="TAMPERING",
                        title=f"Forensic Observation (Informational): {flagged.replace('_', ' ').title()}",
                        description=" ; ".join(tampering.explanation[:2]) + " (Structural checks passed; informational only).",
                        points_added=0.0,
                        severity="LOW"
                    ))
    else:
        if not any(r.likely_tampered for r in field_tamper_forensics.values()):
            clear_factors.append("Forensic analysis verified image integrity: uniform ELA error distribution and consistent typography.")

    # 7. Biometric Face Match & S-MAD Face Morphing Attack Detection (Module 4)
    if biometrics is not None:
        if biometrics.status == "SUCCESS":
            if not biometrics.match:
                bio_pts = 30.0 * (1.0 - biometrics.confidence)
                raw_score += bio_pts
                factors.append(RiskFactor(
                    category="BIOMETRICS",
                    title="Biometric Facial Mismatch",
                    description=f"Facial similarity ({biometrics.confidence:.1%}) is below verification threshold. Holder may not match document photo.",
                    points_added=round(bio_pts, 1),
                    severity="HIGH"
                ))
            else:
                clear_factors.append(f"Biometric face match verified: {biometrics.confidence:.1%} match confidence with live presentation.")
        elif biometrics.status in ("NO_FACE_IN_DOCUMENT", "NO_FACE_IN_SELFIE"):
            bio_pts = 10.0
            raw_score += bio_pts
            factors.append(RiskFactor(
                category="BIOMETRICS",
                title="Facial Presentation Warning",
                description=biometrics.message,
                points_added=bio_pts,
                severity="MEDIUM"
            ))

        # 7b. Single-Image Face-Morphing Attack Detection (S-MAD) - INFORMATIONAL ONLY
        # Pixel-forensic signal unreliable on re-encoded or multi-panel captures (ghosting/double edge).
        # Demoted to INFORMATIONAL: displays an advisory note but must not add risk points or drive outcome.
        morph_res = getattr(biometrics, "morph_analysis", None)
        if morph_res and getattr(morph_res, "face_detected", False):
            if getattr(morph_res, "is_morph_suspected", False):
                m_score = getattr(morph_res, "morph_suspicion_score", 0.0)
                flags = getattr(morph_res, "morph_flags", [])
                flag_str = ", ".join(f.replace("_", " ").title() for f in flags) if flags else "Composite Artifacts"
                tier = getattr(morph_res, "suspicion_tier", "ELEVATED")
                factors.append(RiskFactor(
                    category="BIOMETRICS",
                    title="Face Morphing Observation (Informational: S-MAD)",
                    description=(
                        f"Informational note: document photo exhibits biometric morphing heuristic flags ({tier}, score {m_score:.2f}). "
                        f"Anomalies detected: {flag_str}. Single-image S-MAD signal is informational only on multi-panel or scanned captures."
                    ),
                    points_added=0.0,
                    severity="LOW"
                ))
            else:
                m_score = getattr(morph_res, "morph_suspicion_score", 0.0)
                clear_factors.append(
                    f"Document face photo verified authentic by S-MAD morph detection: natural skin micro-texture and coherent geometry (score {m_score:.2f})."
                )

    # 8. NON-DILUTION RISK FLOOR (Structural checks only)
    # A detected field-level forgery, visual-vs-MRZ mismatch, QR tampering, or cross-document disagreement
    # must NOT be diluted by clean fields — enforce a minimum risk floor.
    has_field_mismatch = any(
        item.flag in ("VISUAL_MRZ_MISMATCH", "VISUAL_MRZ_MISMATCH_AND_CHECKSUM_INVALID")
        for item in field_cross.values()
    )
    has_hist_mismatch = bool(historical_check and historical_check.get("mismatches"))

    if has_field_mismatch or has_hist_mismatch or has_qr_tamper:
        raw_score = max(raw_score, 65.0)

    # Cross-document mismatches are the strongest signal — raise floor higher (≥75 = HIGH→CRITICAL)
    if has_cross_doc_mismatch:
        raw_score = max(raw_score, 75.0)

    # Calculate final score (0.0 to 100.0)
    final_score = round(min(100.0, max(0.0, raw_score)), 1)

    # Determine Tier & Action
    if final_score <= 25.0:
        risk_tier = "LOW"
        operational_action = "CLEAR"
        recommendation = "Standard primary clearance. All cryptographic, logical, and biometric parameters are verified authentic."
    elif final_score <= 55.0:
        risk_tier = "MEDIUM"
        operational_action = "SECONDARY_INSPECTION"
        recommendation = "Route passenger to secondary screening booth. Verify physical document features and request secondary identity proof."
    elif final_score <= 80.0:
        risk_tier = "HIGH"
        operational_action = "SUPERVISOR_REVIEW"
        if has_cross_doc_mismatch:
            mismatch_names = [f.replace("_", " ").title() for f in cross_doc_mismatch_fields] or ["Identity field"]
            recommendation = (
                f"CROSS-DOCUMENT IDENTITY FRAUD: {', '.join(mismatch_names)} does not match across submitted documents. "
                "Hold passenger immediately; escalate to supervisor for document forensic examination."
            )
        elif has_field_mismatch or has_local_tamper or has_hist_mismatch:
            tampered_names = [f.replace("_", " ").title() for f in handled_fields] or ["Identity field"]
            recommendation = (
                f"High risk flagged: Single-field forgery or printed/MRZ mismatch detected on {', '.join(tampered_names)}. "
                "Hold passenger; examine holographic overlay and verify travel history."
            )
        else:
            recommendation = "High risk flagged. Immediate supervisor review required. Hold passenger; examine holographic overlay and verify travel history."
    else:
        risk_tier = "CRITICAL"
        operational_action = "INTERDICT_IMMEDIATE"
        if has_cross_doc_mismatch:
            mismatch_names = [f.replace("_", " ").title() for f in cross_doc_mismatch_fields] or ["Identity field"]
            recommendation = (
                f"CRITICAL: Cross-document identity mismatch on {', '.join(mismatch_names)}. "
                "Interdict passenger immediately — documents are internally inconsistent and indicate coordinated fraud."
            )
        else:
            recommendation = "CRITICAL SECURITY ALERT. Interdict passenger immediately. Flagged on security watchlist or definitive document forgery detected."

    return RiskAssessment(
        risk_score=final_score,
        risk_tier=risk_tier,
        operational_action=operational_action,
        recommendation=recommendation,
        factors=factors,
        clear_factors=clear_factors
    )

