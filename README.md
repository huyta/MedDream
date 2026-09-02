# MedDream DICOM Viewer & Orthanc PACS (Docker Setup)

This repository provides a complete, production-ready **Docker Compose** environment for running **MedDream DICOM Viewer** integrated with **Orthanc PACS**.

---

## 📁 Directory Structure

```text
MedDream/
├── docker-compose.yml              # Core Docker Compose orchestration
├── .env.example                   # Environment variable template
├── .env                           # Active environment configuration
├── config/
│   ├── orthanc.json               # Orthanc PACS server & DICOMweb configuration
│   └── application.properties     # MedDream viewer & PACS backend configuration
├── demo/                          # DICOM Study Management & Viewing Web Application
│   ├── package.json               # Demo dependencies & scripts
│   ├── server.js                  # Express PACS proxy & API backend
│   ├── public/                    # Frontend UI (HTML, CSS, JS)
│   └── README.md                  # Demo guide
├── scripts/
│   └── import_sample.sh           # Script to import DICOM files and output viewer URLs
└── README.md                      # Complete setup & operations guide
```

---

## 💻 DICOM Study Management Demo Web App

A responsive web application is available in `demo/` to browse studies, search/filter, and view them directly in MedDream:

```bash
cd demo
npm install
npm start
```
Access at: `http://localhost:3000`

---

## 🚀 Quick Start

### 1. Start Services
```bash
docker compose up -d
```

### 2. Verify Container Health
```bash
docker compose ps
```

Both containers (`meddream-viewer` and `meddream-orthanc`) will display `healthy`.

### 3. Upload Sample DICOM
```bash
./scripts/import_sample.sh
```
This automatically fetches a standard test study, uploads it to Orthanc, and outputs the direct MedDream URL.

---

## 🌐 Endpoints & URLs

| Service | Host Port | Internal Port | Description |
| :--- | :--- | :--- | :--- |
| **MedDream Viewer** | `8080` | `8080` | Web DICOM Viewer |
| **Orthanc REST API / UI** | `8042` | `8042` | Orthanc Explorer & REST API |
| **Orthanc DICOM DIMSE** | `4242` | `4242` | C-STORE / C-FIND / C-MOVE port |

### Viewing Studies by Study Instance UID
Navigate to:
```text
http://<SERVER_IP>:8080/?study=<STUDY_INSTANCE_UID>
```
*Example with uploaded sample:*
```text
http://localhost:8080/?study=1.3.6.1.4.1.5962.1.2.2.20040826185059.5457
```

---

## 🖼️ Iframe Embedding & LIMS / HIS Integration

To embed MedDream inside an `<iframe>` within your Laboratory Information Management System (LIMS), Electronic Health Record (EHR), or Hospital Information System (HIS), the security headers are configured in [config/application.properties](file:///Users/matt/Documents/MedDream/config/application.properties):

```properties
# 1. Disable restrictive legacy X-Frame-Options (ALLOW-FROM is deprecated by modern browsers)
security.frameOptionsPolicy=NONE

# 2. Configure Content-Security-Policy (CSP) frame-ancestors for your LIMS origin(s)
# Replace * or append specific origins, e.g., 'self' https://lims.yourdomain.com http://localhost:3000
security.contentSecurityPolicy=frame-ancestors 'self' *; default-src 'self'; base-uri 'self'; object-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-eval'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self' blob:; worker-src 'self' blob:; form-action 'self';

# 3. Allow postMessage cross-window communication from your LIMS parent window
security.postMessageWhitelist=*

# 4. Cross-origin authorization
security.authAllowedOrigins=*
```

### HTML Embedding Example

```html
<iframe
  src="http://localhost:8080/?study=1.3.6.1.4.1.5962.1.2.2.20040826185059.5457"
  width="100%"
  height="800px"
  frameborder="0"
  allow="clipboard-read; clipboard-write; fullscreen"
  allowfullscreen>
</iframe>
```

---

## 📋 DICOM Modality Worklist (MWL)
Orthanc is configured with the **Modality Worklists plugin** to serve scheduled radiological procedures to modalities (CT, MRI, Ultrasound, Digital X-Ray) over DICOM C-FIND (`1.2.840.10008.5.1.4.31`) on port `4242`.

### Setup Python Environment
```bash
# Activate the existing virtual environment:
source .venv/bin/activate

# Or recreate and install if needed:
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1. Generate Worklist Files (.wl)
Use the Python generator in `scripts/create_mwl.py`:
```bash
# Generate sample worklists for CT, MR, US, DX
python scripts/create_mwl.py sample --out-dir ./worklists

# Or create a custom MWL entry
python scripts/create_mwl.py create \
    --patient-id "PAT-10045" \
    --patient-name "Doe^John" \
    --patient-dob "1985-06-20" \
    --patient-sex "M" \
    --modality "CT" \
    --station-ae "CT_SCANNER_01" \
    --procedure-desc "CT Chest with Contrast" \
    --priority "STAT" \
    --output "./worklists/pat10045_ct.wl"

# Or batch generate from JSON
python scripts/create_mwl.py batch --input scripts/sample_worklists.json --out-dir ./worklists
```

### 2. Query Worklists via DICOM C-FIND (MWL SCU)
Verify and query active worklist entries served by Orthanc:
```bash
# Query all worklist entries
python scripts/query_mwl.py

# Query by modality
python scripts/query_mwl.py --modality CT

# Query by patient ID or name
python scripts/query_mwl.py --patient-id P1001
```

---

## 🗄️ Database Scaling & Migration

By default, the stack uses an embedded **SQLite** engine suitable for testing and development. When scaling up for production:
- See the complete [DATABASE_MIGRATION.md](file:///Users/matt/Documents/MedDream/DATABASE_MIGRATION.md) for step-by-step guides on upgrading to **PostgreSQL** or **MySQL/MariaDB**, hybrid storage strategies, and backup/restore workflows.


