/**
 * =========================================================
 * GENERIC DOCUMENT PARSER
 * =========================================================
 *
 * Used for:
 * - PAN Card
 * - Voter ID
 * - Government ID
 * - Unknown Document
 *
 * This parser extracts common fields without assuming
 * a specific document layout.
 */

function clean(value = '') {

  return value
    .replace(/\s+/g, ' ')
    .replace(/[|]+/g, ' ')
    .trim();
}

function upper(value = '') {

  return clean(value)
    .toUpperCase();
}

/**
 * =========================================================
 * DATE EXTRACTION
 * =========================================================
 */

function extractDate(text = '') {

  const match =
    text.match(
      /\b\d{1,2}[\/.-]\d{1,2}[\/.-]\d{4}\b/
    );

  return match
    ? match[0]
    : 'Not detected';
}

/**
 * =========================================================
 * DOCUMENT NUMBER
 * =========================================================
 */

function extractIdNumber(
  fullText,
  documentType
) {

  const text =
    upper(fullText);

  /**
   * PAN
   */

  if (
    documentType === 'PAN Card'
  ) {

    const pan =
      text.match(
        /\b[A-Z]{5}[0-9]{4}[A-Z]\b/
      );

    if (pan) {
      return pan[0];
    }
  }

  /**
   * Voter ID
   */

  if (
    documentType === 'Voter ID'
  ) {

    const voter =
      text.match(
        /\b[A-Z]{3}[0-9]{7}\b/
      );

    if (voter) {
      return voter[0];
    }
  }

  /**
   * Aadhaar fallback
   */

  const aadhaar =
    text.match(
      /\b\d{4}\s?\d{4}\s?\d{4}\b/
    );

  if (aadhaar) {
    return aadhaar[0];
  }

  /**
   * Generic alphanumeric ID.
   */

  const generic =
    text.match(
      /\b[A-Z]{2,5}[-\/]?[0-9]{5,15}\b/
    );

  if (generic) {
    return generic[0];
  }

  return 'Not detected';
}

/**
 * =========================================================
 * NAME
 * =========================================================
 */

function extractName(
  lines = []
) {

  /**
   * Explicit Name label.
   */

  for (
    let i = 0;
    i < lines.length;
    i++
  ) {

    const line =
      clean(lines[i]);

    const match =
      line.match(
        /^NAME\s*[:\-]\s*(.+)$/i
      );

    if (match) {

      const value =
        clean(match[1]);

      if (
        value.length >= 3
      ) {
        return value;
      }
    }

    if (
      upper(line) === 'NAME' &&
      i + 1 < lines.length
    ) {

      const next =
        clean(lines[i + 1]);

      if (
        next.length >= 3 &&
        !/\d/.test(next)
      ) {
        return next;
      }
    }
  }

  /**
   * Generic person-like line.
   */

  const ignored = [
    'GOVERNMENT',
    'GOVT',
    'INDIA',
    'INCOME TAX',
    'ELECTION COMMISSION',
    'IDENTITY',
    'IDENTIFICATION',
    'DATE OF BIRTH',
    'DOB',
    'ADDRESS',
    'SIGNATURE',
    'MALE',
    'FEMALE',
    'PAN CARD',
    'VOTER ID',
    'AADHAAR'
  ];

  for (
    const line of lines
  ) {

    const value =
      clean(line);

    const u =
      upper(value);

    if (
      value.length < 3
    ) {
      continue;
    }

    if (
      /\d/.test(value)
    ) {
      continue;
    }

    if (
      ignored.some(word =>
        u.includes(word)
      )
    ) {
      continue;
    }

    if (
      /^[A-Za-z .'-]+$/.test(value)
    ) {

      const count =
        value.split(/\s+/).length;

      if (
        count >= 1 &&
        count <= 5
      ) {
        return value;
      }
    }
  }

  return 'Not detected';
}

/**
 * =========================================================
 * GENDER
 * =========================================================
 */

function extractGender(
  fullText
) {

  const text =
    upper(fullText);

  if (
    /\bFEMALE\b/.test(text)
  ) {
    return 'Female';
  }

  if (
    /\bMALE\b/.test(text)
  ) {
    return 'Male';
  }

  if (
    /\bTRANSGENDER\b/.test(text)
  ) {
    return 'Transgender';
  }

  return 'Not detected';
}

/**
 * =========================================================
 * NATIONALITY
 * =========================================================
 */

function extractNationality(
  fullText
) {

  const text =
    upper(fullText);

  if (
    text.includes('INDIAN')
  ) {
    return 'Indian';
  }

  return 'Not detected';
}

/**
 * =========================================================
 * ADDRESS
 * =========================================================
 */

function extractAddress(
  lines = []
) {

  for (
    let i = 0;
    i < lines.length;
    i++
  ) {

    const line =
      clean(lines[i]);

    if (
      !upper(line).includes('ADDRESS')
    ) {
      continue;
    }

    const parts = [];

    const first =
      line
        .replace(
          /^.*ADDRESS\s*[:\-]?\s*/i,
          ''
        )
        .trim();

    if (first) {
      parts.push(first);
    }

    for (
      let j = i + 1;
      j < Math.min(i + 8, lines.length);
      j++
    ) {

      const next =
        clean(lines[j]);

      if (!next) {
        continue;
      }

      parts.push(next);

      if (
        /\b\d{6}\b/.test(next)
      ) {
        break;
      }
    }

    if (
      parts.length > 0
    ) {

      return clean(
        parts.join(', ')
      );
    }
  }

  return 'Not detected';
}

/**
 * =========================================================
 * ISSUING AUTHORITY
 * =========================================================
 */

function extractIssuingAuthority(
  fullText
) {

  const text =
    upper(fullText);

  if (
    text.includes('INCOME TAX DEPARTMENT')
  ) {
    return 'Income Tax Department';
  }

  if (
    text.includes('ELECTION COMMISSION')
  ) {
    return 'Election Commission of India';
  }

  if (
    text.includes('UIDAI')
  ) {
    return 'UIDAI';
  }

  if (
    text.includes('GOVERNMENT OF INDIA')
  ) {
    return 'Government of India';
  }

  return 'Not detected';
}

/**
 * =========================================================
 * GENERIC PARSER
 * =========================================================
 */

export function parseGenericDocument(
  words = [],
  lines = [],
  fullText = '',
  documentType = 'Unknown Document'
) {

  const issueDate =
    extractDate(
      lines
        .find(line =>
          /ISSUE DATE|DATE OF ISSUE|DOI/i
            .test(line)
        ) || ''
    );

  const expiryDate =
    extractDate(
      lines
        .find(line =>
          /EXPIRY|EXPIRATION|VALID UNTIL|VALID TILL/i
            .test(line)
        ) || ''
    );

  return {

    'Document Type':
      documentType,

    'Document Number':
      extractIdNumber(
        fullText,
        documentType
      ),

    'Full Name':
      extractName(lines),

    'Date of Birth':
      extractDate(
        lines
          .find(line =>
            /DATE OF BIRTH|DOB|BIRTH/i
              .test(line)
          ) || ''
      ),

    'Gender':
      extractGender(fullText),

    'Nationality':
      extractNationality(fullText),

    'Address':
      extractAddress(lines),

    'Issue Date':
      issueDate,

    'Expiry Date':
      expiryDate,

    'Issuing Authority':
      extractIssuingAuthority(fullText)
  };
}