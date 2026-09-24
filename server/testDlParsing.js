import { parseDrivingLicence } from './parsers/dlParser.js';
import fs from 'fs';

// Mock words extracted from the DL test
const tsvText = `level	page_num	block_num	par_num	line_num	word_num	left	top	width	height	conf	text
5	1	1	1	1	1	31	22	33	8	93.8	INDIAN
5	1	1	1	1	2	68	22	31	8	93.1	UNION
5	1	1	1	1	3	103	22	38	8	88.5	DRIVING
5	1	1	1	1	4	145	22	42	8	83.2	LICENCE
5	1	1	1	2	1	31	62	34	8	85.2	ISSUED
5	1	1	1	2	2	68	62	11	8	95.7	BY
5	1	1	1	2	3	82	62	58	8	85.1	TELANGANA
5	1	1	1	3	1	31	102	30	8	57.4	DLNO
5	1	1	1	3	2	65	102	96	8	75.0	TG00420260003084
5	1	1	1	4	1	31	142	29	8	76.2	NAME
5	1	1	1	4	2	65	142	55	8	88.0	KOTHURU
5	1	1	1	4	3	124	142	48	8	85.0	CHARAN
5	1	1	1	5	1	31	182	20	8	60.0	S/O
5	1	1	1	5	2	55	182	55	8	88.0	KOTHURU
5	1	1	1	5	3	114	182	50	8	82.0	KISHORE
5	1	1	1	6	1	31	222	25	8	78.0	DOB
5	1	1	1	6	2	60	222	65	8	88.0	08-10-2006
5	1	1	1	7	1	31	262	35	8	80.0	ISSUE
5	1	1	1	7	2	70	262	30	8	80.0	DATE
5	1	1	1	7	3	105	262	65	8	85.0	11-06-2026
5	1	1	1	8	1	31	302	45	8	85.0	VALIDITY
5	1	1	1	8	2	80	302	65	8	85.0	07-10-2046
5	1	1	1	9	1	31	342	50	8	80.0	HOLDER'S
5	1	1	1	9	2	85	342	60	8	80.0	SIGNATURE`;

const words = [];
const lines = [];
const tsvLines = tsvText.split("\n");

let currentLineNum = -1;
let currentLineWords = [];

for (let i = 1; i < tsvLines.length; i++) {
  const parts = tsvLines[i].split("\t");
  if (parts.length >= 12) {
    const text = parts[11].trim();
    const conf = parseFloat(parts[10]);
    const lineNum = parseInt(parts[4]);
    if (text) {
      words.push({
        text,
        confidence: conf,
        lineNum,
        bbox: {
          x0: parseInt(parts[6]),
          y0: parseInt(parts[7]),
          x1: parseInt(parts[6]) + parseInt(parts[8]),
          y1: parseInt(parts[7]) + parseInt(parts[9])
        }
      });

      if (lineNum !== currentLineNum) {
        if (currentLineWords.length > 0) lines.push(currentLineWords.join(" "));
        currentLineWords = [text];
        currentLineNum = lineNum;
      } else {
        currentLineWords.push(text);
      }
    }
  }
}
if (currentLineWords.length > 0) lines.push(currentLineWords.join(" "));

console.log("Reconstructed Lines:", lines);
const fullText = lines.join("\n");

const result = parseDrivingLicence(words, lines, fullText);
console.log("\n=== PARSED DRIVING LICENCE RESULT ===");
console.log(JSON.stringify(result, null, 2));
