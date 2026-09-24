import { sanitizePersonName, sanitizeRelativeName, sanitizeAddress, sanitizePlace } from './nameAddressSanitizer.js';
import { parsePanCard } from './parsers/panParser.js';
import { parsePassport } from './parsers/passportParser.js';
import { parseAadhaarCard } from './parsers/aadhaarParser.js';
import { parseDrivingLicence } from './parsers/dlParser.js';
import { parseVoterId } from './parsers/voterIdParser.js';

console.log('=== RUNNING ALL OCR RECTIFICATION TESTS ===\n');

let failed = 0;

function assert(condition, desc) {
  if (condition) {
    console.log(`[PASS] ${desc}`);
  } else {
    console.error(`[FAIL] ${desc}`);
    failed++;
  }
}

// 1. Sanitize Person Name Unit Tests
console.log('--- 1. Person Name Sanitization Tests ---');
assert(sanitizePersonName('D MANIKANDAN') === 'D MANIKANDAN', 'Preserve single initial at start (D MANIKANDAN)');
assert(sanitizePersonName('E THADA SAI PRAGNAY') === 'E THADA SAI PRAGNAY', 'Preserve single initial (E THADA SAI PRAGNAY)');
assert(sanitizePersonName('RAJESH KUMAR 7%') === 'RAJESH KUMAR', 'Strip OCR trailing artifact (7%)');
assert(sanitizePersonName('J0HN D0E') === 'JOHN DOE', 'Fix digit-to-letter confusion (J0HN D0E -> JOHN DOE)');
assert(sanitizePersonName("NAME : PRIYA SHARMA FATHER'S NAME") === 'PRIYA SHARMA', "Cut off label bleed (FATHER'S NAME)");
assert(sanitizePersonName('HOLDER SIGNATURE') === 'Not detected', 'Reject blocked keyword placeholder');

// 2. Relative Name Sanitization Tests
console.log('\n--- 2. Relative Name Sanitization Tests ---');
assert(sanitizeRelativeName('S/O RAMESH KUMAR') === 'RAMESH KUMAR', 'Strip S/O prefix');
assert(sanitizeRelativeName("FATHER'S NAME: DURAISAMY") === 'DURAISAMY', "Strip FATHER'S NAME prefix");
assert(sanitizeRelativeName('W/O ANIL VERMA 3') === 'ANIL VERMA', 'Strip trailing OCR digits/noise');

// 3. Address Sanitization Tests
console.log('\n--- 3. Address Sanitization Tests ---');
const aadhaarAddr = 'H NO 4-52/1 MAIN ROAD, GACHIBOWLI, HYDERABAD, TELANGANA - 500032 Aadhaar is proof of identity, not of citizenship.';
const cleanedAddr = sanitizeAddress(aadhaarAddr);
assert(cleanedAddr.includes('500032') && !cleanedAddr.includes('proof of identity'), 'Truncate disclaimer and keep clean address with PIN');

const dlAddr = 'FLAT 201, PEARL APARTMENTS, INDIRANAGAR, BENGALURU, KARNATAKA 560038 Licence to drive throughout India';
const cleanedDlAddr = sanitizeAddress(dlAddr);
assert(cleanedDlAddr.includes('560038') && !cleanedDlAddr.includes('Licence to drive'), 'Truncate DL disclaimer from address');

// 4. Place Sanitization Tests
console.log('\n--- 4. Place of Birth / Issue Sanitization Tests ---');
assert(sanitizePlace('PLACE OF BIRTH: HYDERABAD') === 'HYDERABAD', 'Strip PLACE OF BIRTH label');
assert(sanitizePlace('P.O.I: NEW DELHI, INDIA') === 'NEW DELHI', 'Clean up Place of Issue with country suffix');
assert(sanitizePlace('MUMBAI 400001') === 'MUMBAI', 'Clean trailing PIN from place');

// 5. PAN Card Real Parser Test
console.log('\n--- 5. PAN Card Parser with Real Devanagari Noise ---');
const panLines = [
  'आयकर विभाग',
  'INCOME TAX DEPARTMENT',
  'GOVT. OF INDIA',
  'D MANIKANDAN',
  'DURAISAMY',
  '15/08/1990',
  'Permanent Account Number Card',
  'ABCDE1234F',
  'Signature'
];
const panWords = panLines.flatMap((line, idx) =>
  line.split(' ').map((w, wIdx) => ({
    text: w,
    confidence: 88,
    lineNum: idx + 1,
    bbox: { x0: 10 + wIdx * 40, y0: 10 + idx * 20, x1: 40 + wIdx * 40, y1: 25 + idx * 20 }
  }))
);
const panResult = parsePanCard(panWords, panLines, panLines.join('\n'));
assert(panResult['Full Name'] === 'D MANIKANDAN', `PAN Full Name correctly parsed as "D MANIKANDAN" (got: "${panResult['Full Name']}")`);
assert(panResult["Father's Name"] === 'DURAISAMY', `PAN Father's Name correctly parsed as "DURAISAMY" (got: "${panResult["Father's Name"]}")`);
assert(panResult['PAN Number'] === 'ABCDE1234F', `PAN Number correctly parsed (got: "${panResult['PAN Number']}")`);
assert(panResult['Address'] === undefined || panResult['Address'] === 'Not detected', 'PAN Card has no spurious Address');

// 6. Passport Parser Test
console.log('\n--- 6. Passport Parser Test ---');
const passportText = `
INDIAN PASSPORT / PASSEPORT
REPUBLIC OF INDIA
TYPE: P  CODE: IND  PASSPORT NO: Z1234567
GIVEN NAME: ARUN
SURNAME: SHARMA
NATIONALITY: INDIAN
DATE OF BIRTH: 12/04/1988
SEX: M
PLACE OF BIRTH: NEW DELHI
DATE OF ISSUE: 10/01/2020
DATE OF EXPIRY: 09/01/2030
PLACE OF ISSUE: DELHI
P<INDSHARMA<<ARUN<<<<<<<<<<<<<<<<<<<<<<<<<<<
Z1234567<3IND8804128M3001095<<<<<<<<<<<<<<02
`;
const passLines = passportText.trim().split('\n');
const passWords = passLines.flatMap((line, idx) =>
  line.split(' ').map((w, wIdx) => ({
    text: w,
    confidence: 90,
    bbox: { x0: 10 + wIdx * 30, y0: 10 + idx * 20, x1: 35 + wIdx * 30, y1: 25 + idx * 20 }
  }))
);
const passResult = parsePassport(passWords, passLines, passportText);
assert(passResult['Full Name'] === 'ARUN SHARMA', `Passport Full Name is ARUN SHARMA (got: "${passResult['Full Name']}")`);
assert(passResult['Place of Birth'] === 'NEW DELHI', `Passport Place of Birth is NEW DELHI (got: "${passResult['Place of Birth']}")`);
assert(passResult['Place of Issue'] === 'DELHI', `Passport Place of Issue is DELHI (got: "${passResult['Place of Issue']}")`);
assert(passResult['Passport Number'] === 'Z1234567', `Passport Number is Z1234567 (got: "${passResult['Passport Number']}")`);

// 7. Voter ID Parser Test
console.log('\n--- 7. Voter ID Parser Test ---');
const voterLines = [
  'ELECTION COMMISSION OF INDIA',
  'ELECTOR PHOTO IDENTITY CARD',
  'EPIC NO: WBS1234567',
  "ELECTOR'S NAME: SUMAN ROY",
  "FATHER'S NAME: BIJOY ROY",
  'SEX: MALE',
  'DATE OF BIRTH: 22/11/1995',
  'ADDRESS: 14 PARK STREET, KOLKATA, WEST BENGAL - 700016'
];
const voterWords = voterLines.flatMap((line, idx) =>
  line.split(' ').map((w, wIdx) => ({
    text: w,
    confidence: 88,
    bbox: { x0: 10 + wIdx * 30, y0: 10 + idx * 20, x1: 35 + wIdx * 30, y1: 25 + idx * 20 }
  }))
);
const voterResult = parseVoterId(voterWords, voterLines, voterLines.join('\n'));
assert(voterResult['EPIC / Voter ID Number'] === 'WBS1234567', `EPIC Number is WBS1234567 (got: "${voterResult['EPIC / Voter ID Number']}")`);
assert(voterResult['Full Name'] === 'SUMAN ROY', `Voter Full Name is SUMAN ROY (got: "${voterResult['Full Name']}")`);
assert(voterResult["Father's / Husband's Name"] === 'BIJOY ROY', `Voter Relation Name is BIJOY ROY (got: "${voterResult["Father's / Husband's Name"]}")`);
assert(voterResult['Address'].includes('700016'), `Voter Address includes PIN (got: "${voterResult['Address']}")`);

console.log('\n========================================');
if (failed === 0) {
  console.log('ALL RECTIFICATION TESTS PASSED SUCCESSFULLY! (0 failures)');
} else {
  console.error(`${failed} TEST(S) FAILED!`);
  process.exit(1);
}
