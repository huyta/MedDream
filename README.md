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
├── scripts/
│   └── import_sample.sh           # Script to import DICOM files and output viewer URLs
└── README.md                      # Complete setup & operations guide
```

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

## 🗄️ Database Scaling & Migration

By default, the stack uses an embedded **SQLite** engine suitable for testing and development. When scaling up for production:
- See the complete [DATABASE_MIGRATION.md](file:///Users/matt/Documents/MedDream/DATABASE_MIGRATION.md) for step-by-step guides on upgrading to **PostgreSQL** or **MySQL/MariaDB**, hybrid storage strategies, and backup/restore workflows.

