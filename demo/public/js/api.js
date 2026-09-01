/**
 * API Service for MedDream DICOM Study Hub
 */
const ApiService = {
  /**
   * Fetch runtime server configuration
   */
  async getConfig() {
    try {
      const res = await fetch('/api/config');
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error('Failed to fetch config:', err);
      return { serverIp: window.location.hostname || 'localhost', meddreamPort: 8080 };
    }
  },

  /**
   * Fetch PACS and MedDream health check status
   */
  async getHealth() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      return await res.json();
    } catch (err) {
      return { status: 'error', error: err.message, orthanc: { connected: false } };
    }
  },

  /**
   * Fetch all normalized DICOM studies
   */
  async getStudies() {
    const res = await fetch('/api/studies');
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.message || `HTTP ${res.status}: Failed to load studies from PACS`);
    }
    return await res.json();
  },

  /**
   * Fetch detailed study breakdown with series
   */
  async getStudyDetails(studyId) {
    const res = await fetch(`/api/studies/${encodeURIComponent(studyId)}`);
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.message || `HTTP ${res.status}: Failed to load study details`);
    }
    return await res.json();
  },

  /**
   * Trigger sample CT DICOM study download and import
   */
  async importSampleStudy() {
    const res = await fetch('/api/import-sample', { method: 'POST' });
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.message || `HTTP ${res.status}: Sample import failed`);
    }
    return await res.json();
  },

  /**
   * Upload DICOM files to Orthanc
   */
  async uploadDicomFiles(formData) {
    const res = await fetch('/api/upload', {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.message || `HTTP ${res.status}: Upload failed`);
    }
    return await res.json();
  }
};
