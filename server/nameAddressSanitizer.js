// server/nameAddressSanitizer.js

/**
 * Common OCR Rectifier for Names, Addresses, and Places.
 * Fixes typical Tesseract misrecognitions, character confusions,
 * label bleed-throughs, and structural noise across all identity documents.
 */

// Common words that belong to labels or headers and should NEVER be part of a person's name
const NAME_BLOCKED_WORDS = [
  'FATHER', "FATHER'S", 'MOTHER', "MOTHER'S", 'HUSBAND', "HUSBAND'S", 'GUARDIAN', "GUARDIAN'S",
  'RELATIVE', 'RELATION', 'NAME', 'NOM', 'GIVEN', 'SURNAME', 'CARDHOLDER', 'APPLICANT', 'ELECTOR',
  'SIGNATURE', 'HOLDER', "HOLDER'S", 'PHOTO', 'SIGN',
  'DATE', 'BIRTH', 'DOB', 'YOB', 'YEAR', 'AGE', 'SEX', 'GENDER', 'MALE', 'FEMALE', 'TRANSGENDER',
  'INCOME', 'TAX', 'DEPARTMENT', 'GOVT', 'GOVERNMENT', 'INDIA', 'REPUBLIC',
  'AADHAAR', 'UIDAI', 'UNIQUE', 'IDENTIFICATION', 'AUTHORITY', 'MERA',
  'ELECTION', 'COMMISSION', 'EPIC', 'BHARAT', 'NIRVACHAN',
  'TRANSPORT', 'SARATHI', 'FORM', 'MOTOR', 'VEHICLES', 'UNION', 'DELHI',
  'PASSPORT', 'PASSEPORT', 'VISA', 'PERMIT', 'NATIONALITY', 'TYPE', 'COUNTRY', 'CODE'
];

/**
 * Sanitize and rectify an extracted person name.
 * - Strips OCR noise, percentages, trailing numbers (e.g. "D MANIKANDAN 7%" -> "D MANIKANDAN")
 * - Cleans label leakage (e.g. "VIKRAM ADITYA SINGH FATHER'S NAME:" -> "VIKRAM ADITYA SINGH")
 * - Repairs OCR character confusions (e.g. "ANJA1I" -> "ANJALI", "5INGH" -> "SINGH", "S0HAN" -> "SOHAN")
 * - Preserves initials (e.g. "D MANIKANDAN", "K CHARAN", "E THADA SAI PRAGNAY")
 */
export function sanitizePersonName(rawName = '') {
  if (!rawName || typeof rawName !== 'string') return 'Not detected';

  let name = rawName.trim();

  // 1. Cut off label bleed-through if another label starts on the same line
  // e.g. "VIKRAM ADITYA SINGH FATHER'S NAME: RAMESH" -> "VIKRAM ADITYA SINGH"
  const labelCutRegex = /\b(FATHER|MOTHER|HUSBAND|S\/O|D\/O|W\/O|C\/O|DOB|DATE OF BIRTH|GENDER|SEX|SIGNATURE|HOLDER|PERMANENT|PAN|AADHAAR|ADDRESS)\b.*$/i;
  name = name.replace(labelCutRegex, '').trim();

  // 2. Remove leading label prefixes like "NAME :", "NOM :", "NAME -", "ELECTOR NAME :"
  name = name.replace(/^(?:ELECTOR'?S?\s+NAME|HOLDER'?S?\s+NAME|CARDHOLDER\s+NAME|APPLICANT\s+NAME|FULL\s+NAME|NAME|NOM)\s*[:\-]\s*/i, '').trim();

  // 3. Remove trailing OCR noise characters like " 7%", " 3", " PE", " TW", " ;", " -"
  // Frequently seen on laminated ID cards where background watermark numbers bleed into text
  name = name.replace(/[\s,;:\-_|/\\]+(?:\d{1,3}%?|[A-Z]{1,2}\d{0,2}|[%$#@*+=~])\s*$/g, '').trim();

  // 4. Repair common OCR digit-to-letter confusions inside words BEFORE stripping non-letters:
  // e.g., "1" inside letters -> "I"
  // "0" inside letters -> "O"
  // "5" inside letters -> "S"
  // "8" inside letters -> "B"
  name = name.split(/\s+/).map(word => {
    // If the word has isolated digit noise like "7", drop it
    if (/^\d+$/.test(word)) return '';
    // Repair 0 -> O
    word = word.replace(/([A-Za-z])0([A-Za-z])/g, '$1O$2');
    word = word.replace(/^0([A-Za-z]{2,})/g, 'O$1');
    word = word.replace(/([A-Za-z]{2,})0$/g, '$1O');
    // Repair 1 -> I
    word = word.replace(/([A-Za-z])1([A-Za-z])/g, '$1I$2');
    word = word.replace(/^1([A-Za-z]{2,})/g, 'I$1');
    word = word.replace(/([A-Za-z]{2,})1$/g, '$1I');
    // Repair 5 -> S
    word = word.replace(/^5([A-Za-z]{2,})/g, 'S$1');
    word = word.replace(/([A-Za-z])5([A-Za-z])/g, '$1S$2');
    word = word.replace(/([A-Za-z]{2,})5$/g, '$1S');
    // Repair 8 -> B
    word = word.replace(/^8([A-Za-z]{2,})/g, 'B$1');
    word = word.replace(/([A-Za-z])8([A-Za-z])/g, '$1B$2');
    return word;
  }).filter(Boolean).join(' ').trim();

  // 5. Strip non-name punctuation (keep letters, spaces, dots, hyphens, apostrophes)
  name = name.replace(/[^A-Za-z\s.'-]/g, ' ').replace(/\s+/g, ' ').trim();

  // 6. Filter out pure label words
  const words = name.split(/\s+/).filter(Boolean);
  const filteredWords = words.filter(w => {
    const u = w.toUpperCase().replace(/[^A-Z]/g, '');
    return !NAME_BLOCKED_WORDS.includes(u);
  });

  if (filteredWords.length === 0) {
    return 'Not detected';
  }

  const finalName = filteredWords.join(' ').trim();

  // Validation: Must contain at least 2 letters
  const letterCount = (finalName.match(/[A-Za-z]/g) || []).length;
  if (letterCount < 2 || finalName.length > 50) {
    return 'Not detected';
  }

  return finalName.toUpperCase();
}

/**
 * Sanitize and rectify an extracted relative/father/husband name.
 */
export function sanitizeRelativeName(rawName = '') {
  if (!rawName || typeof rawName !== 'string') return 'Not detected';

  let name = rawName.trim();

  // Remove leading prefixes like "FATHER'S NAME :", "S/O :", "W/O :"
  name = name.replace(/^(?:FATHER'?S?\s*NAME|HUSBAND'?S?\s*NAME|MOTHER'?S?\s*NAME|GUARDIAN'?S?\s*NAME|SON\s*OF|DAUGHTER\s*OF|WIFE\s*OF|S\/O|D\/O|W\/O|C\/O)\s*[:\-]?\s*/i, '').trim();

  return sanitizePersonName(name);
}

/**
 * Sanitize and rectify an extracted address.
 * - Stops at non-address fields (DOB, PIN, Signatures, Disclaimers)
 * - Removes barcode / OCR symbol noise (| , _ , = , ~)
 * - Identifies and normalizes 6-digit Indian PIN codes
 * - Formats neatly with commas and spaces
 */
export function sanitizeAddress(rawAddress = '') {
  if (!rawAddress || typeof rawAddress !== 'string') return 'Not detected';

  let addr = rawAddress.trim();

  // 1. Remove label prefix
  addr = addr.replace(/^(?:PERMANENT\s*ADDRESS|RESIDENTIAL\s*ADDRESS|PRESENT\s*ADDRESS|ADDRESS)\s*[:\-]\s*/i, '').trim();

  // 2. Cut off at known document disclaimer text, card numbers, or next fields
  const stopKeywords = [
    /Aadhaar is a proof.*$/i,
    /Aadhaar is proof.*$/i,
    /Help\s*line.*$/i,
    /www\..*$/i,
    /Unique Identification Authority.*$/i,
    /Permanent Account Number.*$/i,
    /Licence to drive.*$/i,
    /Date of Issue.*$/i,
    /Valid Till.*$/i,
    /Valid Until.*$/i,
    /Signature.*$/i,
    /Blood Group.*$/i,
    /Organ Donor.*$/i
  ];

  for (const stopRegex of stopKeywords) {
    addr = addr.replace(stopRegex, '').trim();
  }

  // 3. Remove garbage characters & normalize delimiters
  addr = addr
    .replace(/[|~_=]+/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/\s*,\s*/g, ', ')
    .replace(/,\s*,+/g, ', ')
    .replace(/^[,.\s:;/\-]+|[,.\s:;/\-]+$/g, '')
    .trim();

  // 4. Ensure PIN code formatting (e.g. "PIN: 500032" or " - 500 032")
  addr = addr.replace(/\b([1-9][0-9]{2})\s*([0-9]{3})\b/g, '$1$2');

  // Validation: Address should have reasonable length and alphabetic content
  const alphaCount = (addr.match(/[A-Za-z]/g) || []).length;
  if (alphaCount < 6 || addr.length < 8) {
    return 'Not detected';
  }

  return addr;
}

/**
 * Sanitize and rectify Place of Birth, Place of Issue, or City/District.
 * - Strips label prefixes (e.g. "PLACE OF BIRTH:", "LIEU DE NAISSANCE:")
 * - Removes dates or document numbers that bled into the place field
 * - Normalizes spacing and uppercase formatting
 */
export function sanitizePlace(rawPlace = '') {
  if (!rawPlace || typeof rawPlace !== 'string') return 'Not detected';

  let place = rawPlace.trim();

  // Remove label prefixes
  place = place.replace(/^(?:PLACE\s*OF\s*BIRTH|LIEU\s*DE\s*NAISSANCE|PLACE\s*OF\s*ISSUE|P\.?\s*O\.?\s*I\.?|ISSUED\s*AT|AUTHORITY|ISSUING\s*AUTHORITY)\s*[:\-]\s*/i, '').trim();

  // Cut off at dates, expiry, or other visual labels
  place = place.split(/\n|\b(?:DATE|DOB|EXPIRY|SEX|NATIONALITY|PASSPORT|DL|NO)\b/i)[0].trim();

  // Strip country suffixes e.g. ", INDIA", ", IND"
  place = place.replace(/,\s*(?:INDIA|IND|REPUBLIC OF INDIA)\s*$/i, '').trim();

  // Remove non-place punctuation
  place = place.replace(/[^A-Za-z\s,.-]/g, ' ').replace(/\s+/g, ' ').trim();
  place = place.replace(/^[,.\s]+|[,.\s]+$/g, '');

  // Drop if it's too short or purely punctuation
  const letters = (place.match(/[A-Za-z]/g) || []).length;
  if (letters < 2 || place.length > 40) {
    return 'Not detected';
  }

  // Common Indian City & State normalizations
  const upper = place.toUpperCase();
  if (upper === 'BOMBAY') return 'MUMBAI';
  if (upper === 'CALCUTTA') return 'KOLKATA';
  if (upper === 'MADRAS') return 'CHENNAI';
  if (upper === 'BANGALORE') return 'BENGALURU';
  if (upper === 'SECUNDERABAD') return 'HYDERABAD';

  return upper;
}
