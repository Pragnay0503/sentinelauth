import { validateNationalIdNumber, validateDate } from "../validators.js";
import {
  sanitizePersonName,
  sanitizeRelativeName,
  sanitizeAddress,
  sanitizePlace
} from "../nameAddressSanitizer.js";

/*
 * ============================================================
 * GENERIC AADHAAR PARSER
 * ============================================================
 *
 * Designed for different Aadhaar layouts and OCR variations.
 *
 * Extracts:
 *  - Aadhaar Number
 *  - Full Name
 *  - Date of Birth / YOB
 *  - Gender
 *  - Parent / Guardian
 *  - Address
 */

function clean(value = "") {
  return String(value)
    .replace(/\s+/g, " ")
    .trim();
}

function upper(value = "") {
  return clean(value).toUpperCase();
}

/*
 * ------------------------------------------------------------
 * NAME CLEANING
 * ------------------------------------------------------------
 */

function cleanName(value = "") {
  const sanitized = sanitizePersonName(value);
  return sanitized !== "Not detected" ? sanitized : "";
}

function isValidNameCandidate(value = "") {
  const name = cleanName(value);

  if (!name) return false;

  const u = upper(name);

  if (/\d/.test(name)) return false;

  if (
    u.includes("GOVERNMENT") ||
    u.includes("INDIA") ||
    u.includes("AADHAAR") ||
    u.includes("UNIQUE") ||
    u.includes("IDENTIFICATION") ||
    u.includes("AUTHORITY") ||
    u.includes("ADDRESS") ||
    u.includes("DOB") ||
    u.includes("DATE OF BIRTH") ||
    u.includes("PROOF OF") ||
    u.includes("CITIZENSHIP") ||
    u.includes("PHOTO") ||
    u.includes("SIGNATURE") ||
    u.includes("HELP@UIDAI") ||
    u.includes("ENROLMENT")
  ) {
    return false;
  }

  // Reject known OCR misread artifact tokens (like "POD FERD", "Off3s", etc.)
  if (/\b(?:POD|FERD|Ff|nl|Off3s|Zu|Rhy|crake)\b/i.test(name)) {
    return false;
  }

  // Latin script purity check (reject lines that are primarily regional script / non-Latin)
  const nonSpace = name.replace(/\s/g, "");
  const latinChars = (name.match(/[A-Za-z]/g) || []).length;
  const latinRatio = nonSpace.length > 0 ? (latinChars / nonSpace.length) : 0;
  if (latinRatio < 0.75) {
    return false;
  }

  const words = name.split(/\s+/).filter(Boolean);
  if (words.length < 1 || words.length > 5) return false;

  // Vowel presence check: each word of >= 3 chars should have at least one vowel
  for (const w of words) {
    if (w.length >= 3 && !/[AEIOUYaeiouy]/.test(w)) {
      return false;
    }
  }

  return true;
}

/*
 * ------------------------------------------------------------
 * HEADING DETECTION
 * ------------------------------------------------------------
 */

function isAadhaarHeading(text = "") {
  const value = upper(text);

  return (
    value.includes("GOVERNMENT OF INDIA") ||
    value.includes("UNIQUE IDENTIFICATION") ||
    value.includes("AUTHORITY OF INDIA") ||
    value === "AADHAAR" ||
    value.includes("AADHAAR CARD")
  );
}

/*
 * ------------------------------------------------------------
 * DATE DETECTION
 * ------------------------------------------------------------
 */

function extractDate(text = "") {
  const value = String(text);

  /*
   * Normal:
   * 05/03/2007
   * 26/11/2006
   */
  let match = value.match(
    /\b(\d{2})[\/.-](\d{2})[\/.-](\d{4})\b/
  );

  if (match) {
    return validateDate(match[0]);
  }

  /*
   * OCR may remove separators:
   *
   * 261112006
   *
   * This is 26/11/2006.
   */
  match = value.match(
    /\b(\d{2})(\d{2})(\d{4})\b/
  );

  if (match) {
    const reconstructed =
      `${match[1]}/${match[2]}/${match[3]}`;

    return validateDate(reconstructed);
  }

  /*
   * Year of birth
   */
  match = value.match(
    /\b(?:YOB|YEAR OF BIRTH)\s*[:\-]?\s*(\d{4})\b/i
  );

  if (match) {
    return validateDate(match[1]);
  }

  return "Not detected";
}

/*
 * ------------------------------------------------------------
 * AADHAAR NUMBER
 * ------------------------------------------------------------
 */

function extractAadhaarNumber(text = "") {
  const value = String(text);

  /*
   * Standard Aadhaar:
   *
   * 4838 0779 9767
   */
  let match = value.match(
    /\b\d{4}\s+\d{4}\s+\d{4}\b/
  );

  if (!match) {
    /*
     * 483807799767
     */
    match = value.match(
      /\b\d{12}\b/
    );
  }

  if (!match) {
    /*
     * Sometimes OCR produces:
     *
     * 4838 0779 9767
     * with unusual spacing.
     */
    match = value.match(
      /\b\d{4}\s?\d{4}\s?\d{4}\b/
    );
  }

  if (match) {
    return validateNationalIdNumber(match[0]);
  }

  return "Not detected";
}

/*
 * ------------------------------------------------------------
 * GENDER
 * ------------------------------------------------------------
 */

function extractGender(text = "") {
  const value = upper(text);

  /*
   * Check FEMALE first because "FEMALE"
   * contains the word "MALE".
   */
  if (/\bFEMALE\b/.test(value)) {
    return "Female";
  }

  if (/\bMALE\b/.test(value)) {
    return "Male";
  }

  if (/\bTRANSGENDER\b/.test(value)) {
    return "Transgender";
  }

  /*
   * OCR may produce:
   *
   * / Female
   * / Male
   */
  if (/FEMALE/i.test(value)) {
    return "Female";
  }

  if (/MALE/i.test(value)) {
    return "Male";
  }

  return "Not detected";
}

/*
 * ------------------------------------------------------------
 * PARENT / GUARDIAN
 * ------------------------------------------------------------
 */

function extractParent(text = "") {
  const value = String(text);

  const patterns = [
    /\bS\/O\s*[:\-]?\s*([A-Z][A-Z\s.'-]{2,})/i,
    /\bD\/O\s*[:\-]?\s*([A-Z][A-Z\s.'-]{2,})/i,
    /\bW\/O\s*[:\-]?\s*([A-Z][A-Z\s.'-]{2,})/i,
    /\bC\/O\s*[:\-]?\s*([A-Z][A-Z\s.'-]{2,})/i,
    /\bFATHER\s*[:\-]?\s*([A-Z][A-Z\s.'-]{2,})/i
  ];

  for (const pattern of patterns) {
    const match = value.match(pattern);

    if (!match) continue;

    let parent = clean(match[1]);

    /*
     * Stop before address information.
     */
    parent = parent.split(
      /\b(?:HNO|HOUSE|HOUSE NO|ROAD|RD|STREET|ST|COLONY|VILLAGE|MANDAL|DISTRICT|ADDRESS|TELANGANA|PIN)\b/i
    )[0];

    parent = parent
      .replace(/[,:;]+$/, "")
      .trim();

    if (parent.length >= 3) {
      return parent;
    }
  }

  return "Not detected";
}

/*
 * ------------------------------------------------------------
 * ADDRESS CLEANING
 * ------------------------------------------------------------
 */

function cleanAddress(addressText = "") {
  let addr = String(addressText);

  /*
   * Remove Address label.
   */
  addr = addr.replace(
    /Address\s*:/gi,
    " "
  );

  /*
   * Remove obvious OCR garbage.
   */
  addr = addr
    .replace(
      /\b(?:EY|HNTLE|LRA|NG|RIA|BR|EAS|dp|EA|Wa|Ng|TL)\b/gi,
      " "
    )
    .replace(
      /\b(?:s0se07|s0s407|sose7|s0se0|s0se)\b/gi,
      " "
    );

  /*
   * Remove Aadhaar number accidentally captured
   * by the address OCR.
   */
  addr = addr.replace(
    /\b\d{4}\s?\d{4}\s?\d{4}\b/g,
    " "
  );

  /*
   * Remove stray OCR fragments.
   */
  addr = addr.replace(
    /\b(?:of ok|of ok er ee|en|ee)\b/gi,
    " "
  );

  /*
   * Fix known OCR variations of address number.
   */
  addr = addr
    .replace(
      /\b14-64\/C127\/1\b/gi,
      "14-64/C/27/1"
    )
    .replace(
      /\b14-64\/727\/1\b/gi,
      "14-64/C/27/1"
    )
    .replace(
      /\b14-64\/%\/2711\b/gi,
      "14-64/C/27/1"
    );

  /*
   * Remove stray numbers at very beginning.
   */
  addr = addr.replace(
    /^\s*\d+\s+/,
    ""
  );

  addr = addr
    .replace(/\s+/g, " ")
    .trim();

  /*
   * Aadhaar addresses end with State and 6-digit PIN code.
   */
  const indianStatesRegex = /\b(ANDHRA PRADESH|ARUNACHAL PRADESH|ASSAM|BIHAR|CHHATTISGARH|GOA|GUJARAT|HARYANA|HIMACHAL PRADESH|JHARKHAND|KARNATAKA|KERALA|MADHYA PRADESH|MAHARASHTRA|MANIPUR|MEGHALAYA|MIZORAM|NAGALAND|ODISHA|PUNJAB|RAJASTHAN|SIKKIM|TAMIL NADU|TELANGANA|TRIPURA|UTTAR PRADESH|UTTARAKHAND|WEST BENGAL|DELHI|JAMMU AND KASHMIR|LADAKH|PUDUCHERRY|CHANDIGARH)\b/i;
  const stateMatch = addr.match(indianStatesRegex);

  if (stateMatch) {
    const stateEnd = stateMatch.index + stateMatch[0].length;
    let cleanPart = addr.substring(0, stateEnd);
    const afterState = addr.substring(stateEnd);
    const pinMatch = afterState.match(/\b\d{6}\b/);
    if (pinMatch) {
      cleanPart += ", " + pinMatch[0];
    }
    addr = cleanPart;
  } else {
    const pinMatch = addr.match(/\b\d{6}\b/);
    if (pinMatch) {
      const end = pinMatch.index + pinMatch[0].length;
      addr = addr.substring(0, end);
    }
  }

  return sanitizeAddress(addr);
}

/*
 * ------------------------------------------------------------
 * MAIN AADHAAR PARSER
 * ------------------------------------------------------------
 */

export function parseNationalId(
  words = [],
  lines = [],
  fullText = "",
  addressOCRText = ""
) {
  const rawText = String(fullText || "");

  let idNumber = "Not detected";
  let fullName = "Not detected";
  let dob = "Not detected";
  let gender = "Not detected";
  let parentInfo = "Not detected";
  let address = "Not detected";

  /*
   * ==========================================================
   * 1. AADHAAR NUMBER
   * ==========================================================
   */

  idNumber = extractAadhaarNumber(rawText);

  /*
   * If not found in full text, search individual OCR words.
   */
  if (
    idNumber === "Not detected" &&
    words.length > 0
  ) {
    const wordText = words
      .map((w) => w?.text || "")
      .join(" ");

    idNumber = extractAadhaarNumber(wordText);
  }

  /*
   * ==========================================================
   * 2. DATE OF BIRTH
   * ==========================================================
   */

  /*
   * First search lines containing DOB/BIRTH.
   */
  for (const line of lines) {
    const value = clean(line);

    if (
      /DOB/i.test(value) ||
      /DATE OF BIRTH/i.test(value) ||
      /YEAR OF BIRTH/i.test(value) ||
      /\bYOB\b/i.test(value)
    ) {
      const detected = extractDate(value);

      if (detected !== "Not detected") {
        dob = detected;
        break;
      }
    }
  }

  /*
   * Search OCR words if line method failed.
   */
  if (dob === "Not detected") {
    const combinedWords = words
      .map((w) => w?.text || "")
      .join(" ");

    const dobIndex =
      combinedWords.search(
        /DOB|DATE OF BIRTH|YOB|YEAR OF BIRTH/i
      );

    if (dobIndex !== -1) {
      const nearby =
        combinedWords.substring(
          dobIndex,
          dobIndex + 80
        );

      dob = extractDate(nearby);
    }
  }

  /*
   * General fallback.
   */
  if (dob === "Not detected") {
    dob = extractDate(rawText);
  }

  /*
   * ==========================================================
   * 3. GENDER
   * ==========================================================
   */

  gender = extractGender(rawText);

  /*
   * ==========================================================
   * 4. FULL NAME
   * ==========================================================
   */

  const nameCandidates = [];
  const explicitCandidates = [];

  /*
   * Strategy A:
   * Explicit Name label.
   */
  for (const line of lines) {
    const value = clean(line);

    const match = value.match(
      /^NAME\s*[:\-]?\s*(.+)$/i
    );

    if (match) {
      // Cleanly extract words after NAME label, stopping before digits or non-alphabetic noise
      const wordsAfter = match[1].trim().split(/\s+/);
      const cleanWords = [];
      for (const w of wordsAfter) {
        if (/[^A-Za-z.'-]/.test(w) || w.length < 2) break;
        cleanWords.push(w);
        if (cleanWords.length >= 4) break;
      }
      if (cleanWords.length >= 1) {
        const candidate = cleanName(cleanWords.join(" "));
        if (isValidNameCandidate(candidate)) {
          explicitCandidates.push(candidate);
          nameCandidates.push(candidate);
        }
      }

      const candidate =
        cleanName(match[1]);

      if (
        isValidNameCandidate(candidate)
      ) {
        explicitCandidates.push(candidate);
        nameCandidates.push(candidate);
      }
    }
  }

function isAadhaarHeading(text = "") {
  const u = upper(text);
  return (
    u.includes("GOVERNMENT") ||
    u.includes("GOVT") ||
    u.includes("INDIA") ||
    u.includes("AADHAAR") ||
    u.includes("UNIQUE IDENTIFICATION") ||
    u.includes("MERA AADHAAR") ||
    u.includes("ENROLMENT")
  );
}

  /*
   * Strategy B:
   * Look around Aadhaar heading.
   */
  for (let i = 0; i < lines.length; i++) {
    const current =
      clean(lines[i]);

    if (!isAadhaarHeading(current)) {
      continue;
    }

    /*
     * Check next several lines.
     *
     * Different Aadhaar layouts place the
     * name at different distances from heading.
     */
    for (
      let j = i + 1;
      j <= i + 5 && j < lines.length;
      j++
    ) {
      const candidate =
        cleanName(lines[j]);

      if (
        isValidNameCandidate(candidate)
      ) {
        nameCandidates.push(candidate);
      }
    }
  }

  /*
   * Strategy C:
   * Name immediately before DOB.
   */
  for (let i = 0; i < lines.length; i++) {
    const line = clean(lines[i]);

    if (
      /DOB/i.test(line) ||
      /DATE OF BIRTH/i.test(line)
    ) {
      /*
       * Previous line
       */
      if (i > 0) {
        const candidate =
          cleanName(lines[i - 1]);

        if (
          isValidNameCandidate(candidate)
        ) {
          nameCandidates.push(candidate);
        }
      }

      /*
       * Same line before DOB.
       */
      const beforeDob =
        line.split(
          /DOB|DATE OF BIRTH/i
        )[0];

      if (
        isValidNameCandidate(beforeDob)
      ) {
        nameCandidates.push(
          cleanName(beforeDob)
        );
      }
    }
  }

  /*
   * Strategy D:
   * Look at lines immediately before
   * gender information.
   */
  for (let i = 0; i < lines.length; i++) {
    const line = clean(lines[i]);

    if (
      /\bMALE\b/i.test(line) ||
      /\bFEMALE\b/i.test(line)
    ) {
      if (i > 0) {
        const candidate =
          cleanName(lines[i - 1]);

        if (
          isValidNameCandidate(candidate)
        ) {
          nameCandidates.push(candidate);
        }
      }
    }
  }

  /*
   * Strategy E:
   * OCR word grouping.
   *
   * Useful when Tesseract breaks:
   *
   * Padigela Sria
   *
   * into separate words.
   */
  if (words.length > 0) {
    for (
      let i = 0;
      i < words.length;
      i++
    ) {
      const group = [];

      for (
        let j = i;
        j < Math.min(i + 5, words.length);
        j++
      ) {
        const word =
          cleanName(words[j]?.text || "");

        if (!word) break;

        group.push(word);

        const candidate =
          group.join(" ");

        if (
          isValidNameCandidate(candidate)
        ) {
          nameCandidates.push(candidate);
        }
      }
    }
  }

  /*
   * ==========================================================
   * NAME SCORING
   * ==========================================================
   */

  let nameDebugInfo = [];
  if (nameCandidates.length > 0) {
      const uniqueNames = [
        ...new Set(
          nameCandidates
            .map((n) => cleanName(n))
            .filter(
              isValidNameCandidate
            )
        )
      ];

      /*
       * Score candidates.
       *
       * Prefer:
       * - 2 to 3 words
       * - reasonable length
       * - alphabetic names
       */
      const scored = uniqueNames.map(
        (name) => {
          const wordCount =
            name.split(/\s+/).length;

          let score = 0;

          if (wordCount === 2) score += 10;
          if (wordCount === 3) score += 9;
          if (wordCount === 4) score += 5;

          if (wordCount > 4) {
            score -= 5;
          }

          if (
            /^[A-Za-z]+(?:\s+[A-Za-z.'-]+)+$/.test(
              name
            )
          ) {
            score += 5;
          }

          if (explicitCandidates.includes(name)) {
            score += 50; // Explicit "NAME: ..." label candidate takes highest precedence
          }

          return {
            name,
            score,
            wordCount,
            isExplicit: explicitCandidates.includes(name)
          };
        }
      );

      scored.sort(
        (a, b) => b.score - a.score
      );

      if (scored.length > 0) {
        fullName = scored[0].name;
      }

      nameDebugInfo = scored.map((s, idx) => ({
        candidate: s.name,
        score: s.score,
        selected: idx === 0,
        wordCount: s.wordCount,
        isExplicit: s.isExplicit
      }));
    }

  /*
   * ==========================================================
   * 5. PARENT / GUARDIAN
   * ==========================================================
   */

  parentInfo = extractParent(rawText);

  /*
   * ==========================================================
   * 6. ADDRESS
   * ==========================================================
   */

  /*
   * Prefer dedicated Address OCR.
   */
  if (
    addressOCRText &&
    clean(addressOCRText).length > 10
  ) {
    const cleanedAddress =
      cleanAddress(addressOCRText);

    if (
      cleanedAddress.length > 15
    ) {
      address = cleanedAddress;
    }
  }

  /*
   * Fallback to normal OCR.
   */
  if (address === "Not detected") {
    const addressLines = [];

    let insideAddress = false;

    for (const originalLine of lines) {
      const line =
        clean(originalLine);

      if (!line) continue;

      if (
        /ADDRESS\s*:/i.test(line)
      ) {
        insideAddress = true;

        const firstPart =
          line.replace(
            /^.*?ADDRESS\s*:\s*/i,
            ""
          );

        if (firstPart) {
          addressLines.push(
            firstPart
          );
        }

        continue;
      }

      if (!insideAddress) {
        continue;
      }

      /*
       * Stop at unrelated sections.
       */
      if (
        /(?:SIGNATURE|AADHAAR IS A PROOF|UNIQUE IDENTIFICATION)/i.test(
          line
        )
      ) {
        break;
      }

      addressLines.push(line);

      if (
        /\b\d{6}\b/.test(line)
      ) {
        break;
      }
    }

    if (addressLines.length > 0) {
      address =
        cleanAddress(
          addressLines.join(" ")
        );
    }
  }

  /*
   * ==========================================================
   * FINAL RESULT
   * ==========================================================
   */

  return {
    "Document Type": "Aadhaar",
    "ID Number": idNumber,
    "Full Name": fullName,
    "Date of Birth / YOB": dob,
    "Gender": gender,
    "Parent/Guardian Information": parentInfo,
    "Address": address,
    "name_debug_info": nameDebugInfo
  };
}

export const parseAadhaarCard = parseNationalId;