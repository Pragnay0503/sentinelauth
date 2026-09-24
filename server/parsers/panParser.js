import { validatePANNumber, validateDate } from '../validators.js';
import { sanitizePersonName, sanitizeRelativeName } from '../nameAddressSanitizer.js';

/**
 * Dedicated PAN Card Parser (Income Tax Department, Government of India).
 * Extracts: PAN Number, Full Name, Father's Name, Date of Birth, Issuing Authority.
 */
export function parsePAN(words = [], lines = [], fullText = "") {
  const upperText = fullText.toUpperCase();
  const upperLines = lines.map(l => l.toUpperCase().trim());

  let panNumber = "Not detected";
  let fullName = "Not detected";
  let fatherName = "Not detected";
  let dob = "Not detected";
  let panConfidence = 0;
  let nameConfidence = 0;

  // 1. PAN Number extraction: 5 letters + 4 digits + 1 letter (e.g. ABCDE1234F)
  const panMatch = upperText.match(/\b([A-Z]{5}[0-9]{4}[A-Z])\b/);
  if (panMatch) {
    panNumber = validatePANNumber(panMatch[1]);
    panConfidence = 95;
  } else {
    // Spatial search near "PERMANENT ACCOUNT NUMBER" or "PAN"
    for (const w of words) {
      const clean = w.text.toUpperCase().replace(/[^A-Z0-9]/g, '');
      const valid = validatePANNumber(clean);
      if (valid !== "Not detected") {
        panNumber = valid;
        panConfidence = Math.round(w.confidence || 90);
        break;
      }
    }
  }

  // 2. Date of Birth extraction (DD/MM/YYYY)
  const dobMatch = upperText.match(/(?:DATE\s*OF\s*BIRTH|DOB)\s*[:\-]?\s*(\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{4})/i);
  if (dobMatch) {
    const valid = validateDate(dobMatch[1]);
    if (valid !== "Not detected") dob = valid;
  } else {
    // Search any date in lines
    for (const line of upperLines) {
      const dMatch = line.match(/\b(\d{2}[\/\.-]\d{2}[\/\.-]\d{4})\b/);
      if (dMatch) {
        const valid = validateDate(dMatch[1]);
        if (valid !== "Not detected") {
          dob = valid;
          break;
        }
      }
    }
  }

  // 3. Name & Father's Name extraction
  const ignoredKeywords = [
    "INCOME TAX DEPARTMENT",
    "GOVT. OF INDIA",
    "GOVT OF INDIA",
    "GOVERNMENT OF INDIA",
    "PERMANENT ACCOUNT NUMBER",
    "PERMANENT ACCOUNT NUMBER CARD",
    "PAN CARD",
    "SIGNATURE",
    "DATE OF BIRTH",
    "DOB",
    "MALE",
    "FEMALE"
  ];

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i].trim();
    const uLine = rawLine.toUpperCase();

    // Check for explicit Name label
    if (
      (uLine.includes("NAME") || uLine.includes("CARDHOLDER") || uLine.startsWith("NAME") || uLine.includes("APPLICANT")) &&
      !uLine.includes("FATHER") && !uLine.includes("MOTHER") && !uLine.includes("HUSBAND")
    ) {
      const split = rawLine.split(/[:\-]/);
      let candidate = split.length > 1 ? split.slice(1).join(" ").trim() : "";
      if (!candidate && i + 1 < lines.length) {
        const nextLine = lines[i+1] ? lines[i+1].trim().toUpperCase() : '';
        const isFieldLabel = /^(FATHER|MOTHER|HUSBAND|DOB|DATE|PAN|PERMANENT|ACCOUNT|INCOME|GOVT|GOVERNMENT|SIGNATURE)/i.test(nextLine);
        if (!isFieldLabel && lines[i+1]) {
          candidate = lines[i + 1].trim();
        }
      }
      if (candidate) {
        const cleaned = sanitizePersonName(candidate);
        if (cleaned !== "Not detected" && !ignoredKeywords.some(k => cleaned.includes(k))) {
          fullName = cleaned;
          nameConfidence = 85;
        }
      }
    }

    // Check for explicit "FATHER'S NAME" label
    if (uLine.includes("FATHER")) {
      const split = rawLine.split(/[:\-]/);
      let candidate = split.length > 1 ? split.slice(1).join(" ").trim() : "";
      if (!candidate && i + 1 < lines.length) {
        const nextLine = lines[i+1] ? lines[i+1].trim().toUpperCase() : '';
        const isFieldLabel = /^(FATHER|MOTHER|HUSBAND|DOB|DATE|PAN|PERMANENT|ACCOUNT|INCOME|GOVT|GOVERNMENT|SIGNATURE)/i.test(nextLine);
        if (!isFieldLabel && lines[i+1]) {
          candidate = lines[i + 1].trim();
        }
      }
      if (candidate) {
        const cleaned = sanitizeRelativeName(candidate);
        if (cleaned !== "Not detected" && !ignoredKeywords.some(k => cleaned.includes(k))) {
          fatherName = cleaned;
        }
      }
    }
  }

  // Fallback: If labels were not explicitly found, check text lines strictly between Header and DOB
  if (fullName === "Not detected" || fatherName === "Not detected") {
    // Locate the header index (INCOME TAX / GOVT. OF INDIA)
    let headerIndex = -1;
    for (let i = 0; i < lines.length; i++) {
      const u = lines[i].toUpperCase();
      if (u.includes("INCOME TAX") || u.includes("GOVT") || u.includes("GOVERNMENT") || u.includes("DEPARTMENT")) {
        if (headerIndex < 0) { headerIndex = i; }
      }
    }

    // Locate the boundary where DOB or PAN begins
    let footerIndex = lines.length;
    for (let i = 0; i < lines.length; i++) {
      const u = lines[i].toUpperCase();
      if (
        (/\b\d{2}[\/\.-]\d{2}[\/\.-]\d{4}\b/.test(u) || /\b[A-Z]{5}[0-9]{4}[A-Z]\b/.test(u) || u.includes("PERMANENT ACCOUNT")) &&
        i > headerIndex
      ) {
        footerIndex = i;
        break;
      }
    }

    const searchLines = headerIndex !== -1
      ? lines.slice(headerIndex + 1, footerIndex)
      : lines.slice(0, footerIndex);

    const candidateNames = [];

    for (const rawLine of searchLines) {
      const l = rawLine.trim();
      const u = l.toUpperCase();

      if (
        ignoredKeywords.some(k => u.includes(k)) ||
        /\b[A-Z]{5}[0-9]{4}[A-Z]\b/.test(u) ||
        /\b\d{2}[\/\.-]\d{2}[\/\.-]\d{4}\b/.test(u) ||
        u.includes("SIGNATURE")
      ) {
        continue;
      }

      const sanitized = sanitizePersonName(l);
      if (
        sanitized !== "Not detected" &&
        !ignoredKeywords.some(k => sanitized.includes(k)) &&
        !candidateNames.includes(sanitized)
      ) {
        candidateNames.push(sanitized);
      }
    }

    if (candidateNames.length >= 1 && fullName === "Not detected") {
      fullName = candidateNames[0];
      nameConfidence = 85;
    }
    if (candidateNames.length >= 2 && fatherName === "Not detected") {
      fatherName = candidateNames[1];
    }
  }

  return {
    "Document Type": "PAN Card",
    "PAN Number": panNumber,
    "PAN Number Confidence": panConfidence,
    "Full Name": fullName,
    "Name Confidence": nameConfidence,
    "Father's Name": fatherName,
    "Date of Birth": dob,
    "Issuing Authority": "Income Tax Department, Government of India"
  };
}

export const parsePanCard = parsePAN;
