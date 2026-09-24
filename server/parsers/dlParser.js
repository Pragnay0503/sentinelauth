import {
  validateDrivingLicenceNumber,
  validateDate,
  maskSensitiveNumber
} from '../validators.js';
import {
  sanitizePersonName,
  sanitizeRelativeName,
  sanitizeAddress,
  sanitizePlace
} from '../nameAddressSanitizer.js';

/**
 * =========================================================
 * INDIAN DRIVING LICENCE PARSER
 * =========================================================
 *
 * Extracts:
 * - Licence Number
 * - Full Name
 * - Date of Birth
 * - Issue Date
 * - Validity NT
 * - Validity TR
 * - Class of Vehicle
 * - Son/Daughter/Wife of
 * - State / Issuing Authority
 * - Address
 * - Blood Group
 * - Organ Donor
 *
 * IMPORTANT:
 * This parser does NOT invent values.
 * If a field cannot be confidently extracted,
 * it returns "Not detected".
 */


/**
 * =========================================================
 * HELPERS
 * =========================================================
 */

function clean(value = '') {
  return String(value)
    .replace(/\s+/g, ' ')
    .replace(/[|]+/g, ' ')
    .trim();
}


function upper(value = '') {
  return clean(value).toUpperCase();
}


function isNotDetected(value) {
  return !value || value === 'Not detected';
}


/**
 * Clean OCR noise from names.
 */
function cleanName(value = '') {
  return sanitizePersonName(value);
}


/**
 * Clean person name and keep only sensible words.
 */
function cleanPersonName(value = '') {
  return sanitizePersonName(value);
}


/**
 * Extract date from text.
 */
function extractDate(text = '') {

  const match = text.match(
    /\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})\b/
  );

  if (!match) {
    return 'Not detected';
  }

  const validated = validateDate(match[1]);

  return validated !== 'Not detected'
    ? validated
    : 'Not detected';
}


/**
 * Find all dates.
 */
function extractAllDates(text = '') {

  const matches =
    text.match(
      /\b\d{1,2}[-/.]\d{1,2}[-/.]\d{4}\b/g
    ) || [];

  const result = [];

  for (const date of matches) {

    const validated = validateDate(date);

    if (
      validated !== 'Not detected' &&
      !result.includes(validated)
    ) {
      result.push(validated);
    }
  }

  return result;
}


/**
 * Get words belonging to a particular OCR line.
 */
function wordsOnSameLine(words, targetWord) {

  if (!targetWord) {
    return [];
  }

  return words
    .filter(word => {

      if (!word?.bbox || !targetWord?.bbox) {
        return false;
      }

      const verticalDistance =
        Math.abs(
          word.bbox.y0 - targetWord.bbox.y0
        );

      return verticalDistance <= 35;
    })
    .sort(
      (a, b) =>
        (a.bbox?.x0 || 0) -
        (b.bbox?.x0 || 0)
    );
}


/**
 * Search for a word containing a label.
 */
function findWord(words, labels = []) {

  for (const word of words) {

    const text = upper(word.text);

    for (const label of labels) {

      if (
        text === upper(label) ||
        text.includes(upper(label))
      ) {
        return word;
      }
    }
  }

  return null;
}


/**
 * Extract text to the right of a label.
 */
function textRightOfLabel(words, labels = []) {

  const labelWord =
    findWord(words, labels);

  if (!labelWord) {
    return '';
  }

  const sameLine =
    wordsOnSameLine(words, labelWord);

  const rightWords =
    sameLine.filter(word =>
      (word.bbox?.x0 || 0) >
      (labelWord.bbox?.x1 || 0)
    );

  return clean(
    rightWords
      .map(word => word.text)
      .join(' ')
  );
}


/**
 * Find a line containing a label.
 */
function findLine(lines, labels = []) {

  for (const line of lines) {

    const u = upper(line);

    if (
      labels.some(label =>
        u.includes(upper(label))
      )
    ) {
      return line;
    }
  }

  return '';
}


/**
 * Extract value after colon.
 */
function afterColon(line = '') {

  if (!line.includes(':')) {
    return '';
  }

  return clean(
    line.substring(
      line.indexOf(':') + 1
    )
  );
}


/**
 * =========================================================
 * LICENCE NUMBER
 * =========================================================
 */

function extractLicenceNumber(words, fullText) {

  let value = 'Not detected';
  let confidence = 0;

  const textCandidates = [

    /\b[A-Z]{2}\s*\d{11,16}\b/i,

    /\b[A-Z]{2}[-/\s]?\d{2,4}[-/\s]?\d{4}[-/\s]?\d{4,8}\b/i,

    /\bDL[-/\s]?\d{8,16}\b/i

  ];

  for (const regex of textCandidates) {

    const match =
      fullText.match(regex);

    if (!match) {
      continue;
    }

    const validated =
      validateDrivingLicenceNumber(
        match[0]
      );

    if (validated !== 'Not detected') {

      return {
        value: validated,
        confidence: 90
      };
    }
  }


  for (const word of words) {

    const validated =
      validateDrivingLicenceNumber(
        word.text
      );

    if (
      validated !== 'Not detected'
    ) {

      return {
        value: validated,
        confidence: Math.round(
          word.confidence || 85
        )
      };
    }
  }


  const dlLabel =
    findWord(
      words,
      ['DL', 'DLNO', 'LICENCE']
    );

  if (dlLabel) {

    const sameLine =
      wordsOnSameLine(
        words,
        dlLabel
      );

    for (const word of sameLine) {

      if (
        (word.bbox?.x0 || 0) <=
        (dlLabel.bbox?.x1 || 0)
      ) {
        continue;
      }

      const validated =
        validateDrivingLicenceNumber(
          word.text
        );

      if (
        validated !== 'Not detected'
      ) {

        return {
          value: validated,
          confidence: Math.round(
            word.confidence || 80
          )
        };
      }
    }
  }


  return {
    value,
    confidence
  };
}


/**
 * =========================================================
 * FULL NAME
 * =========================================================
 */

function extractFullName(words, lines) {

  // FIRST: line-based extraction

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const u = upper(line);

    if (
      u.includes('NAME') &&
      !u.includes('SURNAME') &&
      !u.includes('FATHER') &&
      !u.includes('HOLDER') &&
      !u.includes('SIGNATURE')
    ) {

      let candidate = '';

      if (line.includes(':')) {

        candidate =
          afterColon(line);

      } else {

        const index =
          u.indexOf('NAME');

        candidate =
          line.substring(
            index + 4
          ).trim();
      }

      // If candidate on the same line is empty, look at the next line
      if (!candidate || /^[-=~_.:\s]+$/.test(candidate)) {
        if (i + 1 < lines.length) {
          const nextLine = lines[i + 1].trim();
          if (
            !nextLine.match(/^(DOB|DATE|S\/O|D\/O|W\/O|SON|DAUGHTER|WIFE|ADDRESS|VALIDITY|ISSUE|LICENCE|DL|NO|BLOOD|ORGAN)/i) &&
            nextLine.length >= 2
          ) {
            candidate = nextLine;
          }
        }
      }

      // Stop before another field

      candidate =
        candidate.split(
          /DATE OF BIRTH|DOB|ISSUE DATE|VALIDITY|HOLDER|SIGNATURE|BLOOD GROUP|ORGAN DONOR/i
        )[0];


      candidate =
        sanitizePersonName(candidate);


      if (
        candidate !== 'Not detected' &&
        candidate.length >= 2
      ) {

        return {
          value: candidate,
          confidence: 90
        };
      }
    }
  }


  // SECOND: spatial OCR search

  const nameLabel =
    findWord(
      words,
      ['NAME']
    );

  if (nameLabel) {

    const sameLine =
      wordsOnSameLine(
        words,
        nameLabel
      );

    const candidates =
      sameLine
        .filter(word => {

          if (
            (word.bbox?.x0 || 0) <=
            (nameLabel.bbox?.x1 || 0)
          ) {
            return false;
          }

          const t =
            upper(word.text);

          return (
            !t.includes('HOLDER') &&
            !t.includes('SIGNATURE') &&
            !t.includes('DATE') &&
            !t.includes('BIRTH')
          );
        })
        .map(word => word.text);


    if (candidates.length > 0) {

      const candidate =
        cleanPersonName(
          candidates.join(' ')
        );

      if (
        candidate.length >= 3
      ) {

        return {
          value: candidate,
          confidence: 80
        };
      }
    }
  }


  return {
    value: 'Not detected',
    confidence: 0
  };
}


/**
 * =========================================================
 * DATE OF BIRTH
 * =========================================================
 */

function extractDob(
  lines,
  words,
  fullText
) {

  for (const line of lines) {

    const u = upper(line);

    if (
      u.includes('DATE OF BIRTH') ||
      u.includes('DOB') ||
      u.includes('BIRTH')
    ) {

      const date =
        extractDate(line);

      if (
        date !== 'Not detected'
      ) {

        return {
          value: date,
          confidence: 90
        };
      }
    }
  }


  const label =
    findWord(
      words,
      ['DOB', 'BIRTH']
    );

  if (label) {

    const sameLine =
      wordsOnSameLine(
        words,
        label
      );

    for (const word of sameLine) {

      const date =
        extractDate(word.text);

      if (
        date !== 'Not detected'
      ) {

        return {
          value: date,
          confidence: Math.round(
            word.confidence || 85
          )
        };
      }
    }
  }


  const dobContext =
    fullText.match(
      /(?:DATE\s*OF\s*BIRTH|DOB|BIRTH)[^0-9]{0,40}(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})/i
    );

  if (dobContext) {

    const date =
      validateDate(
        dobContext[1]
      );

    if (
      date !== 'Not detected'
    ) {

      return {
        value: date,
        confidence: 85
      };
    }
  }


  return {
    value: 'Not detected',
    confidence: 0
  };
}


/**
 * =========================================================
 * ISSUE DATE
 * =========================================================
 */

function extractIssueDate(
  lines,
  words,
  fullText,
  dob
) {

  for (const line of lines) {

    const u = upper(line);

    if (
      (
        u.includes('ISSUE DATE') ||
        u.includes('DATE OF ISSUE') ||
        /\bDOI\b/.test(u)
      ) &&
      !u.includes('ISSUED BY')
    ) {

      const date =
        extractDate(line);

      if (
        date !== 'Not detected' &&
        date !== dob
      ) {

        return date;
      }
    }
  }


  const label =
    findWord(
      words,
      ['ISSUE', 'DOI']
    );

  if (label) {

    const sameLine =
      wordsOnSameLine(
        words,
        label
      );

    for (const word of sameLine) {

      const date =
        extractDate(word.text);

      if (
        date !== 'Not detected' &&
        date !== dob
      ) {

        return date;
      }
    }
  }


  const context =
    fullText.match(
      /(?:ISSUE\s*DATE|DATE\s*OF\s*ISSUE|DOI)[^0-9]{0,40}(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})/i
    );

  if (context) {

    const date =
      validateDate(
        context[1]
      );

    if (
      date !== 'Not detected' &&
      date !== dob
    ) {

      return date;
    }
  }


  return 'Not detected';
}


/**
 * =========================================================
 * VALIDITY DATES
 * =========================================================
 */

function extractValidityDates(
  lines,
  fullText,
  dob,
  issueDate
) {

  let nt = 'Not detected';
  let tr = 'Not detected';


  for (const line of lines) {

    const u = upper(line);

    if (
      u.includes('VALIDITY') ||
      u.includes('VALID TILL') ||
      u.includes('EXPIRY')
    ) {

      const dates =
        extractAllDates(line)
          .filter(
            date =>
              date !== dob &&
              date !== issueDate
          );


      if (dates.length >= 1) {
        nt = dates[0];
      }

      if (dates.length >= 2) {
        tr = dates[1];
      }
    }
  }


  if (
    nt === 'Not detected' ||
    tr === 'Not detected'
  ) {

    const allDates =
      extractAllDates(fullText)
        .filter(
          date =>
            date !== dob &&
            date !== issueDate
        );


    if (
      nt === 'Not detected' &&
      allDates.length >= 1
    ) {
      nt = allDates[0];
    }


    if (
      tr === 'Not detected' &&
      allDates.length >= 2
    ) {
      tr = allDates[1];
    }
  }


  return {
    nt,
    tr
  };
}


/**
 * =========================================================
 * CLASS OF VEHICLE
 * =========================================================
 */

function extractCOV(
  fullText,
  lines
) {

  const knownClasses = [
    'MCWG',
    'MCWOG',
    'LMV',
    'LMV-NT',
    '3W-NT',
    'TRANS',
    'MC50CC',
    'HMV',
    'HGV',
    'LGV',
    'MOTOR CYCLE',
    'LIGHT MOTOR VEHICLE'
  ];


  const found = [];


  for (const type of knownClasses) {

    const regex =
      new RegExp(
        `\\b${type.replace('-', '[- ]?')}\\b`,
        'i'
      );

    if (
      regex.test(fullText) &&
      !found.includes(type)
    ) {
      found.push(type);
    }
  }


  for (const line of lines) {

    const u = upper(line);

    if (
      u.includes('COV') ||
      u.includes('CLASS OF VEHICLE')
    ) {

      for (const type of knownClasses) {

        if (
          u.includes(type) &&
          !found.includes(type)
        ) {
          found.push(type);
        }
      }
    }
  }


  return found.length > 0
    ? found.join(', ')
    : 'Not detected';
}


/**
 * =========================================================
 * SON / DAUGHTER / WIFE OF
 * =========================================================
 */

function extractParent(
  lines,
  fullText
) {

  const labels = [
    'SON/DAUGHTER/WIFE OF',
    'SON / DAUGHTER / WIFE OF',
    'SON/DAUGHTER/WIFE',
    'S/O',
    'D/O',
    'W/O',
    'FATHER'
  ];


  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const u = upper(line);

    const matched =
      labels.find(
        label =>
          u.includes(upper(label))
      );


    if (!matched) {
      continue;
    }


    let value = '';

    if (line.includes(':')) {

      value =
        afterColon(line);

    } else {

      const index =
        u.indexOf(
          upper(matched)
        );

      value =
        line.substring(
          index + matched.length
        ).trim();
    }

    // If empty on same line, look at next line
    if (!value || /^[-=~_.:\s]+$/.test(value)) {
      if (i + 1 < lines.length) {
        const nextLine = lines[i + 1].trim();
        if (
          !nextLine.match(/^(DOB|DATE|ADDRESS|VALIDITY|ISSUE|LICENCE|DL|NO|BLOOD|ORGAN)/i) &&
          nextLine.length >= 2
        ) {
          value = nextLine;
        }
      }
    }

    // Stop at other fields

    value =
      value
        .split(
          /ADDRESS|DATE OF BIRTH|DOB|ISSUE DATE|VALIDITY|BLOOD GROUP|ORGAN DONOR|SIGNATURE/i
        )[0];


    value =
      sanitizeRelativeName(value);


    if (
      value !== 'Not detected' &&
      value.length >= 2
    ) {

      return value;
    }
  }


  const match =
    fullText.match(
      /(?:S\/O|D\/O|W\/O|SON\/DAUGHTER\/WIFE\s*OF|FATHER)\s*[:\-]?\s*([A-Z][A-Z .]{2,60})/i
    );


  if (match) {

    const value =
      sanitizeRelativeName(match[1]);

    if (
      value !== 'Not detected' &&
      value.length >= 2
    ) {
      return value;
    }
  }


  return 'Not detected';
}


/**
 * =========================================================
 * STATE / ISSUING AUTHORITY
 * =========================================================
 */

function extractState(
  fullText,
  dlNumber
) {

  const mappings = {

    'TELANGANA':
      'TELANGANA RTO',

    'TG':
      'TELANGANA RTO',

    'ANDHRA PRADESH':
      'ANDHRA PRADESH RTO',

    'AP':
      'ANDHRA PRADESH RTO',

    'KARNATAKA':
      'KARNATAKA RTO',

    'KA':
      'KARNATAKA RTO',

    'MAHARASHTRA':
      'MAHARASHTRA RTO',

    'MH':
      'MAHARASHTRA RTO',

    'TAMIL NADU':
      'TAMIL NADU RTO',

    'TN':
      'TAMIL NADU RTO',

    'KERALA':
      'KERALA RTO',

    'KL':
      'KERALA RTO',

    'GUJARAT':
      'GUJARAT RTO',

    'GJ':
      'GUJARAT RTO',

    'RAJASTHAN':
      'RAJASTHAN RTO',

    'RJ':
      'RAJASTHAN RTO',

    'DELHI':
      'DELHI RTO',

    'DL':
      'DELHI RTO',

    'UTTAR PRADESH':
      'UTTAR PRADESH RTO',

    'UP':
      'UTTAR PRADESH RTO',

    'HARYANA':
      'HARYANA RTO',

    'HR':
      'HARYANA RTO',

    'PUNJAB':
      'PUNJAB RTO',

    'PB':
      'PUNJAB RTO',

    'WEST BENGAL':
      'WEST BENGAL RTO',

    'WB':
      'WEST BENGAL RTO'
  };


  const u =
    upper(fullText);


  const fullNames =
    Object.keys(mappings)
      .filter(
        key =>
          key.length > 2
      )
      .sort(
        (a, b) =>
          b.length - a.length
      );


  for (const key of fullNames) {

    if (u.includes(key)) {
      return mappings[key];
    }
  }


  if (
    dlNumber !== 'Not detected' &&
    /^[A-Z]{2}/i.test(dlNumber)
  ) {

    const prefix =
      dlNumber
        .substring(0, 2)
        .toUpperCase();


    if (mappings[prefix]) {
      return mappings[prefix];
    }

    return `${prefix} RTO`;
  }


  return 'Not detected';
}


/**
 * =========================================================
 * ADDRESS
 * =========================================================
 */

function extractAddress(
  lines,
  fullText
) {

  for (
    let i = 0;
    i < lines.length;
    i++
  ) {

    const line =
      clean(lines[i]);

    const u =
      upper(line);


    if (
      !u.includes('ADDRESS')
    ) {
      continue;
    }


    let address = '';

    if (line.includes(':')) {
      address = afterColon(line);
    }


    const parts = [];


    // Add text after Address:

    if (
      address &&
      !/^[-=~_.]+$/.test(address)
    ) {

      parts.push(
        address
          .replace(/[|~_=]+/g, ' ')
          .trim()
      );
    }


    // Read following lines

    for (
      let j = i + 1;
      j < lines.length;
      j++
    ) {

      let next =
        clean(lines[j]);

      if (!next) {
        continue;
      }


      const nextUpper =
        upper(next);


      // Stop at other fields

      if (
        nextUpper.includes('BLOOD GROUP') ||
        nextUpper.includes('ORGAN DONOR') ||
        nextUpper.includes('DATE OF BIRTH') ||
        nextUpper.includes('DOB') ||
        nextUpper.includes('ISSUE DATE') ||
        nextUpper.includes('VALIDITY') ||
        nextUpper.includes('CLASS OF VEHICLE') ||
        nextUpper.includes('COV') ||
        nextUpper.includes('SIGNATURE')
      ) {
        break;
      }


      // Remove OCR symbols

      next =
        next
          .replace(/[|~_=]+/g, ' ')
          .replace(/\s+/g, ' ')
          .replace(/\s*,\s*,/g, ',')
          .replace(/,\s*,/g, ',')
          .trim();


      if (
        !next ||
        /^[-.,\s]+$/.test(next)
      ) {
        continue;
      }


      parts.push(next);


      if (
        parts.length >= 6
      ) {
        break;
      }
    }


    address =
      parts
        .join(', ')
        .replace(/\s*,\s*,/g, ',')
        .replace(/,\s*$/g, '')
        .trim();


    const sanitized = sanitizeAddress(address);
    if (sanitized !== 'Not detected') {
      return sanitized;
    }
  }


  /**
   * PIN fallback
   */

  const pinRegex =
    /\b\d{6}\b/;


  for (
    let i = 0;
    i < lines.length;
    i++
  ) {

    if (
      pinRegex.test(lines[i])
    ) {

      const start =
        Math.max(
          0,
          i - 3
        );

      const end =
        Math.min(
          lines.length,
          i + 1
        );


      const possible =
        lines
          .slice(start, end)
          .filter(line => {

            const u =
              upper(line);

            return (
              !u.includes('DATE') &&
              !u.includes('NAME') &&
              !u.includes('SIGNATURE') &&
              !u.includes('VALIDITY') &&
              !u.includes('BLOOD GROUP')
            );
          })
          .map(line =>
            clean(line)
              .replace(/[|~_=]+/g, ' ')
              .trim()
          )
          .filter(Boolean);


      const address =
        clean(
          possible.join(', ')
        );


      const sanitized = sanitizeAddress(address);
      if (sanitized !== 'Not detected') {
        return sanitized;
      }
    }
  }

  return 'Not detected';
}


/**
 * =========================================================
 * BLOOD GROUP
 * =========================================================
 */

function extractBloodGroup(
  lines,
  fullText
) {

  /**
   * Supports:
   * Blood Group: Unknown
   * Blood Group: A+
   * Blood Group: B-
   * Blood Group: AB+
   * Blood Group: O-
   */

  const match =
    fullText.match(
      /BLOOD\s*GROUP\s*[:\-]?\s*(UNKNOWN|AB\s*[+-]|A\s*[+-]|B\s*[+-]|O\s*[+-])/i
    );


  if (match) {

    return clean(
      match[1]
    ).toUpperCase();
  }


  for (const line of lines) {

    const u =
      upper(line);

    if (
      u.includes('BLOOD GROUP')
    ) {

      const after =
        afterColon(line);


      if (after) {

        const value =
          after.match(
            /^(UNKNOWN|AB\s*[+-]|A\s*[+-]|B\s*[+-]|O\s*[+-])/i
          );


        if (value) {

          return clean(
            value[1]
          ).toUpperCase();
        }
      }
    }
  }


  return 'Not detected';
}


/**
 * =========================================================
 * ORGAN DONOR
 * =========================================================
 */

function extractOrganDonor(
  lines,
  fullText
) {

  const match =
    fullText.match(
      /ORGAN\s*DONOR\s*[:\-]?\s*(YES|NO)/i
    );


  if (match) {
    return match[1].toUpperCase();
  }


  for (const line of lines) {

    const u =
      upper(line);


    if (
      u.includes('ORGAN DONOR')
    ) {

      const value =
        afterColon(line);


      if (value) {

        const yesNo =
          value.match(
            /\b(YES|NO)\b/i
          );


        if (yesNo) {

          return yesNo[1]
            .toUpperCase();
        }
      }
    }
  }


  return 'Not detected';
}


/**
 * =========================================================
 * MAIN PARSER
 * =========================================================
 */

export function parseDrivingLicence(
  words = [],
  lines = [],
  fullText = ''
) {

  console.log(
    '[DL Parser] Starting driving licence field extraction...'
  );


  /**
   * Normalize input
   */

  const safeWords =
    Array.isArray(words)
      ? words
      : [];


  const safeLines =
    Array.isArray(lines)
      ? lines
          .map(line => clean(line))
          .filter(Boolean)
      : [];


  const safeText =
    clean(fullText);


  /**
   * LICENCE NUMBER
   */

  const licence =
    extractLicenceNumber(
      safeWords,
      safeText
    );


  /**
   * NAME
   */

  const name =
    extractFullName(
      safeWords,
      safeLines
    );


  /**
   * DOB
   */

  const dob =
    extractDob(
      safeLines,
      safeWords,
      safeText
    );


  /**
   * ISSUE DATE
   */

  const issueDate =
    extractIssueDate(
      safeLines,
      safeWords,
      safeText,
      dob.value
    );


  /**
   * VALIDITY
   */

  const validity =
    extractValidityDates(
      safeLines,
      safeText,
      dob.value,
      issueDate
    );


  /**
   * OTHER FIELDS
   */

  const cov =
    extractCOV(
      safeText,
      safeLines
    );


  const parent =
    extractParent(
      safeLines,
      safeText
    );


  const state =
    extractState(
      safeText,
      licence.value
    );


  const address =
    extractAddress(
      safeLines,
      safeText
    );


  const bloodGroup =
    extractBloodGroup(
      safeLines,
      safeText
    );


  const organDonor =
    extractOrganDonor(
      safeLines,
      safeText
    );


  /**
   * DEBUG
   */

  console.log(
    '[DL Parser] Licence:',
    licence.value !== 'Not detected'
      ? 'Detected'
      : 'Not detected'
  );

  console.log(
    '[DL Parser] Name:',
    name.value
  );

  console.log(
    '[DL Parser] DOB:',
    dob.value
  );

  console.log(
    '[DL Parser] Issue Date:',
    issueDate
  );

  console.log(
    '[DL Parser] Validity NT:',
    validity.nt
  );

  console.log(
    '[DL Parser] Validity TR:',
    validity.tr
  );

  console.log(
    '[DL Parser] COV:',
    cov
  );

  console.log(
    '[DL Parser] Parent:',
    parent
  );

  console.log(
    '[DL Parser] State:',
    state
  );

  console.log(
    '[DL Parser] Address:',
    address
  );

  console.log(
    '[DL Parser] Blood Group:',
    bloodGroup
  );

  console.log(
    '[DL Parser] Organ Donor:',
    organDonor
  );


  /**
   * FINAL RESULT
   */

  return {

    'Document Type':
      'Indian Driving Licence',

    'Licence Number':
      licence.value,

    'Licence Number Confidence':
      licence.confidence,

    'Full Name':
      name.value,

    'Name Confidence':
      name.confidence,

    'Date of Birth':
      dob.value,

    'DOB Confidence':
      dob.confidence,

    'Issue Date':
      issueDate,

    'Validity (NT)':
      validity.nt,

    'Validity (TR)':
      validity.tr,

    'Class of Vehicle / COV':
      cov,

    'Son/Daughter/Wife of':
      parent,

    'State / Issuing Authority':
      state,

    'Address':
      address,

    'Blood Group':
      bloodGroup,

    'Organ Donor':
      organDonor
  };
}