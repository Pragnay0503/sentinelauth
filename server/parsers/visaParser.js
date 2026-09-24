import { validatePassportNumber, validateDate } from '../validators.js';
import { sanitizePersonName } from '../nameAddressSanitizer.js';

/**
 * Dedicated Visa Parser.
 * Extracts: Visa Number, Visa Type, Name, Passport Number, Nationality, DOB, Issue Date, Expiry Date, Number of Entries, Stay Duration, Issuing Authority.
 * Supports both MRV (Machine Readable Visa TD2/TD3) and standard visual text zones.
 */
export function parseVisa(words, lines, fullText) {
  const upperText = fullText.toUpperCase();
  let visaNo = "Not detected";
  let visaType = "Not detected";
  let name = "Not detected";
  let passportNo = "Not detected";
  let nationality = "Not detected";
  let dob = "Not detected";
  let issueDate = "Not detected";
  let expiryDate = "Not detected";
  let entries = "Not detected";
  let stayDuration = "Not detected";
  let issuingAuthority = "Not detected";
  let mrzLine1 = "Not detected";
  let mrzLine2 = "Not detected";

  // 1. Check for Machine Readable Visa (MRVA 2x44 or MRVB 2x36)
  const vMrzLines = lines.filter(l => (
    l.toUpperCase().includes("V<") ||
    l.toUpperCase().includes("V(") ||
    (/^V[<A-Z0-9]{25,44}/.test(l.replace(/\s+/g, '')))
  ));

  if (vMrzLines.length >= 2) {
    mrzLine1 = vMrzLines[0].replace(/[^A-Z0-9<]/gi, '<');
    mrzLine2 = vMrzLines[1].replace(/[^A-Z0-9<]/gi, '<');

    // Extract Name from MRV Line 1: V<USA<SURNAME<<GIVEN<NAMES
    const nameMatch = mrzLine1.match(/^V<[A-Z0-9]{3}([A-Z<]+)/);
    if (nameMatch) {
      const parts = nameMatch[1].split("<<");
      const surname = parts[0] ? parts[0].replace(/</g, " ").trim() : "";
      const given = parts[1] ? parts[1].replace(/</g, " ").trim() : "";
      name = `${given} ${surname}`.trim();
    }

    // Visa Number from MRV Line 2 (first 9 chars)
    if (mrzLine2.length >= 9) {
      const vNum = mrzLine2.substring(0, 9).replace(/</g, "").trim();
      if (vNum.length >= 6) visaNo = vNum;
    }

    // Nationality from MRV Line 1 (chars 2-4)
    if (mrzLine1.length >= 5) {
      const nat = mrzLine1.substring(2, 5).replace(/</g, "").trim();
      if (nat.length === 3) nationality = nat;
    }

    // DOB from MRV Line 2 (chars 13-18)
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

    // Expiry Date from MRV Line 2 (chars 21-26)
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

  // 2. Visual Zone Field Extraction
  // Visa Number
  if (visaNo === "Not detected") {
    const vMatch = upperText.match(/(?:VISA\s*NO\.?|VISA\s*NUMBER|DOCUMENT\s*NUMBER|CONTROL\s*NO)\s*[:\s]?\s*([A-Z0-9-]{6,16})/i);
    if (vMatch) visaNo = vMatch[1].trim();
    else {
      const altV = upperText.match(/\b[A-Z]{1,3}[-]?\d{6,12}\b/);
      if (altV) visaNo = altV[0];
    }
  }

  // Visa Type
  if (upperText.includes("TOURIST")) visaType = "TOURIST";
  else if (upperText.includes("BUSINESS")) visaType = "BUSINESS";
  else if (upperText.includes("ENTRY")) visaType = "ENTRY VISA";
  else if (upperText.includes("STUDENT")) visaType = "STUDENT";
  else if (upperText.includes("EMPLOYMENT") || upperText.includes("WORK")) visaType = "EMPLOYMENT / WORK";
  else if (upperText.includes("TRANSIT")) visaType = "TRANSIT";
  else if (upperText.includes("DIPLOMATIC")) visaType = "DIPLOMATIC";

  // Passport Number
  if (passportNo === "Not detected") {
    const pMatch = upperText.match(/(?:PASSPORT\s*NO\.?|PASSPORT\s*NUMBER)\s*[:\s]?\s*([A-Z0-9]{7,9})/i);
    if (pMatch) passportNo = validatePassportNumber(pMatch[1]);
    else {
      const pAlt = upperText.match(/\b[A-Z][0-9]{7,8}\b/);
      if (pAlt && pAlt[0] !== visaNo) passportNo = validatePassportNumber(pAlt[0]);
    }
  }

  // Name from visual lines
  if (name === "Not detected" || name.length < 3) {
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].toUpperCase();
      if (line.includes("NAME") || line.includes("BEARER") || line.includes("HOLDER")) {
        const split = lines[i].split(/[:\-]/);
        if (split.length > 1 && split[1].trim().length > 2) {
          const cand = split[1].trim().split(/\n|VISA|PASSPORT/i)[0].trim();
          if (cand.length > 2 && !cand.includes("REPUBLIC") && !cand.includes("EMBASSY")) {
            name = sanitizePersonName(cand);
            break;
          }
        } else if (i + 1 < lines.length && lines[i + 1].trim().length > 2) {
          const next = lines[i + 1].trim();
          if (!next.includes("PASSPORT") && !next.includes("DATE") && !next.includes("VISA")) {
            name = sanitizePersonName(next);
            break;
          }
        }
      }
    }
  }

  // Nationality
  if (nationality === "Not detected") {
    const natMatch = upperText.match(/(?:NATIONALITY|CITIZENSHIP)\s*[:\-]?\s*([A-Z\s]{3,20})/i);
    if (natMatch) {
      nationality = natMatch[1].trim();
    } else {
      if (upperText.includes("INDIAN") || upperText.includes("IND")) nationality = "INDIAN";
      else if (upperText.includes("USA") || upperText.includes("UNITED STATES")) nationality = "USA";
      else if (upperText.includes("BRITISH") || upperText.includes("GBR")) nationality = "BRITISH";
      else if (upperText.includes("CANADIAN") || upperText.includes("CAN")) nationality = "CANADIAN";
    }
  }

  // DOB
  if (dob === "Not detected") {
    const dobMatch = upperText.match(/(?:DATE\s*OF\s*BIRTH|DOB)\s*[:\-]?\s*(\d{1,2}[\/\s.-][A-Za-z0-9]{2,9}[\/\s.-]\d{4}|\d{2}[/\.-]\d{2}[/\.-]\d{4})/i);
    if (dobMatch) {
      const valid = validateDate(dobMatch[1]);
      if (valid !== "Not detected") dob = valid;
    }
  }

  // Stay Duration
  const stayMatch = upperText.match(/\b(\d+)\s*(DAYS|MONTHS|YEARS)\b/i);
  if (stayMatch) stayDuration = stayMatch[0];

  // Number of Entries
  if (upperText.includes("MULTIPLE") || upperText.includes("MULT") || upperText.includes("M-ENTRIES")) entries = "MULTIPLE";
  else if (upperText.includes("SINGLE") || upperText.includes("ONE")) entries = "SINGLE";
  else if (upperText.includes("DOUBLE") || upperText.includes("TWO")) entries = "DOUBLE";

  // Issue Date & Expiry Date
  if (issueDate === "Not detected") {
    const issueMatch = upperText.match(/(?:DATE\s*OF\s*ISSUE|ISSUED\s*ON|DOI)\s*[:\-]?\s*(\d{1,2}[\/\s.-][A-Za-z0-9]{2,9}[\/\s.-]\d{4}|\d{2}[/\.-]\d{2}[/\.-]\d{4})/i);
    if (issueMatch) {
      const valid = validateDate(issueMatch[1]);
      if (valid !== "Not detected") issueDate = valid;
    }
  }

  if (expiryDate === "Not detected") {
    const expMatch = upperText.match(/(?:DATE\s*OF\s*EXPIRY|EXPIRY\s*DATE|VALID\s*UNTIL|EXPIRATION\s*DATE)\s*[:\-]?\s*(\d{1,2}[\/\s.-][A-Za-z0-9]{2,9}[\/\s.-]\d{4}|\d{2}[/\.-]\d{2}[/\.-]\d{4})/i);
    if (expMatch) {
      const valid = validateDate(expMatch[1]);
      if (valid !== "Not detected") expiryDate = valid;
    }
  }

  // Fallback: search all dates in text
  if (issueDate === "Not detected" || expiryDate === "Not detected") {
    const allDates = (upperText.match(/\b(\d{1,2}[\/\s.-][A-Za-z0-9]{2,9}[\/\s.-]\d{4}|\d{2}[/\.-]\d{2}[/\.-]\d{4})\b/g) || [])
      .map(d => validateDate(d))
      .filter(d => d !== "Not detected" && d !== dob);

    if (allDates.length >= 1 && issueDate === "Not detected") issueDate = allDates[0];
    if (allDates.length >= 2 && expiryDate === "Not detected") expiryDate = allDates[allDates.length - 1];
  }

  // Issuing Authority
  const authMatch = upperText.match(/(?:ISSUING\s*POST|ISSUED\s*AT|AUTHORITY|PLACE\s*OF\s*ISSUE)\s*[:\-]?\s*([A-Z\s,]{3,40})/i);
  if (authMatch) {
    issuingAuthority = authMatch[1].split(/\n|DATE/)[0].trim();
  } else if (upperText.includes("EMBASSY")) {
    const embassyMatch = upperText.match(/(EMBASSY\s+(?:OF\s+)?[A-Z\s,]{2,30})/i);
    issuingAuthority = embassyMatch ? embassyMatch[1].trim() : "EMBASSY";
  } else if (upperText.includes("CONSULATE")) {
    const consulateMatch = upperText.match(/(CONSULATE\s+(?:GENERAL\s+(?:OF\s+)?)?[A-Z\s,]{2,30})/i);
    issuingAuthority = consulateMatch ? consulateMatch[1].trim() : "CONSULATE";
  }

  return {
    "Document Type": "Visa",
    "Visa Number": visaNo,
    "Visa Type": visaType,
    "Full Name": name,
    "Passport Number": passportNo,
    "Nationality": nationality,
    "Date of Birth": dob,
    "Issue Date": issueDate,
    "Expiry Date": expiryDate,
    "Number of Entries": entries,
    "Stay Duration": stayDuration,
    "Issuing Authority": issuingAuthority
  };
}
