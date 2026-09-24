import { Jimp } from 'jimp';

/**
 * Image & Document Preprocessing Pipeline.
 * Creates multiple preprocessing variants (Raw, Grayscale + Normalized, High-Contrast Binarized, Dark-Mode Inverted)
 * and provides dynamic rotation evaluation (90°, 180°, 270°) to ensure universally accurate OCR.
 */

export async function processInputFile(inputBuffer, mimeType = '') {
  // 1. Handle PDF input
  if (mimeType === 'application/pdf' || isPDFBuffer(inputBuffer)) {
    try {
      console.log("[Preprocessing]: PDF input detected. Extracting PDF text & metadata...");
      const { PDFParse } = await import('pdf-parse');
      const parser = new PDFParse({ data: inputBuffer });
      const textResult = await parser.getText();
      const extractedText = (textResult.text || "").trim();

      // Also extract any embedded images from the PDF (for scanned PDFs)
      let extractedImages = [];
      try {
        const imgResult = await parser.getImage({ imageBuffer: true });
        if (imgResult && imgResult.pages) {
          for (const page of imgResult.pages) {
            if (page.images) {
              for (const img of page.images) {
                if (img.data && img.data.length > 1000) {
                  extractedImages.push(Buffer.from(img.data));
                }
              }
            }
          }
        }
      } catch (imgErr) {
        console.warn("[Preprocessing]: PDF image extraction skipped:", imgErr.message);
      }

      await parser.destroy();

      return {
        isPDF: true,
        pdfText: extractedText,
        pdfImages: extractedImages,
        buffer: inputBuffer
      };
    } catch (err) {
      console.warn("[Preprocessing Warning]: PDF text extraction fallback:", err.message);
      return {
        isPDF: true,
        pdfText: "",
        pdfImages: [],
        buffer: inputBuffer,
        error: err.message
      };
    }
  }

  // 2. Generate Primary Upright Image with Resolution Optimization (1400px target)
  let jimpImg = null;
  let primaryBuffer = inputBuffer;

  try {
    jimpImg = await Jimp.read(inputBuffer);
    
    // Target optimal OCR width: 1400px provides crisp character height (~35px)
    // without the massive CPU/RAM penalty of 2400-4000px raw photos.
    if (jimpImg.width > 1600) {
      console.log(`[Preprocessing]: Downscaling image from ${jimpImg.width}px to 1400px for speed optimization...`);
      jimpImg.resize({ w: 1400 });
      primaryBuffer = await jimpImg.getBuffer('image/png');
    } else if (jimpImg.width < 900) {
      console.log(`[Preprocessing]: Upscaling small image from ${jimpImg.width}px to optimal OCR size...`);
      jimpImg.resize({ w: Math.min(1400, Math.round(jimpImg.width * 1.5)) });
      primaryBuffer = await jimpImg.getBuffer('image/png');
    }
  } catch (err) {
    console.warn("[Preprocessing]: Jimp parse note:", err.message);
  }

  // Lazy variant generator — allows early stopping after Variant 1 succeeds
  const getVariant = async (variantIndex) => {
    if (!jimpImg) return null;
    try {
      if (variantIndex === 1) {
        // Variant 2: Grayscale + Auto-Contrast
        const v2 = jimpImg.clone();
        v2.greyscale();
        if (typeof v2.normalize === 'function') v2.normalize();
        v2.contrast(0.25);
        return { name: "Grayscale + Auto-Contrast", buffer: await v2.getBuffer('image/png') };
      } else if (variantIndex === 2) {
        // Variant 3: High-Contrast Binarized
        const v3 = jimpImg.clone();
        v3.greyscale();
        v3.contrast(0.50);
        return { name: "High Contrast Binarized", buffer: await v3.getBuffer('image/png') };
      } else if (variantIndex === 3) {
        // Variant 4: Inverted Contrast
        const v4 = jimpImg.clone();
        v4.greyscale();
        v4.invert();
        v4.contrast(0.35);
        return { name: "Inverted Contrast (Dark Background)", buffer: await v4.getBuffer('image/png') };
      }
    } catch (e) {
      console.warn(`[Preprocessing]: Variant ${variantIndex} generation error:`, e.message);
    }
    return null;
  };

  const variants = [
    { name: "Optimized Original", buffer: primaryBuffer }
  ];

  return {
    isPDF: false,
    primaryBuffer,
    variants,
    getVariant,
    jimpImg
  };
}

/**
 * Generate 90°, 180°, and 270° rotation variants for mobile camera uploads
 * that are sideways or upside-down.
 */
export async function generateRotationVariants(inputBuffer) {
  const rotationVariants = [];
  try {
    const baseImg = await Jimp.read(inputBuffer);

    // Normalize size to max 1400px for speed
    if (baseImg.width > 1600) {
      baseImg.resize({ w: 1400 });
    } else if (baseImg.width < 900) {
      baseImg.resize({ w: Math.min(1400, Math.round(baseImg.width * 1.5)) });
    }

    // 90° Clockwise
    try {
      const r90 = baseImg.clone();
      r90.rotate(90);
      r90.greyscale();
      r90.contrast(0.25);
      const buf90 = await r90.getBuffer('image/png');
      rotationVariants.push({ name: "Auto-Oriented 90° CW", buffer: buf90 });
    } catch (err90) {
      console.warn("[Preprocessing]: 90 deg rotation skipped:", err90.message);
    }

    // 180° Inverted
    try {
      const r180 = baseImg.clone();
      r180.rotate(180);
      r180.greyscale();
      r180.contrast(0.25);
      const buf180 = await r180.getBuffer('image/png');
      rotationVariants.push({ name: "Auto-Oriented 180° Inverted", buffer: buf180 });
    } catch (err180) {
      console.warn("[Preprocessing]: 180 deg rotation skipped:", err180.message);
    }

    // 270° (90° Counter-Clockwise)
    try {
      const r270 = baseImg.clone();
      r270.rotate(270);
      r270.greyscale();
      r270.contrast(0.25);
      const buf270 = await r270.getBuffer('image/png');
      rotationVariants.push({ name: "Auto-Oriented 270° CW", buffer: buf270 });
    } catch (err270) {
      console.warn("[Preprocessing]: 270 deg rotation skipped:", err270.message);
    }

  } catch (err) {
    console.warn("[Preprocessing]: Could not generate rotation variants:", err.message);
  }

  return rotationVariants;
}

function isPDFBuffer(buf) {
  if (!buf || buf.length < 4) return false;
  return buf.toString('ascii', 0, 4) === '%PDF';
}
