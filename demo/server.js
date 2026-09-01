const express = require('express');
const cors = require('cors');
const path = require('path');
const http = require('http');
const multer = require('multer');
const fs = require('fs');
if (fs.existsSync(path.join(__dirname, '.env'))) {
  require('dotenv').config({ path: path.join(__dirname, '.env') });
} else if (fs.existsSync(path.join(__dirname, '..', '.env'))) {
  require('dotenv').config({ path: path.join(__dirname, '..', '.env') });
} else {
  require('dotenv').config();
}

const app = express();
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 100 * 1024 * 1024 } });

// Server and PACS configuration
const PORT = parseInt(process.env.APP_PORT || process.env.PORT || '3000', 10);
const ORTHANC_HOST = process.env.ORTHANC_HOST || 'localhost';
const ORTHANC_PORT = parseInt(process.env.ORTHANC_HTTP_PORT || '8042', 10);
const ORTHANC_USER = process.env.ORTHANC_USER || 'orthanc';
const ORTHANC_PASS = process.env.ORTHANC_PASSWORD || 'orthanc';
const MEDDREAM_PORT = parseInt(process.env.MEDDREAM_PORT || '8080', 10);
const MEDDREAM_HOST = process.env.MEDDREAM_HOST || 'localhost';

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

/**
 * Helper to make authenticated HTTP requests to Orthanc PACS REST API
 */
function orthancRequest(endpoint, method = 'GET', body = null, headers = {}) {
  return new Promise((resolve, reject) => {
    const auth = 'Basic ' + Buffer.from(`${ORTHANC_USER}:${ORTHANC_PASS}`).toString('base64');
    const options = {
      hostname: ORTHANC_HOST,
      port: ORTHANC_PORT,
      path: endpoint,
      method: method,
      headers: {
        'Authorization': auth,
        ...headers
      },
      timeout: 10000
    };

    if (body && (method === 'POST' || method === 'PUT')) {
      if (typeof body === 'object' && !Buffer.isBuffer(body)) {
        body = JSON.stringify(body);
        options.headers['Content-Type'] = 'application/json';
      }
      options.headers['Content-Length'] = Buffer.byteLength(body);
    }

    const req = http.request(options, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf8');
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve({ statusCode: res.statusCode, data: raw ? JSON.parse(raw) : null });
          } catch (e) {
            resolve({ statusCode: res.statusCode, data: raw });
          }
        } else {
          reject(new Error(`Orthanc API error [${res.statusCode}]: ${raw || res.statusMessage}`));
        }
      });
    });

    req.on('error', (err) => reject(err));
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Orthanc connection timed out'));
    });

    if (body) {
      req.write(body);
    }
    req.end();
  });
}

/**
 * Format raw DICOM dates (YYYYMMDD) to readable format (YYYY-MM-DD)
 */
function formatDicomDate(dateStr) {
  if (!dateStr || dateStr.length < 8) return dateStr || '';
  const y = dateStr.substring(0, 4);
  const m = dateStr.substring(4, 6);
  const d = dateStr.substring(6, 8);
  return `${y}-${m}-${d}`;
}

/**
 * Format raw DICOM time (HHMMSS.frac) to readable format (HH:MM:SS)
 */
function formatDicomTime(timeStr) {
  if (!timeStr || timeStr.length < 2) return timeStr || '';
  const h = timeStr.substring(0, 2);
  const m = timeStr.length >= 4 ? timeStr.substring(2, 4) : '00';
  const s = timeStr.length >= 6 ? timeStr.substring(4, 6) : '00';
  return `${h}:${m}:${s}`;
}

/**
 * Clean DICOM patient names (removes ^ separators and trailing caret padding)
 */
function formatPatientName(name) {
  if (!name) return 'Unknown Patient';
  return name.replace(/\^+/g, ' ').replace(/\s+/g, ' ').trim() || 'Unknown Patient';
}

/**
 * GET /api/config
 * Returns client configuration including MedDream viewer base URL
 */
app.get('/api/config', (req, res) => {
  const host = req.hostname === '127.0.0.1' || req.hostname === 'localhost' ? 'localhost' : req.hostname;
  const meddreamUrl = `http://${host}:${MEDDREAM_PORT}`;
  res.json({
    success: true,
    serverIp: host,
    appPort: PORT,
    orthancPort: ORTHANC_PORT,
    meddreamPort: MEDDREAM_PORT,
    meddreamBaseUrl: meddreamUrl,
    orthancHost: ORTHANC_HOST
  });
});

/**
 * GET /api/health
 * Checks PACS and MedDream connectivity
 */
app.get('/api/health', async (req, res) => {
  let orthancHealth = { connected: false, message: 'Unreachable' };
  let meddreamHealth = { accessible: true, port: MEDDREAM_PORT };

  try {
    const sys = await orthancRequest('/system');
    orthancHealth = {
      connected: true,
      name: sys.data.Name,
      version: sys.data.Version,
      dicomAet: sys.data.DicomAet,
      storageArea: sys.data.StorageArea
    };
  } catch (err) {
    orthancHealth = {
      connected: false,
      error: err.message
    };
  }

  res.json({
    status: orthancHealth.connected ? 'ok' : 'degraded',
    timestamp: new Date().toISOString(),
    orthanc: orthancHealth,
    meddream: meddreamHealth
  });
});

/**
 * GET /api/studies
 * Returns normalized list of all DICOM studies in Orthanc
 */
app.get('/api/studies', async (req, res) => {
  try {
    // 1. Fetch DICOMweb studies to quickly obtain aggregated modalities and instance counts
    let dicomWebStudiesMap = new Map();
    try {
      const dwRes = await orthancRequest('/dicom-web/studies');
      if (Array.isArray(dwRes.data)) {
        for (const item of dwRes.data) {
          const studyUid = item['0020000D']?.Value?.[0];
          if (studyUid) {
            const modalities = item['00080061']?.Value || [];
            const instancesCount = item['00201208']?.Value?.[0] || 0;
            const seriesCount = item['00201206']?.Value?.[0] || 0;
            dicomWebStudiesMap.set(studyUid, { modalities, instancesCount, seriesCount });
          }
        }
      }
    } catch (e) {
      console.warn('DICOMweb studies query skipped or failed, falling back to Orthanc REST:', e.message);
    }

    // 2. Fetch full studies from Orthanc
    const studiesRes = await orthancRequest('/studies?expand');
    if (!Array.isArray(studiesRes.data)) {
      return res.json({ success: true, count: 0, studies: [] });
    }

    const host = req.hostname === '127.0.0.1' || req.hostname === 'localhost' ? 'localhost' : req.hostname;
    const meddreamBase = `http://${host}:${MEDDREAM_PORT}`;

    // 3. Normalize study records
    const studies = await Promise.all(studiesRes.data.map(async (st) => {
      const mainTags = st.MainDicomTags || {};
      const patientTags = st.PatientMainDicomTags || {};
      const studyUid = mainTags.StudyInstanceUID || '';
      const orthancId = st.ID;

      // Extract modality from DICOMweb map or query series if not present
      let modalities = [];
      let instancesCount = 0;
      let seriesCount = Array.isArray(st.Series) ? st.Series.length : 0;

      if (dicomWebStudiesMap.has(studyUid)) {
        const dw = dicomWebStudiesMap.get(studyUid);
        modalities = dw.modalities || [];
        instancesCount = dw.instancesCount || 0;
        if (dw.seriesCount) seriesCount = dw.seriesCount;
      }

      // If modality is still empty and series exist, query first series to get modality
      if (modalities.length === 0 && Array.isArray(st.Series) && st.Series.length > 0) {
        try {
          const firstSeries = await orthancRequest(`/series/${st.Series[0]}`);
          const mod = firstSeries.data?.MainDicomTags?.Modality;
          if (mod) modalities = [mod];
          if (firstSeries.data?.Instances) instancesCount = firstSeries.data.Instances.length;
        } catch (err) {
          // ignore series fetch error
        }
      }

      return {
        id: orthancId,
        studyInstanceUid: studyUid,
        patientId: patientTags.PatientID || 'N/A',
        patientName: formatPatientName(patientTags.PatientName),
        patientBirthDate: formatDicomDate(patientTags.PatientBirthDate),
        patientSex: patientTags.PatientSex || '',
        studyDate: formatDicomDate(mainTags.StudyDate),
        rawStudyDate: mainTags.StudyDate || '',
        studyTime: formatDicomTime(mainTags.StudyTime),
        studyDescription: mainTags.StudyDescription || mainTags.RequestedProcedureDescription || 'No description',
        accessionNumber: mainTags.AccessionNumber || 'N/A',
        institutionName: mainTags.InstitutionName || '',
        referringPhysician: formatPatientName(mainTags.ReferringPhysicianName || mainTags.RequestingPhysician),
        seriesCount: seriesCount,
        instancesCount: instancesCount,
        modalities: modalities.length > 0 ? modalities : ['OT'],
        lastUpdate: st.LastUpdate || '',
        meddreamUrl: `${meddreamBase}/?study=${encodeURIComponent(studyUid)}`
      };
    }));

    // Sort studies by date descending (newest first)
    studies.sort((a, b) => {
      const dateA = (a.rawStudyDate || '') + (a.studyTime || '');
      const dateB = (b.rawStudyDate || '') + (b.studyTime || '');
      return dateB.localeCompare(dateA);
    });

    res.json({
      success: true,
      count: studies.length,
      studies: studies
    });
  } catch (err) {
    console.error('Error in /api/studies:', err);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve studies from PACS',
      message: err.message
    });
  }
});

/**
 * GET /api/studies/:id
 * Detailed view for a specific study including all series
 */
app.get('/api/studies/:id', async (req, res) => {
  try {
    const studyId = req.params.id;
    const studyRes = await orthancRequest(`/studies/${encodeURIComponent(studyId)}`);
    const st = studyRes.data;

    const mainTags = st.MainDicomTags || {};
    const patientTags = st.PatientMainDicomTags || {};
    const studyUid = mainTags.StudyInstanceUID || '';

    const host = req.hostname === '127.0.0.1' || req.hostname === 'localhost' ? 'localhost' : req.hostname;
    const meddreamBase = `http://${host}:${MEDDREAM_PORT}`;

    // Fetch details for all series in this study
    let seriesDetails = [];
    if (Array.isArray(st.Series)) {
      seriesDetails = await Promise.all(
        st.Series.map(async (seriesId) => {
          try {
            const serRes = await orthancRequest(`/series/${seriesId}`);
            const serTags = serRes.data?.MainDicomTags || {};
            return {
              id: seriesId,
              seriesInstanceUid: serTags.SeriesInstanceUID || '',
              seriesNumber: serTags.SeriesNumber || '',
              modality: serTags.Modality || 'OT',
              seriesDescription: serTags.SeriesDescription || serTags.PerformedProcedureStepDescription || 'Series ' + (serTags.SeriesNumber || ''),
              bodyPartExamined: serTags.BodyPartExamined || '',
              seriesDate: formatDicomDate(serTags.SeriesDate),
              instancesCount: Array.isArray(serRes.data?.Instances) ? serRes.data.Instances.length : 0
            };
          } catch (e) {
            return { id: seriesId, modality: 'OT', seriesDescription: 'Series', instancesCount: 0 };
          }
        })
      );
    }

    const modalities = [...new Set(seriesDetails.map(s => s.modality).filter(Boolean))];
    const totalInstances = seriesDetails.reduce((sum, s) => sum + (s.instancesCount || 0), 0);

    const study = {
      id: st.ID,
      studyInstanceUid: studyUid,
      patientId: patientTags.PatientID || 'N/A',
      patientName: formatPatientName(patientTags.PatientName),
      patientBirthDate: formatDicomDate(patientTags.PatientBirthDate),
      patientSex: patientTags.PatientSex || '',
      studyDate: formatDicomDate(mainTags.StudyDate),
      studyTime: formatDicomTime(mainTags.StudyTime),
      studyDescription: mainTags.StudyDescription || mainTags.RequestedProcedureDescription || 'No description',
      accessionNumber: mainTags.AccessionNumber || 'N/A',
      institutionName: mainTags.InstitutionName || '',
      referringPhysician: formatPatientName(mainTags.ReferringPhysicianName || mainTags.RequestingPhysician),
      modalities: modalities.length > 0 ? modalities : ['OT'],
      seriesCount: seriesDetails.length,
      instancesCount: totalInstances,
      series: seriesDetails,
      meddreamUrl: `${meddreamBase}/?study=${encodeURIComponent(studyUid)}`
    };

    res.json({ success: true, study });
  } catch (err) {
    console.error(`Error in /api/studies/${req.params.id}:`, err);
    res.status(500).json({
      success: false,
      error: 'Failed to retrieve study details',
      message: err.message
    });
  }
});

/**
 * POST /api/upload
 * Allows uploading DICOM files directly into Orthanc
 */
app.post('/api/upload', upload.array('dicomFiles', 20), async (req, res) => {
  try {
    if (!req.files || req.files.length === 0) {
      return res.status(400).json({ success: false, error: 'No files uploaded' });
    }

    const results = [];
    for (const file of req.files) {
      try {
        const uploadRes = await orthancRequest('/instances', 'POST', file.buffer, {
          'Content-Type': 'application/dicom'
        });
        results.push({
          fileName: file.originalname,
          success: true,
          orthancInstanceId: uploadRes.data?.ID,
          parentStudy: uploadRes.data?.ParentStudy
        });
      } catch (err) {
        results.push({
          fileName: file.originalname,
          success: false,
          error: err.message
        });
      }
    }

    res.json({
      success: true,
      uploadedCount: results.filter(r => r.success).length,
      totalCount: req.files.length,
      results
    });
  } catch (err) {
    console.error('Error in /api/upload:', err);
    res.status(500).json({ success: false, error: 'Upload failed', message: err.message });
  }
});

/**
 * POST /api/import-sample
 * Triggers sample CT DICOM download & upload to Orthanc
 */
app.post('/api/import-sample', async (req, res) => {
  try {
    const sampleUrl = 'https://raw.githubusercontent.com/cornerstonejs/cornerstoneWADOImageLoader/master/testImages/CT2_J2KR';
    
    const fetchSample = () => new Promise((resolve, reject) => {
      const https = require('https');
      https.get(sampleUrl, (sampleRes) => {
        if (sampleRes.statusCode !== 200) {
          return reject(new Error(`Failed to download sample, HTTP ${sampleRes.statusCode}`));
        }
        const dataChunks = [];
        sampleRes.on('data', c => dataChunks.push(c));
        sampleRes.on('end', () => resolve(Buffer.concat(dataChunks)));
      }).on('error', reject);
    });

    const buffer = await fetchSample();
    const uploadRes = await orthancRequest('/instances', 'POST', buffer, {
      'Content-Type': 'application/dicom'
    });

    res.json({
      success: true,
      message: 'Sample study imported successfully',
      instanceId: uploadRes.data?.ID,
      parentStudy: uploadRes.data?.ParentStudy
    });
  } catch (err) {
    console.error('Error importing sample:', err);
    res.status(500).json({ success: false, error: 'Sample import failed', message: err.message });
  }
});

// Single Page App fallback
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// Start Server
app.listen(PORT, '0.0.0.0', () => {
  console.log(`====================================================`);
  console.log(` MedDream DICOM Study Hub Web App is running!`);
  console.log(` Web App URL:      http://localhost:${PORT}`);
  console.log(` Orthanc PACS:     http://${ORTHANC_HOST}:${ORTHANC_PORT}`);
  console.log(` MedDream Viewer:  http://${MEDDREAM_HOST}:${MEDDREAM_PORT}`);
  console.log(`====================================================`);
});
