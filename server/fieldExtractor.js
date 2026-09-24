// server/fieldExtractor.js

import {
  sanitizePersonName,
  sanitizeRelativeName,
  sanitizeAddress,
  sanitizePlace
} from './nameAddressSanitizer.js';

// =========================================================
// BASIC HELPERS
// =========================================================

function cleanText(value) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .replace(/[|]+/g, ' ')
    .trim();
}

function normalize(value) {
  return cleanText(value).toUpperCase();
}

function isValidValue(value) {
  if (!value) return false;

  const text = cleanText(value);

  if (text.length < 2) {
    return false;
  }

  if (/^[^A-Z0-9]+$/i.test(text)) {
    return false;
  }

  return true;
}

// =========================================================
// BOUNDING BOX HELPERS
// =========================================================

function center(box) {
  return {
    x: (box.x0 + box.x1) / 2,
    y: (box.y0 + box.y1) / 2
  };
}

function isSameLine(a, b) {
  if (!a?.bbox || !b?.bbox) {
    return false;
  }

  const ay = center(a.bbox).y;
  const by = center(b.bbox).y;

  return Math.abs(ay - by) < 25;
}

// =========================================================
// FIND LABEL
// =========================================================

function findLabel(words, labels) {
  const wanted = labels.map(label => normalize(label));

  // Single word match (require exact match or meaningful boundary match)
  for (const word of words) {
    const text = normalize(word.text);
    if (!text || text.length < 3) continue;

    for (const label of wanted) {
      if (text === label) {
        return word;
      }
      const labelWords = label.split(/\s+/);
      if (labelWords.includes(text) && text.length >= 4) {
        return word;
      }
      if (text.startsWith(label) && label.length >= 4) {
        return word;
      }
    }
  }

  // Multi-word label match
  for (let i = 0; i < words.length; i++) {
    if (!words[i]?.bbox) continue;

    const first = normalize(words[i].text);
    if (!first || first.length < 2) continue;

    for (let j = i + 1; j < Math.min(i + 4, words.length); j++) {
      if (!isSameLine(words[i], words[j])) continue;

      const combined = `${first} ${normalize(words[j].text)}`;
      for (const label of wanted) {
        if (combined === label || (combined.startsWith(label) && label.length >= 4)) {
          return words[i];
        }
      }
    }
  }

  return null;
}

// =========================================================
// EXTRACT VALUE FROM SAME LINE
// =========================================================

function extractSameLineValue(
  words,
  labels
) {

  const labelWord =
    findLabel(words, labels);

  if (!labelWord?.bbox) {
    return '';
  }

  const candidates =
    words
      .filter(word => {

        if (!word?.bbox) {
          return false;
        }

        if (word === labelWord) {
          return false;
        }

        if (
          !isSameLine(
            labelWord,
            word
          )
        ) {
          return false;
        }

        return (
          word.bbox.x0 >=
          labelWord.bbox.x1 - 5
        );
      })
      .sort(
        (a, b) =>
          a.bbox.x0 -
          b.bbox.x0
      );

  if (candidates.length === 0) {
    return '';
  }

  return cleanText(
    candidates
      .slice(0, 5)
      .map(word => word.text)
      .join(' ')
  );
}

// =========================================================
// REGEX EXTRACTION
// =========================================================

function extractPattern(
  text,
  patterns
) {

  for (const pattern of patterns) {

    const match =
      text.match(pattern);

    if (match?.[1]) {
      return cleanText(
        match[1]
      );
    }

    if (match?.[0]) {
      return cleanText(
        match[0]
      );
    }
  }

  return '';
}

// =========================================================
// FIND EXACT 12-DIGIT NUMBER
// =========================================================

function find12DigitNumber(text) {

  if (!text) {
    return '';
  }

  // Only accept clearly separated 4-4-4
  // numbers already present in OCR.
  const spacedMatches =
    text.match(
      /\b\d{4}\s+\d{4}\s+\d{4}\b/g
    ) || [];

  if (spacedMatches.length > 0) {
    return spacedMatches[0];
  }

  // Only accept an actual continuous 12-digit number.
  const continuousMatches =
    text.match(
      /\b\d{12}\b/g
    ) || [];

  if (continuousMatches.length > 0) {

    const value =
      continuousMatches[0];

    return (
      value.slice(0, 4) +
      ' ' +
      value.slice(4, 8) +
      ' ' +
      value.slice(8, 12)
    );
  }

  // IMPORTANT:
  // Do NOT join every number in the OCR text.
  return '';
}

// =========================================================
// UNIVERSAL FIELD EXTRACTION
// =========================================================

function extractUniversalFields(
  words = [],
  rawText = ''
) {

  if (!Array.isArray(words)) {
    words = [];
  }

  const text =
    cleanText(rawText);

  const fields = {};

  // =======================================================
  // FULL NAME
  // =======================================================

  let name =
    extractSameLineValue(
      words,
      [
        'FULL NAME',
        'APPLICANT NAME',
        'HOLDER NAME',
        'ELECTOR NAME'
      ]
    );

  // If specific labels didn't find a name, try bare 'NAME' but exclude
  // lines containing parent/guardian labels to avoid FATHER'S NAME etc.
  if (!name) {
    const nameWord = findLabel(words, ['NAME']);
    if (nameWord?.bbox) {
      // Check the label context — skip if the surrounding text has FATHER/MOTHER/HUSBAND
      const nearbyText = words
        .filter(w => w?.bbox && Math.abs(center(w.bbox).y - center(nameWord.bbox).y) < 25)
        .map(w => cleanText(w.text).toUpperCase())
        .join(' ');
      const parentLabels = /FATHER|MOTHER|HUSBAND|GUARDIAN|S\/O|D\/O|W\/O|SPOUSE/;
      if (!parentLabels.test(nearbyText)) {
        name = extractSameLineValue(words, ['NAME']);
      }
    }
  }
  // Strip bleed-through: dates, field labels, pure digits
  if (name) {
    name = name
      .replace(/\s*\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}.*$/i, '')
      .replace(/\s*\b(DOB|DATE|BIRTH|GENDER|SEX|MALE|FEMALE|SIGNATURE|\d{4,})\b.*$/i, '')
      .trim();
  }

  if (!name) {

    name =
      extractPattern(
        text,
        [
          /NAME\s*[:\-]?\s*([A-Z][A-Z ]{2,40})(?=\s+(?:DOB|DATE OF BIRTH))/i,
          /(?:FULL\s+)?NAME\s*[:\-]\s*([A-Z][A-Z .'-]{2,40})/i
        ]
      );
  }

  if (name) {
    const sanitized = sanitizePersonName(name);
    if (sanitized !== 'Not detected') {
      fields['Full Name'] = sanitized;
    }
  }

  // =======================================================
  // DOB
  // =======================================================

  let dob =
    extractPattern(
      text,
      [
        /(?:DOB|DATE OF BIRTH|BIRTH DATE)\s*[:\-]?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})/i,

        /(?:DOB|DATE OF BIRTH|BIRTH DATE)[^\d]*(\d{1,2}\s+\d{1,2}\s+\d{4})/i
      ]
    );

  if (!dob) {
    // Only use first-date-in-document if it appears near a DOB-related keyword
    const dobContextMatch = text.match(
      /(?:DOB|DATE\s*(?:OF)?\s*BIRTH|BIRTH\s*DATE|BORN|YOB)[^\d]{0,30}(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})/i
    );
    if (dobContextMatch) {
      dob = dobContextMatch[1];
    }
  }

  if (isValidValue(dob)) {

    fields['Date of Birth'] =
      dob;
  }

  // =======================================================
  // GENDER
  // =======================================================

  const upperText =
    normalize(text);

  // Priority 1: Contextual label match (GENDER: MALE, SEX: FEMALE)
  const genderCtx = upperText.match(/(?:GENDER|SEX)\s*[:\-]?\s*(FEMALE|MALE|TRANSGENDER)/i);
  if (genderCtx) {
    const g = genderCtx[1].toUpperCase();
    fields['Gender'] = g === 'FEMALE' ? 'Female' : (g === 'MALE' ? 'Male' : 'Transgender');
  } else if (
    /\bFEMALE\b/.test(upperText)
  ) {
    fields['Gender'] = 'Female';
  } else if (
    /\bMALE\b/.test(upperText)
  ) {
    fields['Gender'] = 'Male';
  }

  // =======================================================
  // ADDRESS
  // =======================================================

  let address = '';

  const addressWord =
    findLabel(
      words,
      [
        'ADDRESS',
        'RESIDENTIAL ADDRESS',
        'PERMANENT ADDRESS',
        'PRESENT ADDRESS'
      ]
    );

  if (addressWord?.bbox) {

    const labelCenter =
      center(addressWord.bbox);

    const addressCandidates =
      words
        .filter(word => {

          if (!word?.bbox) {
            return false;
          }

          const wordCenter =
            center(word.bbox);

          const below =
            wordCenter.y >
            labelCenter.y + 10;

          const horizontal =
            word.bbox.x0 <
            addressWord.bbox.x1 + 500;

          return (
            below &&
            horizontal
          );
        })
        .sort((a, b) => {

          const ay =
            center(a.bbox).y;

          const by =
            center(b.bbox).y;

          if (
            Math.abs(ay - by) > 10
          ) {
            return ay - by;
          }

          return (
            a.bbox.x0 -
            b.bbox.x0
          );
        });

    address =
      cleanText(
        addressCandidates
          .slice(0, 30)
          .map(word => word.text)
          .join(' ')
      );
  }

  if (!address) {

    const addressMatch =
      text.match(
        /ADDRESS\s*[:\-]?\s*(.{20,300})/i
      );

    if (addressMatch?.[1]) {

      address =
        cleanText(
          addressMatch[1]
        );
    }
  }

  if (address) {
    const sanitized = sanitizeAddress(address);
    if (sanitized !== 'Not detected') {
      fields['Address'] = sanitized;
    }
  }

  // =======================================================
  // ISSUE DATE
  // =======================================================

  const issueDate =
    extractPattern(
      text,
      [
        /(?:ISSUE DATE|DATE OF ISSUE|ISSUED ON)\s*[:\-]?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})/i
      ]
    );

  if (isValidValue(issueDate)) {

    fields['Issue Date'] =
      issueDate;
  }

  // =======================================================
  // EXPIRY DATE
  // =======================================================

  const expiryDate =
    extractPattern(
      text,
      [
        /(?:EXPIRY DATE|DATE OF EXPIRY|VALID UNTIL|VALID TILL|EXPIRATION DATE)\s*[:\-]?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})/i
      ]
    );

  if (isValidValue(expiryDate)) {

    fields['Expiry Date'] =
      expiryDate;
  }

  // =======================================================
  // NATIONALITY
  // =======================================================

  const nationalityText =
    extractSameLineValue(
      words,
      [
        'NATIONALITY'
      ]
    );

  const nationalityUpper =
    normalize(nationalityText);

  if (/\bINDIA(N)?\b/i.test(nationalityUpper) || nationalityUpper === 'IND') {
    fields['Nationality'] = 'Indian';
  } else if (/\bAMERICAN\b/i.test(nationalityUpper) || nationalityUpper === 'USA' || /\bUNITED\s+STATES\b/i.test(nationalityUpper)) {
    fields['Nationality'] = 'American (USA)';
  } else if (/\bBRITISH\b/i.test(nationalityUpper) || nationalityUpper === 'GBR' || /\bUNITED\s+KINGDOM\b/i.test(nationalityUpper)) {
    fields['Nationality'] = 'British';
  } else if (/\bCANADIAN\b/i.test(nationalityUpper) || nationalityUpper === 'CAN') {
    fields['Nationality'] = 'Canadian';
  } else if (/\bAUSTRALIAN\b/i.test(nationalityUpper) || nationalityUpper === 'AUS') {
    fields['Nationality'] = 'Australian';
  } else if (/\bFRENCH\b/i.test(nationalityUpper) || nationalityUpper === 'FRA') {
    fields['Nationality'] = 'French';
  } else if (/\bGERMAN\b/i.test(nationalityUpper) || nationalityUpper === 'DEU') {
    fields['Nationality'] = 'German';
  } else if (/\bEMIRATI\b/i.test(nationalityUpper) || nationalityUpper === 'ARE' || nationalityUpper === 'UAE') {
    fields['Nationality'] = 'Emirati';
  }

  // =======================================================
  // PARENT NAME
  // =======================================================

  let parent =
    extractPattern(
      text,
      [
        /(?:S\/O|D\/O|W\/O|C\/O)\s*[:\-]?\s*([A-Z][A-Z .]{2,50})/i,

        /FATHER(?: NAME)?\s*[:\-]?\s*([A-Z][A-Z .]{2,50})/i
      ]
    );

  if (parent) {
    const sanitized = sanitizeRelativeName(parent);
    if (sanitized !== 'Not detected') {
      fields['Parent Name'] = sanitized;
    }
  }

  // =======================================================
  // DOCUMENT NUMBER
  // =======================================================

  let documentNumber =
    extractPattern(
      text,
      [
        /(?:DOCUMENT|ID|CARD)\s*(?:NO|NUMBER)\s*[:\-]?\s*([A-Z0-9\-\/]{4,25})/i,

        /(?:LICENSE|LICENCE)\s*(?:NO|NUMBER)\s*[:\-]?\s*([A-Z0-9\-\/]{4,25})/i,

        /(?:PASSPORT)\s*(?:NO|NUMBER)\s*[:\-]?\s*([A-Z0-9]{5,15})/i,

        /(?:PAN)\s*(?:NO|NUMBER)\s*[:\-]?\s*([A-Z0-9]{8,15})/i
      ]
    );

  // -------------------------------------------------------
  // SAFE 4-4-4 FALLBACK
  // -------------------------------------------------------

  if (!documentNumber) {

    documentNumber =
      find12DigitNumber(text);
  }

  // -------------------------------------------------------
  // PAN FALLBACK
  // -------------------------------------------------------

  if (!documentNumber) {

    const panMatch =
      text.match(
        /\b[A-Z]{5}[0-9]{4}[A-Z]\b/
      );

    if (panMatch) {

      documentNumber =
        panMatch[0];
    }
  }

  if (isValidValue(documentNumber)) {

    fields['Document Number'] =
      documentNumber;

    fields['ID Number'] =
      documentNumber;
  }

  // =======================================================
  // ISSUING AUTHORITY
  // =======================================================

  const authority =
    extractPattern(
      text,
      [
        /(?:ISSUING AUTHORITY|ISSUED BY)\s*[:\-]?\s*([A-Z][A-Z .,&]{2,80})/i
      ]
    );

  if (isValidValue(authority)) {

    fields['Issuing Authority'] =
      cleanText(authority);
  }

  // =======================================================
  // LOG
  // =======================================================

  console.log(
    '[Universal Fields]:',
    fields
  );

  return fields;
}

// =========================================================
// EXPORT
// =========================================================

export {
  extractUniversalFields
};