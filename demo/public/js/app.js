/**
 * Main Application Logic for MedDream DICOM Study Hub
 */
const App = {
  state: {
    studies: [],
    filteredStudies: [],
    selectedModality: 'ALL',
    searchTerm: '',
    accessionTerm: '',
    currentView: 'table', // 'table' or 'cards'
    selectedStudy: null,
    isLoading: false,
    selectedUploadFiles: []
  },

  async init() {
    // 1. Fetch server config
    const config = await ApiService.getConfig();
    MedDreamViewer.init(config);

    // 2. Initialize Lucide icons
    lucide.createIcons();

    // 3. Bind UI event listeners
    this.bindEvents();

    // 4. Initial healthcheck
    this.checkHealth();

    // 5. Initial studies load
    await this.loadStudies();

    // 6. Check health periodically every 30s
    setInterval(() => this.checkHealth(), 30000);
  },

  /**
   * Healthcheck for PACS and MedDream
   */
  async checkHealth() {
    const health = await ApiService.getHealth();
    const orthancDot = document.getElementById('orthanc-status-dot');
    const orthancText = document.getElementById('orthanc-status-text');

    if (health.orthanc?.connected) {
      orthancDot.className = 'status-dot';
      orthancText.textContent = 'Online';
      orthancText.title = `Orthanc v${health.orthanc.version || ''} (${health.orthanc.name || ''})`;
    } else {
      orthancDot.className = 'status-dot error';
      orthancText.textContent = 'Offline';
    }
  },

  /**
   * Fetch studies from backend and refresh views
   */
  async loadStudies() {
    this.state.isLoading = true;
    this.showState('loading');
    const refreshIcon = document.getElementById('refresh-icon');
    if (refreshIcon) refreshIcon.style.animation = 'spin 0.8s linear infinite';

    try {
      const response = await ApiService.getStudies();
      this.state.studies = response.studies || [];
      this.updateStats();
      this.updateModalityFilters();
      this.applyFilters();
    } catch (err) {
      console.error('Failed to load studies:', err);
      this.showState('error');
      document.getElementById('error-message-text').textContent = err.message || 'Could not connect to Orthanc PACS';
    } finally {
      this.state.isLoading = false;
      if (refreshIcon) refreshIcon.style.animation = '';
    }
  },

  /**
   * Filter studies based on search input, accession input, and active modality pill
   */
  applyFilters() {
    const term = this.state.searchTerm.toLowerCase().trim();
    const accTerm = this.state.accessionTerm.toLowerCase().trim();
    const modality = this.state.selectedModality;

    this.state.filteredStudies = this.state.studies.filter(study => {
      // 1. Modality Filter
      if (modality !== 'ALL') {
        const hasModality = study.modalities && study.modalities.includes(modality);
        if (!hasModality) return false;
      }

      // 2. Dedicated Accession Number Filter
      if (accTerm) {
        const studyAcc = (study.accessionNumber || '').toLowerCase();
        if (!studyAcc.includes(accTerm)) return false;
      }

      // 3. Search Term Filter (Patient Name, ID, Description, UID, Accession, etc.)
      if (!term) return true;

      const patientName = (study.patientName || '').toLowerCase();
      const patientId = (study.patientId || '').toLowerCase();
      const description = (study.studyDescription || '').toLowerCase();
      const accession = (study.accessionNumber || '').toLowerCase();
      const studyUid = (study.studyInstanceUid || '').toLowerCase();
      const institution = (study.institutionName || '').toLowerCase();
      const physician = (study.referringPhysician || '').toLowerCase();
      const modalitiesStr = (study.modalities || []).join(' ').toLowerCase();

      return (
        patientName.includes(term) ||
        patientId.includes(term) ||
        description.includes(term) ||
        accession.includes(term) ||
        studyUid.includes(term) ||
        institution.includes(term) ||
        physician.includes(term) ||
        modalitiesStr.includes(term)
      );
    });

    this.render();
  },

  /**
   * Main render method
   */
  render() {
    if (this.state.filteredStudies.length === 0) {
      this.showState('empty');
      const clearBtn = document.getElementById('btn-clear-filters');
      if (this.state.searchTerm || this.state.accessionTerm || this.state.selectedModality !== 'ALL') {
        document.getElementById('empty-state-title').textContent = 'No Matching Studies';
        document.getElementById('empty-state-desc').textContent = 'No DICOM studies matched your current search filters.';
        clearBtn.style.display = 'inline-flex';
      } else {
        document.getElementById('empty-state-title').textContent = 'No DICOM Studies in PACS';
        document.getElementById('empty-state-desc').textContent = 'The Orthanc PACS server currently contains no DICOM studies. Click below to import sample data.';
        clearBtn.style.display = 'none';
      }
      return;
    }

    if (this.state.currentView === 'table') {
      this.renderTable();
      this.showState('table');
    } else {
      this.renderCards();
      this.showState('cards');
    }

    lucide.createIcons();
  },

  /**
   * Render Studies Table
   */
  renderTable() {
    const tbody = document.getElementById('studies-table-body');
    tbody.innerHTML = '';

    this.state.filteredStudies.forEach(study => {
      const tr = document.createElement('tr');

      // Patient initial for avatar
      const initial = (study.patientName || 'U').charAt(0).toUpperCase();
      const modalityBadges = (study.modalities || ['OT']).map(m => 
        `<span class="modality-badge mod-${m}">${m}</span>`
      ).join(' ');

      const hasAccession = study.accessionNumber && study.accessionNumber !== 'N/A' && study.accessionNumber.trim() !== '';

      tr.innerHTML = `
        <td>
          <div class="patient-cell">
            <div class="patient-avatar">${initial}</div>
            <div class="patient-info">
              <div class="patient-name">${this.escapeHtml(study.patientName)}</div>
              <div class="patient-meta">
                ${study.patientSex ? `<span>${study.patientSex}</span><span>•</span>` : ''}
                ${study.patientBirthDate ? `<span>DOB: ${study.patientBirthDate}</span>` : '<span>Patient</span>'}
              </div>
            </div>
          </div>
        </td>
        <td>
          <span style="font-family: var(--font-mono); font-weight: 600; font-size: 0.82rem;">
            ${this.escapeHtml(study.patientId)}
          </span>
        </td>
        <td>
          ${hasAccession ? `
            <div class="uid-cell" style="font-size: 0.8rem; font-family: var(--font-mono);">
              <span class="accession-tag" onclick="App.filterByAccession('${this.escapeHtml(study.accessionNumber)}')" title="Click to filter by Accession: ${this.escapeHtml(study.accessionNumber)}">
                ${this.escapeHtml(study.accessionNumber)}
              </span>
              <button class="uid-copy-btn" onclick="App.copyText('${this.escapeHtml(study.accessionNumber)}')" title="Copy Accession No">
                <i data-lucide="copy" style="width: 12px; height: 12px;"></i>
              </button>
            </div>
          ` : `<span style="color: #94A3B8; font-size: 0.78rem;">--</span>`}
        </td>
        <td>
          <div class="study-date-cell">
            <span class="study-date-primary">${study.studyDate || 'N/A'}</span>
            <span class="study-time-sub">${study.studyTime || ''}</span>
          </div>
        </td>
        <td>
          <div style="display: flex; gap: 4px; flex-wrap: wrap;">
            ${modalityBadges}
          </div>
        </td>
        <td>
          <div style="max-width: 200px; font-weight: 500; color: #1E293B; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${this.escapeHtml(study.studyDescription)}">
            ${this.escapeHtml(study.studyDescription)}
          </div>
        </td>
        <td>
          <div style="font-size: 0.8rem; font-family: var(--font-mono);">
            <strong style="color: #0F172A;">${study.seriesCount}</strong> series
            <div style="font-size: 0.72rem; color: #64748B;">${study.instancesCount || '--'} images</div>
          </div>
        </td>
        <td>
          <div class="uid-cell">
            <span title="${study.studyInstanceUid}">
              ${this.truncateUid(study.studyInstanceUid)}
            </span>
            <button class="uid-copy-btn" onclick="App.copyText('${study.studyInstanceUid}')" title="Copy Study Instance UID">
              <i data-lucide="copy" style="width: 12px; height: 12px;"></i>
            </button>
          </div>
        </td>
        <td style="text-align: right;">
          <div class="table-actions">
            <button class="btn btn-sm btn-action-view" onclick="App.openStudyInViewer('${study.id}')" title="Open directly in MedDream Web Viewer">
              <i data-lucide="play" style="width: 12px; height: 12px;"></i>
              <span>View</span>
            </button>
            <button class="btn btn-sm btn-action-embed" onclick="App.embedStudyInModal('${study.id}')" title="View embedded in frame">
              <i data-lucide="layout" style="width: 13px; height: 13px;"></i>
            </button>
            <button class="btn btn-sm btn-secondary" onclick="App.openStudyDrawer('${study.id}')" title="Inspect Study Details">
              <i data-lucide="info" style="width: 13px; height: 13px;"></i>
            </button>
          </div>
        </td>
      `;

      tbody.appendChild(tr);
    });
  },

  /**
   * Render Studies Cards Grid
   */
  renderCards() {
    const container = document.getElementById('studies-cards-wrapper');
    container.innerHTML = '';

    this.state.filteredStudies.forEach(study => {
      const card = document.createElement('div');
      card.className = 'study-card';

      const initial = (study.patientName || 'U').charAt(0).toUpperCase();
      const modalityBadges = (study.modalities || ['OT']).map(m => 
        `<span class="modality-badge mod-${m}">${m}</span>`
      ).join(' ');

      const hasAccession = study.accessionNumber && study.accessionNumber !== 'N/A' && study.accessionNumber.trim() !== '';

      card.innerHTML = `
        <div class="study-card-header">
          <div class="patient-cell">
            <div class="patient-avatar">${initial}</div>
            <div class="patient-info">
              <div class="patient-name">${this.escapeHtml(study.patientName)}</div>
              <div class="patient-meta">ID: ${this.escapeHtml(study.patientId)}</div>
            </div>
          </div>
          <div style="display: flex; gap: 4px;">
            ${modalityBadges}
          </div>
        </div>

        <div class="study-card-body">
          <div class="card-meta-row">
            <span class="card-meta-label">Accession No</span>
            <span class="card-meta-value" style="font-family: var(--font-mono); font-size: 0.8rem;">
              ${hasAccession ? `
                <span class="accession-tag" onclick="App.filterByAccession('${this.escapeHtml(study.accessionNumber)}')" title="Click to filter by Accession">
                  ${this.escapeHtml(study.accessionNumber)}
                </span>
              ` : '<span style="color: #94A3B8;">--</span>'}
            </span>
          </div>
          <div class="card-meta-row">
            <span class="card-meta-label">Description</span>
            <span class="card-meta-value" style="max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${this.escapeHtml(study.studyDescription)}">
              ${this.escapeHtml(study.studyDescription)}
            </span>
          </div>
          <div class="card-meta-row">
            <span class="card-meta-label">Study Date</span>
            <span class="card-meta-value">${study.studyDate || 'N/A'} ${study.studyTime || ''}</span>
          </div>
          <div class="card-meta-row">
            <span class="card-meta-label">Series / Images</span>
            <span class="card-meta-value">${study.seriesCount} series (${study.instancesCount || '--'} images)</span>
          </div>
          <div class="card-meta-row">
            <span class="card-meta-label">Study UID</span>
            <div class="uid-cell" style="font-size: 0.72rem;">
              <span>${this.truncateUid(study.studyInstanceUid)}</span>
              <button class="uid-copy-btn" onclick="App.copyText('${study.studyInstanceUid}')" title="Copy UID">
                <i data-lucide="copy" style="width: 12px; height: 12px;"></i>
              </button>
            </div>
          </div>
        </div>

        <div class="study-card-footer">
          <button class="btn btn-sm btn-secondary" onclick="App.openStudyDrawer('${study.id}')">
            <i data-lucide="info" style="width: 14px; height: 14px;"></i>
            <span>Details</span>
          </button>
          <button class="btn btn-sm btn-action-embed" onclick="App.embedStudyInModal('${study.id}')">
            <i data-lucide="layout" style="width: 14px; height: 14px;"></i>
            <span>Embed</span>
          </button>
          <button class="btn btn-sm btn-primary" onclick="App.openStudyInViewer('${study.id}')">
            <i data-lucide="play" style="width: 14px; height: 14px;"></i>
            <span>View</span>
          </button>
        </div>
      `;

      container.appendChild(card);
    });
  },

  /**
   * Update top statistics banner
   */
  updateStats() {
    const studies = this.state.studies;
    const totalStudies = studies.length;
    const totalSeries = studies.reduce((sum, s) => sum + (s.seriesCount || 0), 0);
    const totalInstances = studies.reduce((sum, s) => sum + (s.instancesCount || 0), 0);

    const allModalities = new Set();
    studies.forEach(s => (s.modalities || []).forEach(m => allModalities.add(m)));

    document.getElementById('stat-total-studies').textContent = totalStudies;
    document.getElementById('stat-total-series').textContent = totalSeries;
    document.getElementById('stat-total-instances').textContent = totalInstances;
    document.getElementById('stat-modalities-count').textContent = allModalities.size;
  },

  /**
   * Update dynamic Modality Filter Pills
   */
  updateModalityFilters() {
    const container = document.getElementById('modality-filters-container');
    const allPill = container.querySelector('[data-modality="ALL"]');
    document.getElementById('pill-count-all').textContent = this.state.studies.length;

    // Count studies per modality
    const counts = {};
    this.state.studies.forEach(s => {
      (s.modalities || ['OT']).forEach(m => {
        counts[m] = (counts[m] || 0) + 1;
      });
    });

    // Remove existing dynamic pills
    const oldPills = container.querySelectorAll('.filter-pill:not([data-modality="ALL"])');
    oldPills.forEach(p => p.remove());

    // Append sorted modality pills
    Object.keys(counts).sort().forEach(mod => {
      const btn = document.createElement('button');
      btn.className = `filter-pill ${this.state.selectedModality === mod ? 'active' : ''}`;
      btn.setAttribute('data-modality', mod);
      btn.innerHTML = `
        <span>${mod}</span>
        <span class="pill-count">${counts[mod]}</span>
      `;
      btn.addEventListener('click', () => {
        this.setModalityFilter(mod);
      });
      container.appendChild(btn);
    });
  },

  setModalityFilter(modality) {
    this.state.selectedModality = modality;
    const pills = document.querySelectorAll('#modality-filters-container .filter-pill');
    pills.forEach(p => {
      if (p.getAttribute('data-modality') === modality) {
        p.classList.add('active');
      } else {
        p.classList.remove('active');
      }
    });
    this.applyFilters();
  },

  /**
   * Display specific container state
   */
  showState(stateName) {
    document.getElementById('state-loading').style.display = stateName === 'loading' ? 'block' : 'none';
    document.getElementById('studies-table-wrapper').style.display = stateName === 'table' ? 'block' : 'none';
    document.getElementById('studies-cards-wrapper').style.display = stateName === 'cards' ? 'grid' : 'none';
    document.getElementById('state-empty').style.display = stateName === 'empty' ? 'flex' : 'none';
    document.getElementById('state-error').style.display = stateName === 'error' ? 'flex' : 'none';
  },

  /**
   * Open study in MedDream viewer new tab
   */
  openStudyInViewer(studyId) {
    const study = this.state.studies.find(s => s.id === studyId);
    if (study) {
      MedDreamViewer.openInNewTab(study);
      this.showToast(`Launching MedDream viewer for ${study.patientName}...`, 'info');
    }
  },

  /**
   * Open study embedded in iframe modal
   */
  embedStudyInModal(studyId) {
    const study = this.state.studies.find(s => s.id === studyId);
    if (study) {
      MedDreamViewer.openEmbedded(study);
    }
  },

  /**
   * Open slide-in Study Details Drawer
   */
  async openStudyDrawer(studyId) {
    const drawer = document.getElementById('study-details-drawer');
    const backdrop = document.getElementById('drawer-backdrop');

    // Find basic study info from state
    let study = this.state.studies.find(s => s.id === studyId);
    if (!study) return;

    this.state.selectedStudy = study;

    // Populate drawer static fields
    document.getElementById('drawer-patient-name').textContent = study.patientName;
    document.getElementById('drawer-patient-id').textContent = study.patientId;
    document.getElementById('drawer-patient-dob').textContent = study.patientBirthDate || 'N/A';
    document.getElementById('drawer-patient-sex').textContent = study.patientSex || 'N/A';
    document.getElementById('drawer-study-date').textContent = `${study.studyDate || 'N/A'} ${study.studyTime || ''}`;
    document.getElementById('drawer-accession').textContent = study.accessionNumber || 'N/A';
    document.getElementById('drawer-description').textContent = study.studyDescription || 'No description';
    document.getElementById('drawer-institution').textContent = study.institutionName || 'N/A';
    document.getElementById('drawer-physician').textContent = study.referringPhysician || 'N/A';
    document.getElementById('drawer-study-uid').textContent = study.studyInstanceUid;
    document.getElementById('drawer-series-count').textContent = study.seriesCount || '0';

    // Show drawer immediately
    drawer.classList.add('open');
    backdrop.classList.add('open');
    document.body.style.overflow = 'hidden';

    // Series container loading placeholder
    const seriesContainer = document.getElementById('drawer-series-list');
    seriesContainer.innerHTML = '<div style="font-size: 0.8rem; color: #64748B; padding: 10px;">Loading series details...</div>';

    // Fetch deep series breakdown
    try {
      const detailed = await ApiService.getStudyDetails(studyId);
      if (detailed.study && Array.isArray(detailed.study.series)) {
        seriesContainer.innerHTML = '';
        detailed.study.series.forEach((ser, index) => {
          const item = document.createElement('div');
          item.className = 'series-item';
          item.innerHTML = `
            <div class="series-info">
              <div class="series-name">${ser.seriesDescription || `Series #${ser.seriesNumber || index + 1}`}</div>
              <div style="font-size: 0.72rem; color: #64748B;">
                ${ser.bodyPartExamined ? `Body Part: ${ser.bodyPartExamined} • ` : ''}
                UID: ${this.truncateUid(ser.seriesInstanceUid)}
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="modality-badge mod-${ser.modality}">${ser.modality}</span>
              <span class="series-count-badge">${ser.instancesCount} imgs</span>
            </div>
          `;
          seriesContainer.appendChild(item);
        });
      }
    } catch (e) {
      seriesContainer.innerHTML = `<div style="font-size: 0.78rem; color: #64748B;">Series summary: ${study.seriesCount} series.</div>`;
    }

    lucide.createIcons();
  },

  closeDrawer() {
    document.getElementById('study-details-drawer').classList.remove('open');
    document.getElementById('drawer-backdrop').classList.remove('open');
    document.body.style.overflow = '';
  },

  /**
   * Filter specifically by an accession number
   */
  filterByAccession(accessionNo) {
    if (!accessionNo || accessionNo === 'N/A') return;
    const accInput = document.getElementById('accession-filter-input');
    const accClear = document.getElementById('accession-clear-btn');
    if (accInput) {
      accInput.value = accessionNo;
      if (accClear) accClear.style.display = 'block';
      this.state.accessionTerm = accessionNo;
      this.applyFilters();
      this.showToast(`Filtered by Accession: ${accessionNo}`, 'info');
    }
  },

  /**
   * Import sample test DICOM study
   */
  async importSample() {
    this.showToast('Importing sample CT DICOM study to PACS...', 'info');
    try {
      await ApiService.importSampleStudy();
      this.showToast('Sample study successfully imported!', 'success');
      await this.loadStudies();
    } catch (err) {
      this.showToast(`Import failed: ${err.message}`, 'error');
    }
  },

  /**
   * Copy text to clipboard helper
   */
  copyText(text) {
    navigator.clipboard.writeText(text).then(() => {
      this.showToast('Copied to clipboard', 'success');
    }).catch(() => {
      this.showToast('Failed to copy to clipboard', 'error');
    });
  },

  /**
   * Floating Toast Alerts
   */
  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    let iconName = 'info';
    if (type === 'success') iconName = 'check-circle';
    if (type === 'error') iconName = 'alert-circle';

    toast.innerHTML = `
      <i data-lucide="${iconName}" style="width: 16px; height: 16px; flex-shrink: 0; color: var(--brand-blue);"></i>
      <span>${this.escapeHtml(message)}</span>
    `;

    container.appendChild(toast);
    lucide.createIcons();

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(12px)';
      toast.style.transition = 'all 0.25s ease';
      setTimeout(() => toast.remove(), 250);
    }, 3200);
  },

  /**
   * Truncate long DICOM UIDs for clean display
   */
  truncateUid(uid) {
    if (!uid) return '';
    if (uid.length <= 24) return uid;
    return `${uid.substring(0, 10)}...${uid.substring(uid.length - 10)}`;
  },

  escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  },

  /**
   * Bind all UI event listeners
   */
  bindEvents() {
    // 1. Search Box input & clear
    const searchInput = document.getElementById('search-input');
    const searchClear = document.getElementById('search-clear-btn');

    searchInput.addEventListener('input', (e) => {
      this.state.searchTerm = e.target.value;
      searchClear.style.display = e.target.value ? 'block' : 'none';
      this.applyFilters();
    });

    searchClear.addEventListener('click', () => {
      searchInput.value = '';
      this.state.searchTerm = '';
      searchClear.style.display = 'none';
      searchInput.focus();
      this.applyFilters();
    });

    // 1b. Dedicated Accession Number input & clear
    const accessionInput = document.getElementById('accession-filter-input');
    const accessionClear = document.getElementById('accession-clear-btn');

    if (accessionInput) {
      accessionInput.addEventListener('input', (e) => {
        this.state.accessionTerm = e.target.value;
        if (accessionClear) accessionClear.style.display = e.target.value ? 'block' : 'none';
        this.applyFilters();
      });
    }

    if (accessionClear) {
      accessionClear.addEventListener('click', () => {
        if (accessionInput) accessionInput.value = '';
        this.state.accessionTerm = '';
        accessionClear.style.display = 'none';
        accessionInput?.focus();
        this.applyFilters();
      });
    }

    // Press '/' to focus search input
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && document.activeElement !== searchInput && !['input', 'textarea'].includes(document.activeElement.tagName.toLowerCase())) {
        e.preventDefault();
        searchInput.focus();
      }
    });

    // 2. View Mode Toggle (Table / Cards)
    document.getElementById('btn-view-table')?.addEventListener('click', () => {
      this.state.currentView = 'table';
      document.getElementById('btn-view-table').classList.add('active');
      document.getElementById('btn-view-cards').classList.remove('active');
      this.render();
    });

    document.getElementById('btn-view-cards')?.addEventListener('click', () => {
      this.state.currentView = 'cards';
      document.getElementById('btn-view-cards').classList.add('active');
      document.getElementById('btn-view-table').classList.remove('active');
      this.render();
    });

    // 3. Modality Filter 'All' Button
    document.querySelector('[data-modality="ALL"]')?.addEventListener('click', () => {
      this.setModalityFilter('ALL');
    });

    // 4. Refresh Button
    document.getElementById('btn-refresh')?.addEventListener('click', () => {
      this.loadStudies();
    });

    // 5. Retry Button in Error State
    document.getElementById('btn-retry-fetch')?.addEventListener('click', () => {
      this.loadStudies();
    });

    // 6. Clear Filters Button in Empty State
    document.getElementById('btn-clear-filters')?.addEventListener('click', () => {
      searchInput.value = '';
      this.state.searchTerm = '';
      searchClear.style.display = 'none';

      if (accessionInput) accessionInput.value = '';
      this.state.accessionTerm = '';
      if (accessionClear) accessionClear.style.display = 'none';

      this.setModalityFilter('ALL');
    });

    // 7. Import Sample Study Buttons
    document.getElementById('btn-quick-sample')?.addEventListener('click', () => this.importSample());
    document.getElementById('btn-empty-import')?.addEventListener('click', () => this.importSample());

    // 8. Drawer Actions
    document.getElementById('btn-close-drawer')?.addEventListener('click', () => this.closeDrawer());
    document.getElementById('drawer-backdrop')?.addEventListener('click', () => this.closeDrawer());

    document.getElementById('drawer-btn-open')?.addEventListener('click', () => {
      if (this.state.selectedStudy) {
        this.openStudyInViewer(this.state.selectedStudy.id);
      }
    });

    document.getElementById('drawer-btn-embed')?.addEventListener('click', () => {
      if (this.state.selectedStudy) {
        this.closeDrawer();
        this.embedStudyInModal(this.state.selectedStudy.id);
      }
    });

    // 9. Upload Modal Handling
    const uploadModal = document.getElementById('modal-upload');
    const fileInput = document.getElementById('file-input-dicom');
    const dropzone = document.getElementById('upload-dropzone');
    const submitUploadBtn = document.getElementById('btn-submit-upload');

    document.getElementById('btn-open-upload')?.addEventListener('click', () => {
      uploadModal.classList.add('open');
      this.state.selectedUploadFiles = [];
      document.getElementById('upload-file-list').innerHTML = '';
      submitUploadBtn.disabled = true;
    });

    document.getElementById('btn-close-upload')?.addEventListener('click', () => uploadModal.classList.remove('open'));
    document.getElementById('btn-cancel-upload')?.addEventListener('click', () => uploadModal.classList.remove('open'));

    document.getElementById('btn-browse-files')?.addEventListener('click', (e) => {
      e.stopPropagation();
      fileInput.click();
    });

    dropzone?.addEventListener('click', () => fileInput.click());

    dropzone?.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });

    dropzone?.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

    dropzone?.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files?.length) {
        this.handleUploadFilesSelection(Array.from(e.dataTransfer.files));
      }
    });

    fileInput?.addEventListener('change', (e) => {
      if (e.target.files?.length) {
        this.handleUploadFilesSelection(Array.from(e.target.files));
      }
    });

    submitUploadBtn?.addEventListener('click', async () => {
      if (this.state.selectedUploadFiles.length === 0) return;

      submitUploadBtn.disabled = true;
      submitUploadBtn.textContent = 'Uploading...';

      const formData = new FormData();
      this.state.selectedUploadFiles.forEach(f => formData.append('dicomFiles', f));

      try {
        const res = await ApiService.uploadDicomFiles(formData);
        this.showToast(`Uploaded ${res.uploadedCount || 0} DICOM instance(s) successfully!`, 'success');
        uploadModal.classList.remove('open');
        await this.loadStudies();
      } catch (err) {
        this.showToast(`Upload failed: ${err.message}`, 'error');
      } finally {
        submitUploadBtn.disabled = false;
        submitUploadBtn.textContent = 'Upload to PACS';
      }
    });

    // 10. Server Settings Modal Handling
    const settingsModal = document.getElementById('modal-settings');
    document.getElementById('btn-settings')?.addEventListener('click', () => {
      document.getElementById('setting-server-ip').value = MedDreamViewer.config.serverIp;
      document.getElementById('setting-meddream-port').value = MedDreamViewer.config.port;
      settingsModal.classList.add('open');
    });

    document.getElementById('btn-close-settings')?.addEventListener('click', () => settingsModal.classList.remove('open'));
    
    document.getElementById('btn-save-settings')?.addEventListener('click', () => {
      const ip = document.getElementById('setting-server-ip').value.trim() || 'localhost';
      const port = parseInt(document.getElementById('setting-meddream-port').value, 10) || 8080;
      
      MedDreamViewer.config.serverIp = ip;
      MedDreamViewer.config.port = port;
      localStorage.setItem('meddream_server_ip', ip);
      localStorage.setItem('meddream_server_port', port.toString());

      this.showToast(`Viewer configuration updated (${ip}:${port})`, 'success');
      settingsModal.classList.remove('open');
      this.render();
    });

    document.getElementById('btn-reset-settings')?.addEventListener('click', () => {
      localStorage.removeItem('meddream_server_ip');
      localStorage.removeItem('meddream_server_port');
      MedDreamViewer.config.serverIp = window.location.hostname || 'localhost';
      MedDreamViewer.config.port = 8080;
      document.getElementById('setting-server-ip').value = MedDreamViewer.config.serverIp;
      document.getElementById('setting-meddream-port').value = 8080;
      this.showToast('Settings reset to defaults', 'info');
      settingsModal.classList.remove('open');
      this.render();
    });

    // Escape listener for modals
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        uploadModal.classList.remove('open');
        settingsModal.classList.remove('open');
        this.closeDrawer();
      }
    });
  },

  handleUploadFilesSelection(files) {
    this.state.selectedUploadFiles = files;
    const listEl = document.getElementById('upload-file-list');
    listEl.innerHTML = '';

    files.forEach(f => {
      const item = document.createElement('div');
      item.style.cssText = 'display: flex; justify-content: space-between; padding: 4px 8px; background: #F8FAFC; border-radius: 4px; border: 1px solid #E2E8F0;';
      item.innerHTML = `
        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 300px; font-weight: 500;">${this.escapeHtml(f.name)}</span>
        <span style="color: #64748B; font-family: var(--font-mono); font-size: 0.75rem;">${(f.size / 1024).toFixed(1)} KB</span>
      `;
      listEl.appendChild(item);
    });

    document.getElementById('btn-submit-upload').disabled = files.length === 0;
  }
};

// Launch App when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
