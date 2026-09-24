/**
 * Validation utilities for identity document field extraction.
 * Rule: If validation fails, value must return "Not detected" instead of guessing.
 */
import fs from 'fs';
import path from 'path';

// Load country-specific format configurations (10 countries)
let countryFormats = {};
try {
  const p = path.resolve('data/country_formats.json');
  if (fs.existsSync(p)) {
    countryFormats = JSON.parse(fs.readFileSync(p, 'utf8'));
  }
} catch (e) {
  console.warn('[Validators] Could not load country_formats.json:', e.message);
}

export function validateCountryFormat(docType, number, nationality) {
  if (!number || !nationality) return null;
  const natUpper = String(nationality).toUpperCase().trim();
  const natToCode = {
    'INDIAN': 'IN', 'INDIA': 'IN', 'IND': 'IN',
    'AMERICAN': 'US', 'USA': 'US', 'UNITED STATES': 'US',
    'BRITISH': 'GB', 'GBR': 'GB', 'UNITED KINGDOM': 'GB',
    'CANADIAN': 'CA', 'CANADA': 'CA', 'CAN': 'CA',
    'AUSTRALIAN': 'AU', 'AUSTRALIA': 'AU', 'AUS': 'AU',
    'FRENCH': 'FR', 'FRANCE': 'FR', 'FRA': 'FR',
    'GERMAN': 'DE', 'GERMANY': 'DE', 'DEU': 'DE',
    'EMIRATI': 'AE', 'UAE': 'AE', 'ARE': 'AE',
    'SINGAPOREAN': 'SG', 'SINGAPORE': 'SG', 'SGP': 'SG',
    'CHINESE': 'CN', 'CHINA': 'CN', 'CHN': 'CN',
    'NIGERIAN': 'NG', 'NIGERIA': 'NG', 'NGA': 'NG',
  };

  const code = natToCode[natUpper] || (natUpper.length === 2 ? natUpper : null);
  if (!code || !countryFormats[code]) return null;

  const country = countryFormats[code];
  const isPassport = (docType || '').toLowerCase().includes('passport');
  const isVisa = (docType || '').toLowerCase().includes('visa');
  const pattern = isPassport ? country.passport : (isVisa ? country.visa : null);
  if (!pattern) return null;

  const cleanNum = number.replace(/[^A-Z0-9]/g, '');
  const isValid = new RegExp(pattern).test(cleanNum);
  return {
    country_code: code,
    country_name: country.country_name,
    pattern,
    is_valid: isValid
  };
}

// Months map for textual dates (e.g. 14 AUG 1992, 08-OCT-2006)
const MONTH_MAP = {
  JAN: '01', JANUARY: '01',
  FEB: '02', FEBRUARY: '02',
  MAR: '03', MARCH: '03',
  APR: '04', APRIL: '04',
  MAY: '05',
  JUN: '06', JUNE: '06',
  JUL: '07', JULY: '07',
  AUG: '08', AUGUST: '08',
  SEP: '09', SEPT: '09', SEPTEMBER: '09',
  OCT: '10', OCTOBER: '10',
  NOV: '11', NOVEMBER: '11',
  DEC: '12', DECEMBER: '12'
};

// Validate Date string format and logical calendar range
export function validateDate(dateStr) {
  if (!dateStr || dateStr === "Not detected") return "Not detected";
  
  // Clean whitespace
  const clean = dateStr.trim().toUpperCase();

  // Pattern 1: DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
  const m1 = clean.match(/^(\d{1,2})[/\.-](\d{1,2})[/\.-](\d{4})$/);
  if (m1) {
    const day = parseInt(m1[1], 10);
    const month = parseInt(m1[2], 10);
    const year = parseInt(m1[3], 10);

    if (month >= 1 && month <= 12 && day >= 1 && day <= 31 && year >= 1900 && year <= 2100) {
      const dd = String(day).padStart(2, '0');
      const mm = String(month).padStart(2, '0');
      return `${dd}/${mm}/${year}`;
    }
  }

  // Pattern 2: Textual Month (e.g. 14-AUG-1992, 14 AUG 1992, 08/OCT/2006)
  const mText1 = clean.match(/^(\d{1,2})[/\s.-]([A-Z]{3,9})[/\s.-](\d{4})$/);
  if (mText1) {
    const day = parseInt(mText1[1], 10);
    const mStr = mText1[2];
    const year = parseInt(mText1[3], 10);
    const mm = MONTH_MAP[mStr];

    if (mm && day >= 1 && day <= 31 && year >= 1900 && year <= 2100) {
      const dd = String(day).padStart(2, '0');
      return `${dd}/${mm}/${year}`;
    }
  }

  // Pattern 3: Textual Month First (e.g. AUG 14 1992, AUGUST 14, 1992)
  const mText2 = clean.match(/^([A-Z]{3,9})[/\s.-](\d{1,2})[,\s/\.-]+(\d{4})$/);
  if (mText2) {
    const mStr = mText2[1];
    const day = parseInt(mText2[2], 10);
    const year = parseInt(mText2[3], 10);
    const mm = MONTH_MAP[mStr];

    if (mm && day >= 1 && day <= 31 && year >= 1900 && year <= 2100) {
      const dd = String(day).padStart(2, '0');
      return `${dd}/${mm}/${year}`;
    }
  }

  // Pattern 4: YYYY-MM-DD or YYYY/MM/DD
  const m2 = clean.match(/^(\d{4})[/\.-](\d{1,2})[/\.-](\d{1,2})$/);
  if (m2) {
    const year = parseInt(m2[1], 10);
    const month = parseInt(m2[2], 10);
    const day = parseInt(m2[3], 10);

    if (month >= 1 && month <= 12 && day >= 1 && day <= 31 && year >= 1900 && year <= 2100) {
      const dd = String(day).padStart(2, '0');
      const mm = String(month).padStart(2, '0');
      return `${dd}/${mm}/${year}`;
    }
  }

  // Pattern 5: YOB / 4-digit Year
  const m3 = clean.match(/^\d{4}$/);
  if (m3) {
    const year = parseInt(m3[0], 10);
    if (year >= 1900 && year <= new Date().getFullYear()) {
      return m3[0];
    }
  }

  return "Not detected";
}

// Validate Passport Number format (e.g. A1234567 or 7-9 alphanumeric)
export function validatePassportNumber(passStr) {
  if (!passStr || passStr === "Not detected") return "Not detected";
  const clean = passStr.toUpperCase().replace(/[^A-Z0-9]/g, '');

  if (/^[A-Z][0-9]{7,8}$/.test(clean) || /^[A-Z0-9]{7,9}$/.test(clean)) {
    return clean;
  }
  return "Not detected";
}

// Validate Indian Driving Licence Number structure (e.g. TG00420260003084, DL-1420110012345, KA01 20150001234)
export function validateDrivingLicenceNumber(dlStr) {
  if (!dlStr || dlStr === "Not detected") return "Not detected";
  const raw = dlStr.toUpperCase().trim();
  const clean = raw.replace(/[^A-Z0-9]/g, '');

  // 1. Check clean alphanumeric format: 2-letter state code + 11-15 digits
  if (/^[A-Z]{2}[0-9]{11,15}$/.test(clean)) {
    return raw;
  }

  // 2. Check formatted string with hyphens, slashes or spaces
  const formattedMatch = raw.match(/\b([A-Z]{2}[- /]?[0-9]{2,4}[- /]?[0-9]{4}[- /]?[0-9]{4,8})\b/);
  if (formattedMatch) {
    const candidateClean = formattedMatch[0].replace(/[^A-Z0-9]/g, '');
    if (candidateClean.length >= 13 && candidateClean.length <= 17) {
      return formattedMatch[0];
    }
  }

  // 3. Fallback check for DL- prefixed numbers
  const dlPrefixMatch = raw.match(/\b(DL[- /]?[0-9]{11,15})\b/);
  if (dlPrefixMatch) {
    return dlPrefixMatch[0];
  }

  return "Not detected";
}

// Validate Aadhaar 12-digit or Voter ID format
export function validateNationalIdNumber(idStr) {
  if (!idStr || idStr === "Not detected") return "Not detected";
  const clean = idStr.trim();

  // Aadhaar 12-digit
  const aadhaarMatch = clean.match(/\b\d{4}\s?\d{4}\s?\d{4}\b/);
  if (aadhaarMatch) {
    return aadhaarMatch[0];
  }

  // Voter ID: 3 letters + 7 digits
  const voterMatch = clean.toUpperCase().match(/\b[A-Z]{3}\d{7}\b/);
  if (voterMatch) {
    return voterMatch[0];
  }

  return "Not detected";
}

// Validate PAN Card number (5 letters + 4 digits + 1 letter)
export function validatePANNumber(panStr) {
  if (!panStr || panStr === "Not detected") return "Not detected";
  const clean = panStr.toUpperCase().replace(/[^A-Z0-9]/g, '');
  if (/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(clean)) {
    return clean;
  }
  return "Not detected";
}

// Validate Voter ID (EPIC) number (3 letters + 7 digits)
export function validateVoterIdNumber(voterStr) {
  if (!voterStr || voterStr === "Not detected") return "Not detected";
  const clean = voterStr.toUpperCase().replace(/[^A-Z0-9]/g, '');
  if (/^[A-Z]{3}[0-9]{7}$/.test(clean)) {
    return clean;
  }
  return "Not detected";
}

// ICAO 9303 Modulo 10 Check Digit Calculation (Weighting 7, 3, 1)
export function calculateICAOCheckDigit(str) {
  if (!str) return 0;
  const weights = [7, 3, 1];
  let sum = 0;

  for (let i = 0; i < str.length; i++) {
    const char = str[i].toUpperCase();
    let val = 0;

    if (char >= '0' && char <= '9') {
      val = char.charCodeAt(0) - '0'.charCodeAt(0);
    } else if (char >= 'A' && char <= 'Z') {
      val = char.charCodeAt(0) - 'A'.charCodeAt(0) + 10;
    } else if (char === '<') {
      val = 0;
    } else {
      val = 0;
    }

    sum += val * weights[i % 3];
  }

  return sum % 10;
}

/**
 * Optical Error Repair for ICAO Doc 9303 MRZ Lines.
 * Automatically resolves common character confusions between letters and digits.
 */
export function repairMRZLine(rawLine, isLine1, mrzType = 'TD3') {
  if (!rawLine) return "";
  
  // Clean fillers: convert common OCR misreads of '<'
  let line = rawLine.toUpperCase()
    .replace(/[«\(\{\[\|]/g, '<')
    .replace(/\s+/g, '<')
    .replace(/[^A-Z0-9<]/g, '<');

  const toDigit = (c) => {
    if (c === 'O' || c === 'D' || c === 'Q') return '0';
    if (c === 'I' || c === 'L' || c === 'J') return '1';
    if (c === 'Z') return '2';
    if (c === 'S') return '5';
    if (c === 'B') return '8';
    return c;
  };

  const toLetter = (c) => {
    if (c === '0') return 'O';
    if (c === '1') return 'I';
    if (c === '2') return 'Z';
    if (c === '5') return 'S';
    if (c === '8') return 'B';
    return c;
  };

  if (mrzType === 'TD3' && line.length >= 35) {
    const chars = line.split('');

    if (isLine1) {
      // Line 1: P<COUNTRY_SURNAME<<GIVEN_NAMES<<<<<
      if (chars[0] !== 'P' && chars[0] !== 'V') chars[0] = 'P';
      chars[1] = '<';
      // Chars 2-4: Country Code (must be letters)
      for (let i = 2; i <= 4; i++) {
        if (i < chars.length && chars[i] !== '<') chars[i] = toLetter(chars[i]);
      }
      // Chars 5+: Names and Fillers (must be letters or <)
      for (let i = 5; i < chars.length; i++) {
        if (chars[i] !== '<') chars[i] = toLetter(chars[i]);
      }
    } else {
      // Line 2: DOC_NO(9) + CHECK(1) + NAT(3) + DOB(6) + CHECK(1) + SEX(1) + EXP(6) + CHECK(1) + ...
      // Char 9: Passport Check Digit (MUST BE DIGIT)
      if (chars.length > 9 && chars[9] !== '<') chars[9] = toDigit(chars[9]);

      // Chars 10-12: Nationality (MUST BE LETTERS)
      for (let i = 10; i <= 12; i++) {
        if (i < chars.length && chars[i] !== '<') chars[i] = toLetter(chars[i]);
      }

      // Chars 13-18: Date of Birth YYMMDD (MUST BE DIGITS)
      for (let i = 13; i <= 18; i++) {
        if (i < chars.length && chars[i] !== '<') chars[i] = toDigit(chars[i]);
      }

      // Char 19: DOB Check Digit (MUST BE DIGIT)
      if (chars.length > 19 && chars[19] !== '<') chars[19] = toDigit(chars[19]);

      // Char 20: Sex (M, F, or <)
      if (chars.length > 20) {
        if (chars[20] === 'H' || chars[20] === 'N') chars[20] = 'M';
        if (chars[20] === 'E' || chars[20] === 'P') chars[20] = 'F';
      }

      // Chars 21-26: Expiry Date YYMMDD (MUST BE DIGITS)
      for (let i = 21; i <= 26; i++) {
        if (i < chars.length && chars[i] !== '<') chars[i] = toDigit(chars[i]);
      }

      // Char 27: Expiry Check Digit (MUST BE DIGIT)
      if (chars.length > 27 && chars[27] !== '<') chars[27] = toDigit(chars[27]);

      // Char 43: Final Composite Check Digit (MUST BE DIGIT)
      if (chars.length > 43 && chars[43] !== '<') chars[43] = toDigit(chars[43]);
    }

    return chars.join('');
  }

  return line;
}

// Validate MRZ TD3 Checksums with auto-repair
export function validateMRZ(line1, line2) {
  if (!line1 || !line2) {
    return { isValid: false, reason: "MRZ lines missing" };
  }

  const cleanL1 = repairMRZLine(line1, true, 'TD3');
  const cleanL2 = repairMRZLine(line2, false, 'TD3');

  if (cleanL2.length < 28) {
    return { isValid: false, reason: "MRZ line 2 too short" };
  }

  try {
    // Passport No check digit (chars 0-8, check digit at char 9)
    const passNo = cleanL2.substring(0, 9);
    const passCheck = parseInt(cleanL2.charAt(9), 10);
    const calcPassCheck = calculateICAOCheckDigit(passNo);

    // DOB check digit (chars 13-18, check digit at char 19)
    const dob = cleanL2.substring(13, 19);
    const dobCheck = parseInt(cleanL2.charAt(19), 10);
    const calcDobCheck = calculateICAOCheckDigit(dob);

    // Expiry check digit (chars 21-26, check digit at char 27)
    const exp = cleanL2.substring(21, 27);
    const expCheck = parseInt(cleanL2.charAt(27), 10);
    const calcExpCheck = calculateICAOCheckDigit(exp);

    const passValid = isNaN(passCheck) || passCheck === calcPassCheck;
    const dobValid = isNaN(dobCheck) || dobCheck === calcDobCheck;
    const expValid = isNaN(expCheck) || expCheck === calcExpCheck;

    const isValid = passValid && dobValid && expValid;

    return {
      isValid,
      passValid,
      dobValid,
      expValid,
      repairedLine1: cleanL1,
      repairedLine2: cleanL2,
      reason: isValid ? "ICAO TD3 Checksums Valid" : "MRZ Checksum Mismatch"
    };
  } catch (err) {
    return { isValid: false, reason: "MRZ Parsing Failed" };
  }
}

// Security Masking for sensitive numbers in logging
export function maskSensitiveNumber(str) {
  if (!str || str === "Not detected") return "Not detected";
  if (str.length <= 4) return "****";
  const start = str.substring(0, 2);
  const end = str.substring(str.length - 2);
  return `${start}${'X'.repeat(str.length - 4)}${end}`;
}

// =========================================================
// VERHOEFF CHECKSUM ALGORITHM (Aadhaar / UIDAI)
// =========================================================

const _VERHOEFF_D = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
  [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
  [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
  [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
  [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
  [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
  [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
  [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
  [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
  [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
];

const _VERHOEFF_P = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
  [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
  [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
  [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
  [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
  [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
  [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
  [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]
];

export function validateVerhoeff(str) {
  const digits = String(str || '').replace(/\D/g, '');
  if (!digits || digits.length !== 12) return false;
  if (digits[0] === '0' || digits[0] === '1') return false;
  let c = 0;
  const rev = digits.split('').reverse().map(Number);
  for (let i = 0; i < rev.length; i++) {
    c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][rev[i]]];
  }
  return c === 0;
}

// =========================================================
// LIGHTWEIGHT MODULE 2 VALIDATION ENGINE (< 1ms execution)
// =========================================================

export function validateDocumentModule2(docType, fields = {}, rawText = '', qrResult = null) {
  const checksumResults = {};
  const missingRequired = [];
  const formatErrors = [];
  const dateErrors = [];

  const normType = (docType || '').toLowerCase();
  const carriesExpiry = normType.includes('passport') || normType.includes('driving') || normType.includes('visa');

  // 1. Required Fields check per document standard
  if (normType.includes('pan')) {
    const pan = fields['PAN Number'] || fields['ID Number'];
    const name = fields['Name'] || fields['Full Name'] || fields['Holder Name'];
    if (!pan || pan === 'Not detected') missingRequired.push('PAN Number');
    if (!name || name === 'Not detected') missingRequired.push('Name');
    
    // PAN Format
    if (pan && pan !== 'Not detected') {
      const cleanPan = pan.replace(/[^A-Z0-9]/g, '');
      const valid = /^[A-Z]{5}[0-9]{4}[A-Z]$/.test(cleanPan);
      checksumResults.pan_format_valid = valid;
      if (!valid) formatErrors.push(`PAN format invalid: ${pan}`);

      // 5th character represents cardholder's surname initial
      if (cleanPan.length >= 5 && name && name !== 'Not detected') {
        const nameTokens = name.trim().toUpperCase().split(/\s+/).filter(Boolean);
        const surname = nameTokens.length > 1 ? nameTokens[nameTokens.length - 1] : nameTokens[0];
        const surnameInitial = surname ? surname[0] : '';
        const fifthChar = cleanPan[4];
        const surnameMatches = (fifthChar === surnameInitial);
        checksumResults.pan_surname_match = surnameMatches;
        if (!surnameMatches && surnameInitial) {
          formatErrors.push(`PAN 5th-character '${fifthChar}' does not match cardholder surname initial '${surnameInitial}' (${surname})`);
        }
      }
    }
  } else if (normType.includes('aadhaar')) {
    const aadhaar = fields['Aadhaar Number'] || fields['ID Number'];
    const name = fields['Name'] || fields['Full Name'] || fields['Holder Name'];
    if (!aadhaar || aadhaar === 'Not detected') missingRequired.push('Aadhaar Number');
    if (!name || name === 'Not detected') missingRequired.push('Name');

    // Aadhaar Verhoeff & length
    if (aadhaar && aadhaar !== 'Not detected') {
      const cleanAadhaar = aadhaar.replace(/\D/g, '');
      const formatValid = cleanAadhaar.length === 12 && cleanAadhaar[0] !== '0' && cleanAadhaar[0] !== '1';
      const verhoeffValid = validateVerhoeff(cleanAadhaar);
      checksumResults.aadhaar_format_valid = formatValid;
      checksumResults.aadhaar_verhoeff_valid = verhoeffValid;
      checksumResults.aadhaar_checksum_valid = verhoeffValid;
      if (!formatValid) formatErrors.push('Aadhaar must be 12 digits not starting with 0 or 1');
      if (!verhoeffValid) formatErrors.push('Aadhaar Verhoeff checksum validation failed');
    }

    // UIDAI QR verification
    checksumResults.uidai_qr_verified = qrResult ? (qrResult.overall_qr_ocr_match !== false && qrResult.qr_ocr_match !== false) : true;
    checksumResults.qr_verification = checksumResults.uidai_qr_verified;
  } else if (normType.includes('voter')) {
    const epic = fields['Voter ID Number'] || fields['EPIC / Voter ID Number'] || fields['EPIC Number'] || fields['ID Number'] || fields['Document Number'];
    const name = fields['Name'] || fields['Full Name'] || fields['Holder Name'];
    if (!epic || epic === 'Not detected') missingRequired.push('Voter ID Number');
    if (!name || name === 'Not detected') missingRequired.push('Name');

    if (epic && epic !== 'Not detected') {
      const cleanEpic = epic.replace(/[^A-Z0-9]/g, '');
      const valid = /^[A-Z]{3}[0-9]{7}$/.test(cleanEpic);
      checksumResults.epic_format_valid = valid;
      if (!valid) formatErrors.push(`EPIC format invalid: ${epic}`);
    }
  } else if (normType.includes('passport')) {
    const pass = fields['Passport Number'] || fields['ID Number'] || fields['Document Number'];
    const name = fields['Name'] || fields['Full Name'] || fields['Holder Name'];
    const nat = fields['Nationality'] || fields['nationality'];
    if (!pass || pass === 'Not detected') missingRequired.push('Passport Number');
    if (!name || name === 'Not detected') missingRequired.push('Name');

    if (pass && pass !== 'Not detected') {
      const cleanPass = pass.replace(/[^A-Z0-9]/g, '');
      const valid = /^[A-Z][0-9]{7,8}$/.test(cleanPass) || /^[A-Z0-9]{7,9}$/.test(cleanPass);
      checksumResults.passport_format_valid = valid;
      if (!valid) formatErrors.push(`Passport format invalid: ${pass}`);

      // Country-specific format validation from country_formats.json
      if (nat && nat !== 'Not detected') {
        const cCheck = validateCountryFormat('passport', cleanPass, nat);
        if (cCheck) {
          checksumResults[`${cCheck.country_code.toLowerCase()}_passport_format`] = cCheck.is_valid;
          if (!cCheck.is_valid) {
            formatErrors.push(`Passport number ${pass} does not match ${cCheck.country_name} format pattern (${cCheck.pattern})`);
          }
        }
      }
    }
  } else if (normType.includes('visa')) {
    const visaNo = fields['Visa Number'] || fields['ID Number'] || fields['Document Number'];
    const name = fields['Name'] || fields['Full Name'] || fields['Holder Name'];
    const nat = fields['Nationality'] || fields['Issuing Country'] || fields['nationality'];
    if (!visaNo || visaNo === 'Not detected') missingRequired.push('Visa Number');
    if (!name || name === 'Not detected') missingRequired.push('Name');

    if (visaNo && visaNo !== 'Not detected') {
      const cleanVisa = visaNo.replace(/[^A-Z0-9]/g, '');
      const valid = /^[A-Z0-9]{6,16}$/.test(cleanVisa);
      checksumResults.visa_format_valid = valid;
      if (!valid) formatErrors.push(`Visa format invalid: ${visaNo}`);

      if (nat && nat !== 'Not detected') {
        const cCheck = validateCountryFormat('visa', cleanVisa, nat);
        if (cCheck) {
          checksumResults[`${cCheck.country_code.toLowerCase()}_visa_format`] = cCheck.is_valid;
          if (!cCheck.is_valid) {
            formatErrors.push(`Visa number ${visaNo} does not match ${cCheck.country_name} format pattern (${cCheck.pattern})`);
          }
        }
      }
    }
  } else if (normType.includes('driving')) {
    const dl = fields['Driving Licence Number'] || fields['Licence Number'] || fields['License Number'] || fields['ID Number'] || fields['Document Number'];
    const name = fields['Name'] || fields['Full Name'] || fields['Holder Name'];
    if (!dl || dl === 'Not detected') missingRequired.push('Driving Licence Number');
    if (!name || name === 'Not detected') missingRequired.push('Name');

    if (dl && dl !== 'Not detected') {
      const cleanDl = dl.replace(/[^A-Z0-9]/g, '');
      const valid = cleanDl.length >= 12 && /^[A-Z]{2}[0-9]/.test(cleanDl);
      checksumResults.dl_format_valid = valid;
      if (!valid) formatErrors.push(`Driving licence format invalid: ${dl}`);
    }
  }

  // 2. Date consistency checks
  const dob = fields['Date of Birth'] || fields['DOB'];
  if (dob && dob !== 'Not detected' && dob !== 'not applicable for this document type') {
    const parts = dob.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (parts) {
      const year = parseInt(parts[3], 10);
      const currentYear = new Date().getFullYear();
      if (year > currentYear) dateErrors.push(`Date of Birth in the future: ${dob}`);
      if (year < 1900) dateErrors.push(`Date of Birth unrealistically old: ${dob}`);
    }
  }

  // Only validate expiry for documents that carry expiry
  if (carriesExpiry) {
    const expiry = fields['Date of Expiry'] || fields['Expiry Date'] || fields['Valid Till'] || fields['Validity (NT)'] || fields['valid_until'];
    if (expiry && expiry !== 'Not detected' && expiry !== 'not applicable for this document type') {
      let expDate = null;
      const dmy = String(expiry).trim().match(/^(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})$/);
      if (dmy) {
        const day = parseInt(dmy[1], 10);
        const month = parseInt(dmy[2], 10) - 1;
        const year = parseInt(dmy[3], 10);
        expDate = new Date(year, month, day);
      } else {
        const ymd = String(expiry).trim().match(/^(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})$/);
        if (ymd) {
          const year = parseInt(ymd[1], 10);
          const month = parseInt(ymd[2], 10) - 1;
          const day = parseInt(ymd[3], 10);
          expDate = new Date(year, month, day);
        }
      }

      if (expDate && !isNaN(expDate.getTime())) {
        const isExpired = expDate < new Date();
        checksumResults.document_expired = isExpired;
        if (isExpired) {
          dateErrors.push(`Document has expired on ${expiry}`);
        }
      }
    }
  }

  // 3. QR code cross-validation checks (Tampering Signal)
  if (qrResult && (qrResult.overall_qr_ocr_match === false || qrResult.qr_ocr_match === false)) {
    checksumResults.qr_tampering_detected = true;
    checksumResults.qr_match_valid = false;
    formatErrors.push('Tampering signal: QR payload does not match printed document data');
  } else if (qrResult && (qrResult.overall_qr_ocr_match === true || qrResult.qr_ocr_match === true)) {
    checksumResults.qr_tampering_detected = false;
    checksumResults.qr_match_valid = true;
  }

  const isValid = missingRequired.length === 0 && formatErrors.length === 0 && dateErrors.length === 0;

  return {
    validation_passed: isValid,
    checksum_validation: checksumResults,
    missing_required: missingRequired,
    format_errors: formatErrors,
    date_errors: dateErrors
  };
}
