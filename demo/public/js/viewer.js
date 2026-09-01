/**
 * MedDream DICOM Viewer Integration Manager
 */
const MedDreamViewer = {
  activeStudy: null,
  config: {
    serverIp: window.location.hostname || 'localhost',
    port: 8080
  },

  init(config = {}) {
    if (config.serverIp) this.config.serverIp = config.serverIp;
    if (config.meddreamPort) this.config.port = config.meddreamPort;

    // Load custom settings from localStorage if saved
    const savedIp = localStorage.getItem('meddream_server_ip');
    const savedPort = localStorage.getItem('meddream_server_port');
    if (savedIp) this.config.serverIp = savedIp;
    if (savedPort) this.config.port = parseInt(savedPort, 10);

    this.bindEvents();
  },

  /**
   * Constructs token-authenticated MedDream viewer URL:
   * http://SERVER_IP:8080/?token={TOKEN}
   */
  getViewerUrl(token) {
    const host = this.config.serverIp || 'localhost';
    const port = this.config.port || 8080;
    return `http://${host}:${port}/?token=${encodeURIComponent(token)}`;
  },

  /**
   * Open the study directly in a new browser tab/window using a secure token
   */
  async openInNewTab(study) {
    if (!study || !study.studyInstanceUid) return;
    try {
      App.showToast(`Requesting secure viewer token...`, 'info');
      const tokenRes = await ApiService.generateViewerToken(study);
      const url = this.getViewerUrl(tokenRes.token);
      window.open(url, '_blank', 'noopener,noreferrer');
      App.showToast(`Opened MedDream viewer with authenticated token`, 'success');
    } catch (err) {
      console.error('Failed to generate viewer token:', err);
      App.showToast(`Authentication error: ${err.message}`, 'error');
    }
  },

  /**
   * Embed and display the study inside the interactive modal iframe with a secure token
   */
  async openEmbedded(study) {
    if (!study || !study.studyInstanceUid) return;
    this.activeStudy = study;

    const modal = document.getElementById('viewer-modal');
    const iframe = document.getElementById('meddream-iframe');
    const loader = document.getElementById('viewer-iframe-loader');

    // Update modal header metadata
    document.getElementById('modal-viewer-patient').textContent = study.patientName || 'Unknown Patient';
    document.getElementById('modal-viewer-date').textContent = study.studyDate || 'N/A';
    document.getElementById('modal-viewer-desc').textContent = study.studyDescription || 'No description';
    document.getElementById('modal-viewer-uid').textContent = `UID: ${study.studyInstanceUid}`;

    // Update modality badge
    const modalityEl = document.getElementById('modal-viewer-modality');
    const mod = (study.modalities && study.modalities[0]) || 'OT';
    modalityEl.textContent = mod;
    modalityEl.className = `modality-badge mod-${mod}`;

    // Open modal & reset iframe
    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
    loader.style.opacity = '1';
    loader.style.display = 'flex';
    loader.innerHTML = `
      <div class="spinner"></div>
      <div style="font-size: 0.85rem; color: #64748B;">Authenticating and connecting to MedDream DICOM Viewer...</div>
    `;
    iframe.src = 'about:blank';

    try {
      const tokenRes = await ApiService.generateViewerToken(study);
      this.activeToken = tokenRes.token;
      const viewerUrl = this.getViewerUrl(tokenRes.token);
      iframe.src = viewerUrl;

      iframe.onload = () => {
        setTimeout(() => {
          loader.style.opacity = '0';
          setTimeout(() => { loader.style.display = 'none'; }, 200);
        }, 500);
      };
    } catch (err) {
      console.error('Failed to embed viewer:', err);
      loader.innerHTML = `
        <div style="color: #EF4444; font-weight: 600; text-align: center; padding: 20px;">
          <div>Authentication failed</div>
          <div style="font-size: 0.8rem; color: #94A3B8; margin-top: 6px;">${err.message}</div>
        </div>
      `;
      App.showToast(`Authentication error: ${err.message}`, 'error');
    }
  },

  closeModal() {
    const modal = document.getElementById('viewer-modal');
    const iframe = document.getElementById('meddream-iframe');
    modal.classList.remove('open');
    iframe.src = 'about:blank';
    document.body.style.overflow = '';
    this.activeStudy = null;
    this.activeToken = null;
  },

  toggleFullscreen() {
    const viewerWindow = document.getElementById('viewer-window');
    const isFullscreen = viewerWindow.classList.toggle('fullscreen');
    const icon = document.getElementById('icon-fullscreen');
    if (icon) {
      if (isFullscreen) {
        icon.setAttribute('data-lucide', 'minimize-2');
      } else {
        icon.setAttribute('data-lucide', 'maximize-2');
      }
      lucide.createIcons();
    }
  },

  async copyViewerUrl(study) {
    if (!study || !study.studyInstanceUid) return;
    try {
      let token = this.activeToken;
      if (!token) {
        const tokenRes = await ApiService.generateViewerToken(study);
        token = tokenRes.token;
      }
      const url = this.getViewerUrl(token);
      await navigator.clipboard.writeText(url);
      App.showToast('Token-authenticated Viewer URL copied to clipboard!', 'success');
    } catch (err) {
      App.showToast('Could not copy URL to clipboard: ' + err.message, 'error');
    }
  },

  bindEvents() {
    // Close modal button
    document.getElementById('btn-viewer-close')?.addEventListener('click', () => this.closeModal());

    // Fullscreen toggle
    document.getElementById('btn-viewer-fullscreen')?.addEventListener('click', () => this.toggleFullscreen());

    // Open in new tab button from modal
    document.getElementById('btn-viewer-new-tab')?.addEventListener('click', () => {
      if (this.activeStudy) this.openInNewTab(this.activeStudy);
    });

    // Copy link button from modal
    document.getElementById('btn-viewer-copy-link')?.addEventListener('click', () => {
      if (this.activeStudy) this.copyViewerUrl(this.activeStudy.studyInstanceUid);
    });

    // Close on backdrop click (if clicking outside window)
    document.getElementById('viewer-modal')?.addEventListener('click', (e) => {
      if (e.target.id === 'viewer-modal') {
        this.closeModal();
      }
    });

    // Escape key listener
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && document.getElementById('viewer-modal')?.classList.contains('open')) {
        this.closeModal();
      }
    });
  }
};
