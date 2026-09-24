import { createWorker } from 'tesseract.js';
import fs from 'fs';

async function test() {
  console.log("Reading test_dl.png...");
  const imgBuffer = fs.readFileSync('server/test_dl.png');
  console.log("Image size:", imgBuffer.length, "bytes");

  console.log("Initializing Tesseract worker...");
  const worker = await createWorker('eng');

  console.log("Recognizing image with structured output options...");
  const res = await worker.recognize(imgBuffer, {}, { text: true, blocks: true, tsv: true });

  console.log("\n=== RAW OCR TEXT ===");
  console.log(res.data.text);

  console.log("=== OCR OVERALL CONFIDENCE ===");
  console.log(res.data.confidence);

  console.log("\n=== PARSING WORDS FROM TSV ===");
  const tsvLines = (res.data.tsv || "").split("\n");
  const words = [];

  for (let i = 1; i < tsvLines.length; i++) {
    const parts = tsvLines[i].split("\t");
    if (parts.length >= 12) {
      const text = parts[11].trim();
      const conf = parseFloat(parts[10]);
      if (text && conf >= 0) {
        words.push({
          text,
          confidence: conf,
          bbox: {
            x0: parseInt(parts[6]),
            y0: parseInt(parts[7]),
            x1: parseInt(parts[6]) + parseInt(parts[8]),
            y1: parseInt(parts[7]) + parseInt(parts[9])
          }
        });
      }
    }
  }

  console.log("Total words extracted from TSV:", words.length);
  console.log("Sample extracted words:", words.slice(0, 10));

  await worker.terminate();
  console.log("\nOCR Test Completed Successfully!");
}

test().catch(console.error);
