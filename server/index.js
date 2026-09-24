import express from 'express';
import cors from 'cors';
import multer from 'multer';
import { processUploadedDocument, runTesseractHealthCheck, initTesseractWorker } from './ocrEngine.js';

// Process-level crash prevention
process.on('uncaughtException', (err) => {
  console.error('[Process uncaughtException]:', err.message || err);
});
process.on('unhandledRejection', (reason) => {
  console.error('[Process unhandledRejection]:', reason);
});

const app = express();
const PORT = process.env.PORT || 5000;

// Configure CORS and JSON payload parsing
app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true, limit: '50mb' }));

// Multer in-memory storage for JPG/JPEG, PNG, WEBP, and PDF
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 25 * 1024 * 1024 } // 25MB limit
});

// Root endpoint
app.get('/', (req, res) => {
  res.json({
    status: 'ONLINE',
    service: 'SentinelAuth AI OCR & Document Classification API',
    endpoints: {
      health: 'GET /api/health',
      ocrCheck: 'GET /api/ocr-check',
      processDocument: 'POST /api/process-document'
    },
    timestamp: new Date().toISOString()
  });
});

// Health check endpoint
app.get('/api/health', (req, res) => {
  res.json({
    status: 'ONLINE',
    service: 'SentinelAuth AI OCR & Document Processing Service',
    timestamp: new Date().toISOString()
  });
});

// Dedicated OCR Health Check endpoint
app.get('/api/ocr-check', async (req, res) => {
  try {
    const health = await runTesseractHealthCheck();
    res.json(health);
  } catch (err) {
    res.status(500).json({ status: 'ERROR', error: err.message });
  }
});

const uploadFields = upload.fields([
  { name: 'file', maxCount: 1 },
  { name: 'back_image', maxCount: 1 }
]);

// Main Document Processing Endpoint (POST /api/process-document)
app.post('/api/process-document', uploadFields, async (req, res) => {
  try {
    let imageSource = null;
    let backImageSource = null;
    let mimeType = '';

    if (req.files) {
      if (req.files['file'] && req.files['file'][0]) {
        imageSource = req.files['file'][0].buffer;
        mimeType = req.files['file'][0].mimetype || '';
      }
      if (req.files['back_image'] && req.files['back_image'][0]) {
        backImageSource = req.files['back_image'][0].buffer;
      }
    }
    if (!imageSource && req.file) {
      imageSource = req.file.buffer;
      mimeType = req.file.mimetype || '';
    }
    if (!imageSource && req.body && req.body.image) {
      const rawImage = req.body.image;
      if (rawImage.includes('<svg') || rawImage.includes('image/svg+xml')) {
        imageSource = rawImage;
      } else {
        const matchMime = rawImage.match(/^data:(image\/\w+|application\/pdf);base64,/);
        if (matchMime) mimeType = matchMime[1];
        const base64Data = rawImage.replace(/^data:(image\/\w+|application\/pdf);base64,/, '');
        imageSource = Buffer.from(base64Data, 'base64');
      }
      if (req.body.back_image) {
        const rawBack = req.body.back_image;
        const base64Back = rawBack.replace(/^data:(image\/\w+|application\/pdf);base64,/, '');
        backImageSource = Buffer.from(base64Back, 'base64');
      }
    }

    if (!imageSource) {
      return res.status(400).json({
        documentType: "Not detected",
        fields: {},
        rawOcrText: "",
        processingStatus: "FAILED",
        errors: ["No document image file or base64 data provided in request"]
      });
    }

    console.log(`[API Request]: Processing document... (${imageSource.length || imageSource.byteLength} bytes)${backImageSource ? ` + back image (${backImageSource.length || backImageSource.byteLength} bytes)` : ''}`);

    const submittedDocumentType = (req.body && (req.body.submitted_document_type || req.body.submittedDocumentType || req.body.document_type || req.body.tab_type)) || null;
    const result = await processUploadedDocument(imageSource, mimeType, backImageSource, submittedDocumentType);

    return res.json({
      success: result.success,
      documentType: result.documentType,
      fields: result.fields,
      rawOcrText: result.rawOcrText,
      processingStatus: result.processingStatus,
      checksum_validation: result.checksum_validation,
      validation: result.validation,
      type_mismatch_warning: result.type_mismatch_warning,
      metadata: result.metadata,
      errors: result.errors || []
    });

  } catch (error) {
    console.error('[API Error]: Failed to process document:', error);
    return res.status(500).json({
      documentType: "Not detected",
      fields: {},
      rawOcrText: "",
      processingStatus: "ERROR",
      errors: [error.message || 'Failed to extract text from document image']
    });
  }
});

// Explicit 0.0.0.0 binding for IPv4 & IPv6 localhost compatibility
app.listen(PORT, '0.0.0.0', () => {
  console.log(`=======================================================`);
  console.log(`🚀 SentinelAuth AI OCR Server running on port ${PORT} (0.0.0.0)`);
  console.log(`👉 Health check: http://localhost:${PORT}/api/health`);
  console.log(`👉 Endpoint: http://localhost:${PORT}/api/process-document`);
  console.log(`=======================================================`);

  // Pre-warm Tesseract worker at startup so subsequent requests are immediate
  initTesseractWorker().catch(err => {
    console.warn('[Startup Warning]: Tesseract pre-warming error:', err.message);
  });
});
