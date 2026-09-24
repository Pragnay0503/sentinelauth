import { 
  validatePassportNumber, 
  validateDate, 
  validateMRZ 
} from '../validators.js';
import {
  sanitizePersonName,
  sanitizeRelativeName,
  sanitizeAddress,
  sanitizePlace
} from '../nameAddressSanitizer.js';

/**
 * Dedicated Passport Parser.
 * Separately extracts & validates ICAO TD3 MRZ lines (2 lines x 44 chars) and Visual Zone text.
 */
export function parsePassport(words, lines, fullText) {
  const upperText = fullText.toUpperCase();
  let surname = "Not detected";
  let givenName = "Not detected";
  let fullName = "Not detected";
  let passportNo = "Not detected";
  let nationality = "Not detected";
  let dob = "Not detected";
  let sex = "Not detected";
  let issueDate = "Not detected";
  let expiryDate = "Not detected";
  let placeOfBirth = "Not detected";
  let placeOfIssue = "Not detected";
  let mrzLine1 = "Not detected";
  let mrzLine2 = "Not detected";
  let mrzStatus = { isValid: false, reason: "No MRZ Detected" };

  // 1. Locate MRZ Lines (TD3 lines: ~44 characters containing <, or starting with P<)
  const candidateMrzLines = lines
    .map(l => l.trim())
    .filter(l => (
      l.toUpperCase().includes("P<") || 
      l.toUpperCase().includes("P(") ||
      (l.includes("<") && l.replace(/[^A-Z0-9<]/gi, '').length >= 25) ||
      (/[A-Z0-9<]{30,45}/.test(l.replace(/\s+/g, '')))
    ));

  if (candidateMrzLines.length >= 2) {
    // Find the line that looks like Line 1 (starts with P) and Line 2 (contains digits and checksums)
    let rawL1 = candidateMrzLines.find(l => /^P[<(\[{A-Z]/i.test(l.trim())) || candidateMrzLines[0];
    let rawL2 = candidateMrzLines.find(l => l !== rawL1 && /[0-9]{6}/.test(l)) || candidateMrzLines[1];

    // Validate MRZ via ICAO Check Digits with auto-repair
    mrzStatus = validateMRZ(rawL1, rawL2);

    mrzLine1 = mrzStatus.repairedLine1 || rawL1;
    mrzLine2 = mrzStatus.repairedLine2 || rawL2;

    // Extract Name from MRZ Line 1: P<IND<SURNAME<<GIVEN<NAMES<<<<
    const nameMatch = mrzLine1.match(/^P<[A-Z0-9]{3}([A-Z<]+)/);
    if (nameMatch) {
      const rawNameParts = nameMatch[1].split("<<");
      if (rawNameParts.length > 0) surname = rawNameParts[0].replace(/</g, " ").trim();
      if (rawNameParts.length > 1) givenName = rawNameParts[1].replace(/</g, " ").trim();
      fullName = `${givenName} ${surname}`.trim();
    }

    // Extract Passport No from MRZ Line 2 (first 9 chars)
    const mrzDocNo = mrzLine2.substring(0, 9).replace(/</g, "").trim();
    const validatedPass = validatePassportNumber(mrzDocNo);
    if (validatedPass !== "Not detected") passportNo = validatedPass;

    // Extract Nationality from MRZ Line 1
    if (mrzLine1.length >= 5) {
      const nat = mrzLine1.substring(2, 5).replace(/</g, "").trim();
      if (nat.length === 3) nationality = nat;
    }

    // Extract DOB from MRZ Line 2 (chars 13-18)
    if (mrzLine2.length >= 19) {
      const dobStr = mrzLine2.substring(13, 19);
      if (/^\d{6}$/.test(dobStr)) {
        const yy = dobStr.substring(0, 2);
        const mm = dobStr.substring(2, 4);
        const dd = dobStr.substring(4, 6);
        const year = parseInt(yy, 10) > 30 ? `19${yy}` : `20${yy}`;
        dob = validateDate(`${dd}/${mm}/${year}`);
      }
    }

    // Extract Sex from MRZ Line 2 (char 20)
    if (mrzLine2.length >= 21) {
      const s = mrzLine2.charAt(20);
      if (s === 'M' || s === 'F') sex = s === 'M' ? 'Male (M)' : 'Female (F)';
    }

    // Extract Expiry from MRZ Line 2 (chars 21-26)
    if (mrzLine2.length >= 27) {
      const expStr = mrzLine2.substring(21, 27);
      if (/^\d{6}$/.test(expStr)) {
        const yy = expStr.substring(0, 2);
        const mm = expStr.substring(2, 4);
        const dd = expStr.substring(4, 6);
        expiryDate = validateDate(`${dd}/${mm}/20${yy}`);
      }
    }
  }

  // 2. Fallbacks & Enhancements from Visual Zone
  // Passport Number
  if (passportNo === "Not detected") {
    const pMatch = upperText.match(/(?:PASSPORT\s*(?:NO|NUMBER)|DOCUMENT\s*NO)\s*[:\-]?\s*([A-Z][0-9]{7,8}|[A-Z0-9]{8,9})/i);
    if (pMatch) {
      passportNo = validatePassportNumber(pMatch[1]);
    } else {
      const pAlt = upperText.match(/\b[A-Z][0-9]{7,8}\b/);
      if (pAlt) passportNo = validatePassportNumber(pAlt[0]);
    }
  }

  // Full Name from visual zone
  if (fullName === "Not detected" || fullName.length < 3) {
    const nameMatch = upperText.match(/(?:GIVEN\s*NAMES?|FULL\s*NAME|NAME|NOM)\s*[:\-]?\s*([A-Z\s]{3,40})/);
    if (nameMatch) {
      const candidate = nameMatch[1].split(/\n|PASSPORT|DATE|DOB|SEX|NATIONALITY/i)[0].trim();
      if (candidate.length > 2 && !candidate.includes("REPUBLIC") && !candidate.includes("GOVERNMENT")) {
        fullName = candidate;
        givenName = candidate;
      }
    }
  }

  // Nationality
  if (nationality === "Not detected") {
    if (upperText.includes("INDIAN") || upperText.includes("REPUBLIC OF INDIA")) nationality = "INDIAN (IND)";
    else if (upperText.includes("UNITED STATES") || upperText.includes("USA")) nationality = "USA";
    else if (upperText.includes("BRITISH") || upperText.includes("UNITED KINGDOM") || upperText.includes("GBR")) nationality = "BRITISH (GBR)";
    else if (upperText.includes("CANADIAN") || upperText.includes("CANADA") || upperText.includes("CAN")) nationality = "CANADIAN (CAN)";
    else if (upperText.includes("AUSTRALIAN") || upperText.includes("AUSTRALIA") || upperText.includes("AUS")) nationality = "AUSTRALIAN (AUS)";
    else if (upperText.includes("FRENCH") || upperText.includes("FRANCE") || upperText.includes("FRA")) nationality = "FRENCH (FRA)";
    else if (upperText.includes("GERMAN") || upperText.includes("DEUTSCH") || upperText.includes("DEU")) nationality = "GERMAN (DEU)";
    else if (upperText.includes("EMIRATES") || upperText.includes("UAE") || upperText.includes("ARE")) nationality = "EMIRATI (ARE)";
  }

  // Sex
  if (sex === "Not detected") {
    if (/\b(SEX|GENDER)\s*[:\-]?\s*M(ALE)?\b/i.test(upperText)) sex = "Male (M)";
    else if (/\b(SEX|GENDER)\s*[:\-]?\s*F(EMALE)?\b/i.test(upperText)) sex = "Female (F)";
  }

  // Date of Birth
  if (dob === "Not detected") {
    const dobMatch = upperText.match(/(?:DATE\s*OF\s*BIRTH|DOB|DATE\s*DE\s*NAISSANCE)\s*[:\-]?\s*(\d{1,2}[\/\s.-][A-Za-z0-9]{2,9}[\/\s.-]\d{4}|\d{2}[/\.-]\d{2}[/\.-]\d{4})/i);
    if (dobMatch) {
      const valid = validateDate(dobMatch[1]);
      if (valid !== "Not detected") dob = valid;
    }
  }

  // Date of Issue
  if (issueDate === "Not detected") {
    const issueMatch = upperText.match(/(?:DATE\s*OF\s*ISSUE|ISSUED\s*ON|DOI|DATE\s*DE\s*DELIVRANCE)\s*[:\-]?\s*(\d{1,2}[\/\s.-][A-Za-z0-9]{2,9}[\/\s.-]\d{4}|\d{2}[/\.-]\d{2}[/\.-]\d{4})/i);
    if (issueMatch) {
      const valid = validateDate(issueMatch[1]);
      if (valid !== "Not detected") issueDate = valid;
    }
  }

  // Date of Expiry
  if (expiryDate === "Not detected") {
    const expMatch = upperText.match(/(?:DATE\s*OF\s*EXPIRY|EXPIRY\s*DATE|VALID\s*UNTIL|DATE\s*D'EXPIRATION)\s*[:\-]?\s*(\d{1,2}[\/\s.-][A-Za-z0-9]{2,9}[\/\s.-]\d{4}|\d{2}[/\.-]\d{2}[/\.-]\d{4})/i);
    if (expMatch) {
      const valid = validateDate(expMatch[1]);
      if (valid !== "Not detected") expiryDate = valid;
    }
  }

  // Place of Issue / Place of Birth
  const pobMatch = upperText.match(/(?:PLACE\s*OF\s*BIRTH|LIEU\s*DE\s*NAISSANCE)\s*[:\-]?\s*([A-Z\s,]{3,30})/i);
  if (pobMatch) {
    const cleanedPob = sanitizePlace(pobMatch[1]);
    if (cleanedPob !== "Not detected") placeOfBirth = cleanedPob;
  }

  const poiMatch = upperText.match(/(?:PLACE\s*OF\s*ISSUE|AUTHORITY|ISSUING\s*AUTHORITY)\s*[:\-]?\s*([A-Z\s,]{3,40})/i);
  if (poiMatch) {
    const cleanedPoi = sanitizePlace(poiMatch[1]);
    if (cleanedPoi !== "Not detected") placeOfIssue = cleanedPoi;
  }

  // Address (present on Passport page 2 / back cover)
  let address = "Not detected";
  const addrMatch = upperText.match(/ADDRESS\s*[:\-]?\s*([A-Z0-9\s,.\/-]{10,200})/i);
  if (addrMatch) {
    const cleanedAddr = sanitizeAddress(addrMatch[1]);
    if (cleanedAddr !== "Not detected") address = cleanedAddr;
  }

  // Father's Name / Legal Guardian (on Passport page 2)
  let fatherName = "Not detected";
  const fatherMatch = upperText.match(/(?:NAME\s*OF\s*FATHER|LEGAL\s*GUARDIAN|FATHER)\s*[:\-]?\s*([A-Z\s.]{3,40})/i);
  if (fatherMatch) {
    const cleanedFather = sanitizeRelativeName(fatherMatch[1]);
    if (cleanedFather !== "Not detected") fatherName = cleanedFather;
  }

  const cleanedFullName = sanitizePersonName(
    fullName !== "Not detected" ? fullName : (givenName !== "Not detected" ? givenName : surname)
  );

  return {
    "Document Type": "Passport",
    "Surname": surname !== "Not detected" ? sanitizePersonName(surname) : "Not detected",
    "Given Name": givenName !== "Not detected" ? sanitizePersonName(givenName) : "Not detected",
    "Full Name": cleanedFullName !== "Not detected" ? cleanedFullName : fullName,
    "Passport Number": passportNo,
    "Nationality": nationality,
    "Date of Birth": dob,
    "Sex": sex,
    "Date of Issue": issueDate,
    "Date of Expiry": expiryDate,
    "Place of Birth": placeOfBirth,
    "Place of Issue": placeOfIssue,
    "Father's Name": fatherName,
    "Address": address,
    "MRZ Line 1": mrzLine1,
    "MRZ Line 2": mrzLine2,
    "MRZ Checksum Status": mrzStatus.reason
  };
}
