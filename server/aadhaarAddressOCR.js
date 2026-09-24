import { Jimp } from 'jimp';
import { PSM } from 'tesseract.js';

/**
 * =========================================================
 * AADHAAR ADDRESS REGION OCR
 * =========================================================
 *
 * Uses the OCR bounding box of "Address" to locate the
 * address section, crops that region, enhances it and
 * performs a second OCR pass.
 */

export async function runAadhaarAddressOCR(
  imageBuffer,
  words,
  worker
) {
  try {

    if (!Buffer.isBuffer(imageBuffer)) {
      return '';
    }

    if (!Array.isArray(words) || words.length === 0) {
      return '';
    }

    /**
     * Find the "Address" OCR word.
     */
    const addressWord = words.find(word => {
      const text = String(word.text || '')
        .toUpperCase()
        .replace(/[^A-Z]/g, '');

      return (
        text === 'ADDRESS' ||
        text.includes('ADDRESS')
      );
    });

    if (!addressWord?.bbox) {
      console.log(
        '[Aadhaar Address OCR] Address label not found.'
      );

      return '';
    }

    /**
     * Load original image.
     */
    const image = await Jimp.read(imageBuffer);

    const imageWidth = image.width;
    const imageHeight = image.height;

    const labelX = Math.max(
      0,
      Math.floor(addressWord.bbox.x0)
    );

    const labelY = Math.max(
      0,
      Math.floor(addressWord.bbox.y0)
    );

    /**
     * Aadhaar address is normally below the
     * "Address:" label.
     *
     * We deliberately keep the crop toward the
     * left side so the QR code does not interfere.
     */
    const cropX = Math.max(
      0,
      labelX - 20
    );

    const cropY = Math.max(
      0,
      labelY - 10
    );

    const maxRight =
      Math.floor(imageWidth * 0.72);

    const cropWidth = Math.min(
      imageWidth - cropX,
      Math.max(300, maxRight - cropX)
    );

    const cropHeight = Math.min(
      imageHeight - cropY,
      300
    );

    if (
      cropWidth < 100 ||
      cropHeight < 50
    ) {
      console.log(
        '[Aadhaar Address OCR] Crop region too small.'
      );

      return '';
    }

    console.log(
      `[Aadhaar Address OCR] Crop: x=${cropX}, y=${cropY}, w=${cropWidth}, h=${cropHeight}`
    );

    /**
     * =====================================================
     * CREATE ENHANCED ADDRESS CROP
     * =====================================================
     */

    const crop = image
      .clone()
      .crop({
        x: cropX,
        y: cropY,
        w: cropWidth,
        h: cropHeight
      });

    // Upscale for better OCR
    crop.resize({
      w: cropWidth * 2,
      h: cropHeight * 2
    });

    // Remove Aadhaar background colours
    crop.greyscale();

    // Increase contrast
    crop.contrast(0.45);

    const enhancedBuffer =
      await crop.getBuffer('image/png');

    /**
     * =====================================================
     * OCR PASS 1 - SINGLE BLOCK
     * =====================================================
     */

    await worker.setParameters({
      tessedit_pageseg_mode: PSM.SINGLE_BLOCK,
      preserve_interword_spaces: '1'
    });

    const result1 =
      await worker.recognize(
        enhancedBuffer,
        {},
        { text: true }
      );

    const text1 =
      (result1.data.text || '').trim();

    /**
     * =====================================================
     * OCR PASS 2 - SPARSE TEXT
     * =====================================================
     */

    await worker.setParameters({
      tessedit_pageseg_mode: PSM.SPARSE_TEXT,
      preserve_interword_spaces: '1'
    });

    const result2 =
      await worker.recognize(
        enhancedBuffer,
        {},
        { text: true }
      );

    const text2 =
      (result2.data.text || '').trim();

    /**
     * Choose the better result.
     *
     * Prefer the result containing a PIN code.
     */
    const hasPin1 =
      /\b\d{6}\b/.test(text1);

    const hasPin2 =
      /\b\d{6}\b/.test(text2);

    let bestText = text1;

    if (hasPin2 && !hasPin1) {
      bestText = text2;
    } else if (
      text2.length > text1.length &&
      !hasPin1
    ) {
      bestText = text2;
    }

    console.log(
      '[Aadhaar Address OCR] Pass 1:',
      text1
    );

    console.log(
      '[Aadhaar Address OCR] Pass 2:',
      text2
    );

    console.log(
      '[Aadhaar Address OCR] Selected:',
      bestText
    );

    return bestText;

  } catch (error) {

    console.error(
      '[Aadhaar Address OCR Error]:',
      error.message
    );

    return '';
  }
}