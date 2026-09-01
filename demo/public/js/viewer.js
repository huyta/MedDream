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
   * Constructs standard MedDream viewer URL:
   * http://SERVER_IP:8080/?study={STUDY_INSTANCE_UID}
   */
  getViewerUrl(studyInstanceUid) {
    const host = this.config.serverIp || 'localhost';
    const port = this.config.port || 8080;
    return `http://${host}:${port}/?study=${encodeURIComponent(studyInstanceUid)}`;
  },

  /**
   * Open the study directly in a new browser tab/window
   */
  openInNewTab(study) {
    if (!study || !study.studyInstanceUid) return;
    const url = this.getViewerUrl(study.studyInstanceUid);
    window.open(url, '_blank', 'noopener,noreferrer');
  },

  /**
   * Embed and display the study inside the interactive modal iframe
   */
  openEmbedded(study) {
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

    // Show loading spinner and set iframe source
    loader.style.opacity = '1';
    loader.style.display = 'flex';

    const viewerUrl = this.getViewerUrl(study.studyInstanceUid);
    iframe.src = viewerUrl;

    iframe.onload = () => {
      setTimeout(() => {
        loader.style.opacity = '0';
        setTimeout(() => { loader.style.display = 'none'; }, 200);
      }, 400);
    };

    // Open modal
    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
  },

  closeModal() {
    const modal = document.getElementById('viewer-modal');
    const iframe = document.getElementById('meddream-iframe');
    modal.classList.remove('open');
    iframe.src = 'about:blank';
    document.body.style.overflow = '';
    this.activeStudy = null;
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

  copyViewerUrl(studyInstanceUid) {
    const url = this.getViewerUrl(studyInstanceUid);
    navigator.clipboard.writeText(url).then(() => {
      App.showToast('Viewer URL copied to clipboard!', 'success');
    }).catch(() => {
      App.showToast('Could not copy URL to clipboard', 'error');
    });
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
