import { validateVoterIdNumber, validateDate } from '../validators.js';
import {
  sanitizePersonName,
  sanitizeRelativeName,
  sanitizeAddress,
  sanitizePlace
} from '../nameAddressSanitizer.js';

/**
 * Dedicated Voter ID (EPIC) Parser (Election Commission of India).
 * Extracts: EPIC/Voter ID Number, Elector's Full Name, Father's/Husband's Name, Gender, Date of Birth/Age, Address, Issuing Authority.
 */
export function parseVoterId(words = [], lines = [], fullText = "") {
  const upperText = fullText.toUpperCase();
  const upperLines = lines.map(l => l.toUpperCase().trim());

  let epicNumber = "Not detected";
  let fullName = "Not detected";
  let relationName = "Not detected";
  let dobOrAge = "Not detected";
  let gender = "Not detected";
  let address = "Not detected";
  let epicConfidence = 0;
  let nameConfidence = 0;

  // 1. EPIC Number extraction: 3 letters + 7 digits (e.g. ABC1234567, XYZ9876543)
  const epicMatch = upperText.match(/\b([A-Z]{3}[0-9]{7})\b/);
  if (epicMatch) {
    epicNumber = validateVoterIdNumber(epicMatch[1]);
    epicConfidence = 95;
  } else {
    // Spatial search for EPIC code pattern
    for (const w of words) {
      const clean = w.text.toUpperCase().replace(/[^A-Z0-9]/g, '');
      const valid = validateVoterIdNumber(clean);
      if (valid !== "Not detected") {
        epicNumber = valid;
        epicConfidence = Math.round(w.confidence || 90);
        break;
      }
    }
  }

  // 2. Gender extraction
  if (/\b(FEMALE|WOMAN)\b/i.test(upperText)) {
    gender = "Female";
  } else if (/\b(MALE|MAN)\b/i.test(upperText)) {
    gender = "Male";
  } else if (/\b(TRANSGENDER|OTHER)\b/i.test(upperText)) {
    gender = "Transgender";
  }

  // 3. Date of Birth or Age extraction
  const dobMatch = upperText.match(/(?:DATE\s*OF\s*BIRTH|DOB)\s*[:\-]?\s*(\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{4})/i);
  if (dobMatch) {
    const valid = validateDate(dobMatch[1]);
    if (valid !== "Not detected") dobOrAge = valid;
  }

  if (dobOrAge === "Not detected") {
    const ageMatch = upperText.match(/\bAGE\s*[:\-]?\s*(\d{1,3})\s*(?:YEARS?)?\b/i);
    if (ageMatch) {
      dobOrAge = `Age ${ageMatch[1]} Years`;
    } else {
      for (const line of upperLines) {
        const dMatch = line.match(/\b(\d{2}[\/\.-]\d{2}[\/\.-]\d{4})\b/);
        if (dMatch) {
          const valid = validateDate(dMatch[1]);
          if (valid !== "Not detected") {
            dobOrAge = valid;
            break;
          }
        }
      }
    }
  }

  // 4. Name & Relative Name extraction
  const ignoredKeywords = [
    "ELECTION COMMISSION OF INDIA",
    "ELECTION COMMISSION",
    "BHARAT NIRVACHAN AAYOG",
    "ELECTOR PHOTO IDENTITY CARD",
    "IDENTITY CARD",
    "GOVT OF INDIA",
    "GOVERNMENT OF INDIA",
    "EPIC",
    "MALE",
    "FEMALE",
    "SEX",
    "GENDER",
    "AGE",
    "DOB",
    "DATE",
    "ADDRESS",
    "SIGNATURE"
  ];

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i].trim();
    const uLine = rawLine.toUpperCase();

    // Elector's Name
    if (
      (uLine.includes("ELECTOR'S NAME") || uLine.includes("ELECTOR NAME") || uLine.startsWith("NAME:") || uLine.startsWith("NAME -") || uLine === "NAME") &&
      !uLine.includes("FATHER") && !uLine.includes("HUSBAND") && !uLine.includes("MOTHER")
    ) {
      const split = rawLine.split(/[:\-]/);
      let candidate = split.length > 1 ? split.slice(1).join(" ").trim() : "";
      if (!candidate && i + 1 < lines.length) {
        candidate = lines[i + 1].trim();
      }
      if (candidate) {
        const cleaned = sanitizePersonName(candidate);
        if (cleaned !== "Not detected" && !ignoredKeywords.some(k => cleaned.includes(k))) {
          fullName = cleaned;
          nameConfidence = 85;
        }
      }
    }

    // Relative's Name (Father / Husband / Mother / Guardian)
    if (uLine.includes("FATHER") || uLine.includes("HUSBAND") || uLine.includes("MOTHER") || uLine.includes("RELATION")) {
      const split = rawLine.split(/[:\-]/);
      let candidate = split.length > 1 ? split.slice(1).join(" ").trim() : "";
      if (!candidate && i + 1 < lines.length) {
        candidate = lines[i + 1].trim();
      }
      if (candidate) {
        const cleaned = sanitizeRelativeName(candidate);
        if (cleaned !== "Not detected" && !ignoredKeywords.some(k => cleaned.includes(k))) {
          relationName = cleaned;
        }
      }
    }

    // Address
    if (uLine.includes("ADDRESS")) {
      const split = rawLine.split(/[:\-]/);
      let addressText = split.length > 1 ? split.slice(1).join(" ").trim() : "";
      if (!addressText && i + 1 < lines.length) {
        addressText = lines[i + 1].trim();
      }
      if (addressText) {
        // Collect subsequent lines as part of the address
        let addressLines = [addressText];
        const startJ = split.length > 1 ? i + 1 : i + 2;
        for (let j = startJ; j < lines.length && j <= startJ + 3; j++) {
          const nextLine = lines[j].trim();
          if (!nextLine) break;
          if (/^(ELECTOR|FATHER|MOTHER|HUSBAND|GENDER|SEX|DOB|DATE|EPIC|PHOTO)/i.test(nextLine)) break;
          if (/\b[A-Z]{3}\d{7}\b/.test(nextLine)) break;
          addressLines.push(nextLine);
        }
        const cleaned = sanitizeAddress(addressLines.join(', '));
        if (cleaned !== "Not detected") {
          address = cleaned;
        }
      }
    }
  }

  // Fallback: If names weren't explicitly matched with labels
  if (fullName === "Not detected") {
    const candidateLines = [];
    for (const rawLine of lines) {
      const l = rawLine.trim();
      const u = l.toUpperCase();

      if (
        ignoredKeywords.some(k => u.includes(k)) ||
        /\b[A-Z]{3}[0-9]{7}\b/.test(u) ||
        /\b\d{2}[\/\.-]\d{2}[\/\.-]\d{4}\b/.test(u)
      ) {
        continue;
      }

      const constituencyKeywords = /ASSEMBLY|CONSTITUENCY|POLLING|STATION|BOOTH|PART|SECTION|ELECTORAL|ROLL/i;
      if (constituencyKeywords.test(u)) continue; // skip constituency text

      const sanitized = sanitizePersonName(l);
      if (
        sanitized !== "Not detected" &&
        !ignoredKeywords.some(k => sanitized.includes(k)) &&
        !candidateLines.includes(sanitized)
      ) {
        candidateLines.push(sanitized);
      }
    }

    if (candidateLines.length >= 1) {
      fullName = candidateLines[0];
      nameConfidence = 75;
    }
    if (candidateLines.length >= 2 && relationName === "Not detected") {
      relationName = candidateLines[1];
    }
  }

  return {
    "Document Type": "Voter ID",
    "EPIC / Voter ID Number": epicNumber,
    "EPIC Number Confidence": epicConfidence,
    "Full Name": fullName,
    "Name Confidence": nameConfidence,
    "Father's / Husband's Name": relationName,
    "Gender": gender,
    "Date of Birth / Age": dobOrAge,
    "Address": address,
    "Issuing Authority": "Election Commission of India"
  };
}
