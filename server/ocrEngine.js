// server/ocrEngine.js

import { createWorker } from 'tesseract.js';
import { processInputFile, generateRotationVariants } from './preprocessing.js';

import { extractUniversalFields } from './fieldExtractor.js';

import { parseDrivingLicence } from './parsers/dlParser.js';
import { parsePassport } from './parsers/passportParser.js';
import { parseVisa } from './parsers/visaParser.js';
import { parseNationalId } from './parsers/aadhaarParser.js';
import { parsePAN } from './parsers/panParser.js';
import { parseVoterId } from './parsers/voterIdParser.js';

import { parseGenericDocument } from './genericParser.js';
import { runAadhaarAddressOCR } from './aadhaarAddressOCR.js';
import { validateDocumentModule2 } from './validators.js';

let sharedWorker = null;

// =========================================================
// TESSERACT WORKER SINGLETON & PRE-WARMING
// =========================================================

export async function initTesseractWorker() {
  if (!sharedWorker) {
    console.log('[OCR Engine]: Pre-warming and initializing shared Tesseract OCR Worker...');
    sharedWorker = await createWorker('eng');
    console.log('[OCR Engine]: Shared Tesseract OCR Worker initialized successfully.');
  }
  return sharedWorker;
}

async function getWorker() {
  return await initTesseractWorker();
}

// =========================================================
// TESSERACT HEALTH CHECK
// =========================================================

export async function runTesseractHealthCheck() {

  const startTime =
    Date.now();

  try {

    const worker =
      await getWorker();

    const fs =
      await import('fs');

    const path =
      await import('path');

    const testPath =
      path.resolve(
        'server/test_dl.png'
      );

    let testBuf;

    if (fs.existsSync(testPath)) {

      testBuf =
        fs.readFileSync(testPath);

    } else {

      testBuf =
        Buffer.from(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
          'base64'
        );
    }

    const res =
      await worker.recognize(
        testBuf,
        {},
        {
          text: true,
          tsv: true
        }
      );

    const text =
      (res.data.text || '').trim();

    return {

      status: 'HEALTHY',

      engine:
        'Tesseract.js WebAssembly',

      diagnosticSnippet:
        text.substring(0, 100),

      durationMs:
        Date.now() - startTime,

      timestamp:
        new Date().toISOString()
    };

  } catch (err) {

    console.error(
      '[Tesseract Health Check Failed]:',
      err.message
    );

    return {

      status: 'ERROR',

      engine:
        'Tesseract.js WebAssembly',

      error:
        err.message,

      durationMs:
        Date.now() - startTime,

      timestamp:
        new Date().toISOString()
    };
  }
}

// =========================================================
// DOCUMENT CLASSIFICATION
// =========================================================

export function classifyDocument(rawText = '') {
  const upper = rawText.toUpperCase();

  // -------------------------------------------------------
  // 1. VISA (Check before Passport because Visas state 'Passport No')
  // -------------------------------------------------------
  if (
    upper.includes('ENTRY VISA') ||
    upper.includes('VISA NO') ||
    upper.includes('VISA NUMBER') ||
    upper.includes('IMMIGRATION VISA') ||
    upper.includes('IMMIGRATION ENTRY PERMIT') ||
    upper.includes('DURATION OF STAY') ||
    upper.includes('VISA TYPE') ||
    upper.includes('VALID FOR PRESENTATION') ||
    /\bV[<(\[{A-Z][A-Z0-9<]{10,}/.test(upper) ||
    (upper.includes('VISA') && (upper.includes('ENTRIES') || upper.includes('SINGLE') || upper.includes('MULTIPLE')))
  ) {
    return 'Visa';
  }

  // -------------------------------------------------------
  // 2. PASSPORT
  // -------------------------------------------------------
  if (
    upper.includes('PASSPORT') ||
    upper.includes('PASSEPORT') ||
    upper.includes('TRAVEL DOCUMENT') ||
    upper.includes('REPUBLIC OF INDIA PASSPORT') ||
    upper.includes('UNITED STATES OF AMERICA') ||
    upper.includes('TYPE P') ||
    upper.includes('TYPE/TYPE P') ||
    /\bP[<(\[{A-Z][A-Z0-9<]{10,}/.test(upper) ||
    upper.includes('MINISTRY OF EXTERNAL AFFAIRS')
  ) {
    return 'Passport';
  }

  // -------------------------------------------------------
  // 3. DRIVING LICENCE
  // -------------------------------------------------------
  if (
    upper.includes('DRIVING LICENCE') ||
    upper.includes('DRIVING LICENSE') ||
    upper.includes('LICENCE TO DRIVE') ||
    upper.includes('LICENCE NO') ||
    upper.includes('DL NO') ||
    upper.includes('DLNO') ||
    upper.includes('TRANSPORT DEPARTMENT') ||
    upper.includes('FORM 7') ||
    upper.includes('COV') ||
    upper.includes('SARATHI') ||
    upper.includes('MOTOR VEHICLES') ||
    upper.includes('NON-TRANSPORT') ||
    upper.includes('AUTHORITY TO DRIVE') ||
    /\b[A-Z]{2}[- /]?[0-9]{2,4}[- /]?[0-9]{4}[- /]?[0-9]{4,8}\b/.test(upper) ||
    /\bDL[- /]?[0-9]{11,15}\b/.test(upper)
  ) {
    return 'Indian Driving Licence';
  }

  // -------------------------------------------------------
  // 4. AADHAAR
  // -------------------------------------------------------
  if (
    upper.includes('AADHAAR') ||
    upper.includes('UIDAI') ||
    upper.includes('UNIQUE IDENTIFICATION') ||
    upper.includes('MERA AADHAAR') ||
    upper.includes('ENROLMENT NO') ||
    /\bVID\s*:\s*\d{4}\b/.test(upper) ||
    /\b\d{4}\s\d{4}\s\d{4}\b/.test(upper)
  ) {
    return 'Aadhaar';
  }

  // -------------------------------------------------------
  // 5. PAN CARD
  // -------------------------------------------------------
  if (
    upper.includes('INCOME TAX DEPARTMENT') ||
    upper.includes('PERMANENT ACCOUNT NUMBER') ||
    upper.includes('PAN CARD') ||
    /\b[A-Z]{5}[0-9]{4}[A-Z]\b/.test(upper)
  ) {
    return 'PAN Card';
  }

  // -------------------------------------------------------
  // 6. VOTER ID (EPIC)
  // -------------------------------------------------------
  if (
    upper.includes('ELECTION COMMISSION') ||
    upper.includes('VOTER ID') ||
    upper.includes('ELECTOR PHOTO IDENTITY') ||
    upper.includes('ELECTOR PHOTO IDENTITY CARD') ||
    upper.includes('EPIC NO') ||
    /\b[A-Z]{3}[0-9]{7}\b/.test(upper)
  ) {
    return 'Voter ID';
  }

  // -------------------------------------------------------
  // 7. GOVERNMENT ID / NATIONAL ID
  // -------------------------------------------------------
  if (
    upper.includes('NATIONAL ID') ||
    upper.includes('NATIONAL IDENTITY') ||
    upper.includes('IDENTITY CARD') ||
    upper.includes('IDENTIFICATION CARD') ||
    upper.includes('GOVERNMENT OF INDIA') ||
    upper.includes('GOVT OF INDIA') ||
    upper.includes('RESIDENT CARD') ||
    upper.includes('EMIRATES ID')
  ) {
    return 'Government ID';
  }

  return 'Unknown Document';
}

// =========================================================
// MAIN OCR PROCESSING
// =========================================================

export async function processUploadedDocument(
  inputSource,
  mimeType = '',
  backInputSource = null,
  submittedDocumentType = null
) {
  const tTotalStart = Date.now();
  let tPreprocessMs = 0;
  let tOcrMs = 0;
  let tClassifyMs = 0;
  let tExtractMs = 0;
  let tValidationMs = 0;

  let rawText = '';
  let words = [];
  let lines = [];
  let bestVariantName = 'Original Upload (Raw)';
  let averageConfidence = 0;
  let errors = [];
  let bestVariantBuffer = null;

  try {
    let strContent = '';
    if (Buffer.isBuffer(inputSource)) {
      strContent = inputSource.toString('utf8');
    } else if (typeof inputSource === 'string') {
      strContent = inputSource;
    }

    // =====================================================
    // SVG TEXT VECTOR EXTRACTION (<10ms)
    // =====================================================
    if (
      strContent.includes('<svg') ||
      strContent.includes('image/svg+xml') ||
      strContent.includes('%3Csvg')
    ) {
      console.log('[OCR Pipeline]: Processing SVG Text Vector Source...');
      bestVariantName = 'SVG Vector Extraction';

      let decodedSvg = strContent;
      if (decodedSvg.includes('%3C') || decodedSvg.includes('%20')) {
        try { decodedSvg = decodeURIComponent(decodedSvg); } catch (e) {}
      }
      decodedSvg = decodedSvg.replace(/^data:image\/svg\+xml;utf8,/, '');

      const textMatches = Array.from(decodedSvg.matchAll(/<text[^>]*>([\s\S]*?)<\/text>/gi));
      if (textMatches.length > 0) {
        lines = textMatches
          .map(m => m[1].replace(/<[^>]+>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').trim())
          .filter(Boolean);
        rawText = lines.join('\n');
      } else {
        rawText = decodedSvg
          .replace(/<\/?svg[^>]*>/gi, '')
          .replace(/<text[^>]*>/gi, '\n')
          .replace(/<\/text>/gi, '')
          .replace(/&lt;/g, '<')
          .replace(/&gt;/g, '>')
          .replace(/&amp;/g, '&')
          .trim();
        lines = rawText.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
      }

      words = rawText
        .split(/\s+/)
        .filter(Boolean)
        .map((word, index) => ({
          text: word,
          confidence: 92,
          lineNum: index,
          bbox: {
            x0: index * 10,
            y0: 10,
            x1: index * 10 + 30,
            y1: 30
          }
        }));

      averageConfidence = 92;
    }

    // =====================================================
    // PDF / IMAGE
    // =====================================================
    else {
      const tPreStart = Date.now();
      const prepResult = await processInputFile(inputSource, mimeType);
      tPreprocessMs = Date.now() - tPreStart;

      // PDF PROCESSING
      if (prepResult.isPDF) {
        if (prepResult.pdfText && prepResult.pdfText.trim().length > 0) {
          bestVariantName = 'PDF Native Text Engine';
          rawText = prepResult.pdfText.trim();
          lines = rawText.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
          words = rawText.split(/\s+/).filter(Boolean).map((word, index) => ({
            text: word,
            confidence: 95,
            lineNum: index,
            bbox: { x0: index * 10, y0: 10, x1: index * 10 + 30, y1: 30 }
          }));
          averageConfidence = 95;
        } else if (prepResult.pdfImages && prepResult.pdfImages.length > 0) {
          console.log(`[OCR Pipeline]: PDF contains ${prepResult.pdfImages.length} embedded images. Running image OCR on primary image...`);
          return await processUploadedDocument(prepResult.pdfImages[0], 'image/png');
        } else {
          return {
            success: false,
            documentType: 'Not detected',
            fields: { 'Document Type': 'Not detected', Status: 'Uploaded PDF has no selectable text and no readable images.' },
            rawOcrText: '',
            processingStatus: 'PDF_EMPTY_OR_UNREADABLE',
            metadata: { preprocessingVariant: 'PDF Inspection', wordCount: 0, averageConfidence: 0 },
            errors: ['The uploaded PDF contains no digital text or extractable document images.']
          };
        }
      }

      // ===================================================
      // IMAGE OCR (FAST SINGLE-PASS WITH EARLY STOPPING)
      // ===================================================
      else {
        const tOcrStart = Date.now();
        const worker = await getWorker();

        // Quality scoring helper to eliminate noise
        const evaluateTextQuality = (txt, wordList = []) => {
          if (!txt || !txt.trim()) return { meaningfulWords: 0, alphaRatio: 0, score: 0 };
          const rawW = wordList.length > 0 ? wordList.map(w => w.text) : txt.split(/\s+/).filter(Boolean);
          const meaningfulWords = rawW.filter(w => w.length >= 3 && /[A-Za-z0-9]/.test(w) && !/^[^A-Za-z0-9]+$/.test(w)).length;
          const alphaCount = (txt.match(/[a-zA-Z0-9]/g) || []).length;
          const alphaRatio = alphaCount / (txt.length || 1);
          const score = meaningfulWords * (alphaRatio >= 0.45 ? 1.5 : 0.4);
          return { meaningfulWords, alphaRatio, score };
        };

        const parseOcrOutput = (ocrRes) => {
          const data = ocrRes.data;
          const tsvLines = (data.tsv || '').split('\n');
          const variantWords = [];
          for (let i = 1; i < tsvLines.length; i++) {
            const parts = tsvLines[i].split('\t');
            if (parts.length >= 12) {
              const text = parts[11].trim();
              const confidence = parseFloat(parts[10]);
              const lineNum = parseInt(parts[4]);
              if (text && confidence >= 0) {
                variantWords.push({
                  text,
                  confidence,
                  lineNum,
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
          const q = evaluateTextQuality(data.text || '', variantWords);
          return { words: variantWords, text: data.text || '', quality: q };
        };

        let bestWordCount = -1;
        let bestMeaningfulWords = -1;
        let bestScore = -1;

        // Pass 1: Primary Preprocessed Image (Target 1400px width)
        const primaryVariant = (prepResult.variants && prepResult.variants[0]) || {
          name: "Optimized Original",
          buffer: prepResult.primaryBuffer || inputSource
        };

        console.log(`[OCR Pipeline]: Evaluating Primary Variant "${primaryVariant.name}" (${primaryVariant.buffer.length} bytes)...`);
        const primaryRes = await worker.recognize(primaryVariant.buffer, {}, { text: true, blocks: true, tsv: true });
        const primaryParsed = parseOcrOutput(primaryRes);

        bestScore = primaryParsed.quality.score;
        bestWordCount = primaryParsed.words.length;
        bestMeaningfulWords = primaryParsed.quality.meaningfulWords;
        rawText = primaryParsed.text;
        words = primaryParsed.words;
        bestVariantName = primaryVariant.name;
        bestVariantBuffer = primaryVariant.buffer;

        console.log(`[OCR Pipeline]: Primary Variant detected ${primaryParsed.words.length} words (${primaryParsed.quality.meaningfulWords} meaningful), score: ${primaryParsed.quality.score.toFixed(1)}`);

        // EARLY STOPPING CHECK:
        // If Variant 1 yields high-quality document text (>= 8 meaningful words, score >= 5.0, alpha ratio >= 0.40),
        // we stop IMMEDIATELY! This eliminates 3 redundant passes (~45s saved).
        const isHighQuality = primaryParsed.quality.meaningfulWords >= 8 && primaryParsed.quality.score >= 5.0 && primaryParsed.quality.alphaRatio >= 0.40;

        if (isHighQuality) {
          console.log(`[OCR Pipeline]: [FAST PATH] High quality text detected on primary pass (${primaryParsed.quality.meaningfulWords} meaningful words). Skipping fallback variants.`);
        } else if (typeof prepResult.getVariant === 'function') {
          // Fallback: lazily evaluate additional variants ONLY when primary pass was low quality
          console.log(`[OCR Pipeline]: Primary text quality low (${primaryParsed.quality.meaningfulWords} words). Trying fallback preprocessing variants...`);
          for (let vIdx = 1; vIdx <= 3; vIdx++) {
            const fallbackVar = await prepResult.getVariant(vIdx);
            if (!fallbackVar) continue;
            console.log(`[OCR Pipeline]: Evaluating Fallback Variant "${fallbackVar.name}"...`);
            try {
              const res = await worker.recognize(fallbackVar.buffer, {}, { text: true, blocks: true, tsv: true });
              const parsed = parseOcrOutput(res);
              console.log(`[OCR Pipeline]: Fallback "${fallbackVar.name}" detected ${parsed.words.length} words (${parsed.quality.meaningfulWords} meaningful), score: ${parsed.quality.score.toFixed(1)}`);
              if (parsed.quality.score > bestScore) {
                bestScore = parsed.quality.score;
                bestWordCount = parsed.words.length;
                bestMeaningfulWords = parsed.quality.meaningfulWords;
                rawText = parsed.text;
                words = parsed.words;
                bestVariantName = fallbackVar.name;
                bestVariantBuffer = fallbackVar.buffer;
              }
              if (parsed.quality.meaningfulWords >= 8 && parsed.quality.score >= 5.0) {
                console.log(`[OCR Pipeline]: Fallback variant "${fallbackVar.name}" achieved good quality. Early stopping.`);
                break;
              }
            } catch (vErr) {
              console.warn(`[OCR Pipeline Warning]: Fallback variant error:`, vErr.message);
            }
          }
        }

        // AUTO-ORIENTATION RESCUE (90°, 180°, 270°)
        // Only if upright variants detected < 6 meaningful words (e.g. phone photo upside down)
        if ((bestMeaningfulWords < 6 || bestScore < 4.0) && Buffer.isBuffer(inputSource)) {
          console.log(`[OCR Pipeline]: Low quality score (${bestScore.toFixed(1)}) on upright variants. Evaluating auto-rotation...`);
          try {
            const rotVariants = await generateRotationVariants(inputSource);
            for (const rotVariant of rotVariants) {
              const rotRes = await worker.recognize(rotVariant.buffer, {}, { text: true, blocks: true, tsv: true });
              const rotParsed = parseOcrOutput(rotRes);
              if (rotParsed.quality.score > bestScore) {
                console.log(`[OCR Pipeline]: Rotation "${rotVariant.name}" rescued document!`);
                bestScore = rotParsed.quality.score;
                bestWordCount = rotParsed.words.length;
                bestMeaningfulWords = rotParsed.quality.meaningfulWords;
                rawText = rotParsed.text;
                words = rotParsed.words;
                bestVariantName = rotVariant.name;
                bestVariantBuffer = rotVariant.buffer;
              }
            }
          } catch (rotErr) {
            console.warn('[OCR Pipeline Warning]: Rotation evaluation error:', rotErr.message);
          }
        }

        // SPARSE TEXT SEGMENTATION (PSM 11)
        // Only if meaningful words is still < 5
        if (bestMeaningfulWords < 5 && bestVariantBuffer) {
          console.log('[OCR Pipeline]: Evaluating PSM 11 for sparse layout...');
          try {
            await worker.setParameters({ tessedit_pageseg_mode: '11' });
            const psmRes = await worker.recognize(bestVariantBuffer, {}, { text: true, blocks: true, tsv: true });
            const psmParsed = parseOcrOutput(psmRes);
            if (psmParsed.quality.score > bestScore) {
              bestScore = psmParsed.quality.score;
              bestWordCount = psmParsed.words.length;
              bestMeaningfulWords = psmParsed.quality.meaningfulWords;
              rawText = psmParsed.text;
              words = psmParsed.words;
              bestVariantName += ' (Sparse PSM 11)';
            }
            await worker.setParameters({ tessedit_pageseg_mode: '3' });
          } catch (psmErr) {
            console.warn('[OCR Pipeline Warning]: PSM 11 error:', psmErr.message);
            try { await worker.setParameters({ tessedit_pageseg_mode: '3' }); } catch (e) {}
          }
        }

        tOcrMs = Date.now() - tOcrStart;

        lines = rawText ? rawText.split(/\r?\n/).map(line => line.trim()).filter(Boolean) : [];
        if (words.length > 0) {
          const totalConfidence = words.reduce((sum, word) => sum + word.confidence, 0);
          averageConfidence = Math.round(totalConfidence / words.length);
        } else {
          averageConfidence = 0;
        }
      }
    }
  } catch (err) {
    console.error('[OCR Pipeline Execution Error]:', err.message);
    errors.push(`OCR Execution Error: ${err.message}`);
    averageConfidence = 0;
  }

  // =========================================================
  // DOCUMENT CLASSIFICATION (<1ms)
  // =========================================================
  const tClassifyStart = Date.now();
  const documentType = classifyDocument(rawText);
  tClassifyMs = Date.now() - tClassifyStart;

  // =========================================================
  // FIELD EXTRACTION (<5ms)
  // =========================================================
  const tExtractStart = Date.now();
  const universalFields = extractUniversalFields(words, rawText);

  // Failure early exit
  if (words.length === 0 && (!rawText || !rawText.trim())) {
    return {
      success: false,
      documentType: 'Not detected',
      fields: { 'Document Type': 'Not detected', Status: 'OCR returned 0 words.' },
      rawOcrText: '',
      processingStatus: 'OCR_FAILED_NO_TEXT_DETECTED',
      checksum_validation: null,
      metadata: { preprocessingVariant: bestVariantName, wordCount: 0, averageConfidence: 0 },
      errors: ['No readable text or characters detected in the uploaded image.']
    };
  }

  // Dedicated Aadhaar Address OCR (runs only for Aadhaar cards with text)
  let aadhaarAddressOCRText = '';
  if (documentType === 'Aadhaar' && bestVariantBuffer && words.length > 0) {
    try {
      const worker = await getWorker();
      aadhaarAddressOCRText = await runAadhaarAddressOCR(bestVariantBuffer, words, worker);
    } catch (addressError) {
      console.warn('[OCR Pipeline]: Aadhaar Address OCR skipped:', addressError.message);
    }
  }

  let extractedFields = {};
  switch (documentType) {
    case 'Indian Driving Licence':
      extractedFields = parseDrivingLicence(words, lines, rawText);
      break;
    case 'Passport':
      extractedFields = parsePassport(words, lines, rawText);
      break;
    case 'Visa':
      extractedFields = parseVisa(words, lines, rawText);
      break;
    case 'Aadhaar':
      extractedFields = parseNationalId(words, lines, rawText, aadhaarAddressOCRText);
      if ((!extractedFields.Address || extractedFields.Address === 'Not detected') && backInputSource) {
        try {
          const worker = await getWorker();
          const backPrep = await processInputFile(backInputSource, 'image/png');
          const backBuf = (backPrep.variants && backPrep.variants[0]?.buffer) || backPrep.primaryBuffer || backInputSource;
          const backRes = await worker.recognize(backBuf, {}, { text: true });
          const backLines = (backRes.data.text || '').split(/\r?\n/).map(l => l.trim()).filter(Boolean);
          const backParsed = parseNationalId([], backLines, backRes.data.text || '', '');
          if (backParsed.Address && backParsed.Address !== 'Not detected') {
            extractedFields.Address = backParsed.Address;
          }
        } catch (e) {
          console.warn('[OCR Pipeline]: Back image address extraction skipped:', e.message);
        }
      }
      break;
    case 'PAN Card':
      extractedFields = parsePAN(words, lines, rawText);
      break;
    case 'Voter ID':
      extractedFields = parseVoterId(words, lines, rawText);
      break;
    case 'Government ID':
    case 'Unknown Document':
    default:
      extractedFields = parseGenericDocument(words, lines, rawText, documentType);
      break;
  }

  // Merge: Document-specific parser priority over universal fields
  const panDisallowed = ['Address', 'Nationality', 'Gender'];
  const isGeneric = documentType === 'Government ID' || documentType === 'Unknown Document';
  for (const [key, val] of Object.entries(universalFields)) {
    if (documentType === 'PAN Card' && panDisallowed.includes(key)) continue;
    if (isGeneric || key in extractedFields) {
      if ((!extractedFields[key] || extractedFields[key] === "Not detected") && val && val !== "Not detected") {
        extractedFields[key] = val;
      }
    }
  }

  // Explicitly mark uncarried fields as 'not applicable for this document type'
  if (documentType === 'PAN Card') {
    extractedFields['Date of Expiry'] = 'not applicable for this document type';
    extractedFields['Expiry Date'] = 'not applicable for this document type';
    extractedFields['Address'] = 'not applicable for this document type';
    extractedFields['Gender'] = 'not applicable for this document type';
    extractedFields['Nationality'] = 'not applicable for this document type';
    extractedFields['MRZ Line 1'] = 'not applicable for this document type';
    extractedFields['MRZ Line 2'] = 'not applicable for this document type';
  } else if (documentType === 'Aadhaar') {
    extractedFields['Date of Expiry'] = 'not applicable for this document type';
    extractedFields['Expiry Date'] = 'not applicable for this document type';
    extractedFields['Nationality'] = 'not applicable for this document type';
    extractedFields['MRZ Line 1'] = 'not applicable for this document type';
    extractedFields['MRZ Line 2'] = 'not applicable for this document type';
  } else if (documentType === 'Indian Driving Licence') {
    extractedFields['Nationality'] = 'not applicable for this document type';
    extractedFields['MRZ Line 1'] = 'not applicable for this document type';
    extractedFields['MRZ Line 2'] = 'not applicable for this document type';
  } else if (documentType === 'Passport') {
    if (!extractedFields['Address'] || extractedFields['Address'] === 'Not detected') {
      extractedFields['Address'] = 'not applicable for this document type';
    }
  }

  tExtractMs = Date.now() - tExtractStart;

  // Type mismatch check if submittedDocumentType is provided
  let typeMismatchWarning = null;
  if (submittedDocumentType && submittedDocumentType !== 'auto' && submittedDocumentType !== 'unknown') {
    const normSub = submittedDocumentType.toLowerCase().replace(/[^a-z]/g, '');
    const normDet = documentType.toLowerCase().replace(/[^a-z]/g, '');
    const isSubPassport = normSub.includes('passport');
    const isDetPassport = normDet.includes('passport');
    const isSubAadhaar = normSub.includes('aadhaar');
    const isDetAadhaar = normDet.includes('aadhaar');
    const isSubPan = normSub.includes('pan');
    const isDetPan = normDet.includes('pan');
    const isSubDl = normSub.includes('driving') || normSub.includes('dl');
    const isDetDl = normDet.includes('driving') || normDet.includes('dl');

    const matches = (isSubPassport && isDetPassport) ||
                    (isSubAadhaar && isDetAadhaar) ||
                    (isSubPan && isDetPan) ||
                    (isSubDl && isDetDl) ||
                    (normSub === normDet);

    if (!matches && documentType !== 'Unknown Document') {
      const subLabel = isSubPassport ? 'Passport' : isSubAadhaar ? 'Aadhaar' : isSubPan ? 'PAN' : isSubDl ? 'Driving Licence' : submittedDocumentType;
      const detLabel = isDetPassport ? 'Passport' : isDetAadhaar ? 'Aadhaar' : isDetPan ? 'PAN' : isDetDl ? 'Driving Licence' : documentType;
      typeMismatchWarning = `Type mismatch — tab set to ${subLabel}, document detected as ${detLabel}. Analysing as ${detLabel}.`;
      console.warn(`[OCR Pipeline Warning]: ${typeMismatchWarning}`);
    }
  }

  // =========================================================
  // MODULE 2 VALIDATION (<1ms)
  // =========================================================
  const tValStart = Date.now();

  const validationResult = validateDocumentModule2(documentType, extractedFields, rawText);

  tValidationMs = Date.now() - tValStart;
  const tTotalMs = Date.now() - tTotalStart;

  // =========================================================
  // EXACT PERFORMANCE LOGGING [PERF]
  // =========================================================
  console.log(`[PERF] Image preprocessing: ${tPreprocessMs} ms`);
  console.log(`[PERF] OCR: ${tOcrMs} ms`);
  console.log(`[PERF] Document classification: ${tClassifyMs} ms`);
  console.log(`[PERF] Field extraction: ${tExtractMs} ms`);
  console.log(`[PERF] Validation: ${tValidationMs} ms`);
  console.log(`[PERF] Total: ${tTotalMs} ms`);

  // =========================================================
  // FINAL RETURN
  // =========================================================
  return {
    success: true,
    documentType,
    fields: extractedFields,
    rawOcrText: rawText,
    processingStatus: documentType !== 'Unknown Document'
      ? (validationResult.validation_passed ? 'SUCCESS' : 'VALIDATION_WARNING')
      : 'DOCUMENT_TYPE_UNCERTAIN',
    checksum_validation: validationResult.checksum_validation,
    validation: validationResult,
    type_mismatch_warning: typeMismatchWarning,
    metadata: {
      preprocessingVariant: bestVariantName,
      wordCount: words.length,
      averageConfidence: averageConfidence,
      perfTimings: {
        preprocessingMs: tPreprocessMs,
        ocrMs: tOcrMs,
        classificationMs: tClassifyMs,
        extractionMs: tExtractMs,
        validationMs: tValidationMs,
        totalMs: tTotalMs
      }
    },
    errors: [
      ...errors,
      ...validationResult.missing_required.map(f => `Missing required field: ${f}`),
      ...validationResult.format_errors,
      ...validationResult.date_errors
    ]
  };
}