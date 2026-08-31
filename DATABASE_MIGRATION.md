# Database Migration & Production Scaling Guide

This guide explains how to transition your MedDream & Orthanc PACS stack from the default **SQLite** database to **PostgreSQL** (recommended) or **MySQL / MariaDB** for production workloads.

---

## 📊 Database Architecture Overview

Orthanc separates PACS data into two components:

1. **Metadata Index:** Patient demographics, Study/Series hierarchies, DICOM tags, UID mappings.
2. **Binary Storage:** Raw pixel data / `.dcm` files.

### Storage Strategies:
- **Hybrid Storage (Recommended):**
  - `EnableIndex: true` → Stores metadata in PostgreSQL/MySQL for fast SQL search and indexing.
  - `EnableStorage: false` → Keeps raw binary DICOM files on the filesystem (faster disk throughput for large multi-gigabyte CT/MRI sets).
- **All-in-Database Storage:**
  - `EnableIndex: true` & `EnableStorage: true` → Stores both metadata and raw DICOM blobs inside the database (simplifies unified database-level replication and backups).

---

## 🐘 Option 1: Migrating to PostgreSQL (Recommended)

PostgreSQL is the gold standard for production PACS archives due to its robust concurrent transaction handling and indexing performance.

### 1. Ready-to-Use `docker-compose.postgres.yml`

Create or replace your `docker-compose.yml` with the following configuration:

```yaml
services:
  # ==========================================
  # PostgreSQL Database Server
  # ==========================================
  postgres:
    image: postgres:16-alpine
    container_name: meddream-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: orthanc_db
      POSTGRES_USER: orthanc
      POSTGRES_PASSWORD: orthanc_password
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - pacs-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U orthanc -d orthanc_db"]
      interval: 5s
      timeout: 3s
      retries: 5

  # ==========================================
  # Orthanc PACS Server (with PostgreSQL Plugin)
  # ==========================================
  orthanc:
    image: orthancteam/orthanc:24.12.0
    container_name: meddream-orthanc
    restart: unless-stopped
    ports:
      - "${ORTHANC_DICOM_PORT:-4242}:4242"
      - "${ORTHANC_HTTP_PORT:-8042}:8042"
    environment:
      ORTHANC__AUTHENTICATION_ENABLED: "true"
      ORTHANC__REGISTERED_USERS: '{"orthanc":"orthanc"}'
      DICOM_WEB__ENABLE: "true"
      DICOM_WEB__ENABLE_WADO: "true"
      # --- PostgreSQL Backend Configuration ---
      POSTGRESQL__ENABLE_INDEX: "true"
      POSTGRESQL__ENABLE_STORAGE: "false"     # Keep raw files on disk for speed
      POSTGRESQL__HOST: "postgres"
      POSTGRESQL__PORT: "5432"
      POSTGRESQL__DATABASE: "orthanc_db"
      POSTGRESQL__USERNAME: "orthanc"
      POSTGRESQL__PASSWORD: "orthanc_password"
    volumes:
      - ./config/orthanc.json:/etc/orthanc/orthanc.json:ro
      - orthanc-data:/var/lib/orthanc/db
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - pacs-network
    healthcheck:
      test: ["CMD-SHELL", "python3 -c 'import urllib.request, base64; req = urllib.request.Request(\"http://localhost:8042/system\"); req.add_header(\"Authorization\", \"Basic \" + base64.b64encode(b\"orthanc:orthanc\").decode()); exit(0 if urllib.request.urlopen(req).status == 200 else 1)'"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 5s

  # ==========================================
  # MedDream DICOM Viewer
  # ==========================================
  meddream:
    image: meddream/orthanc-dicom-viewer:8.10.0-rc.8
    container_name: meddream-viewer
    restart: unless-stopped
    ports:
      - "${MEDDREAM_PORT:-8080}:8080"
    volumes:
      - ./config/application.properties:/opt/meddream/application.properties:ro
      - ./license:/opt/meddream/license
    depends_on:
      orthanc:
        condition: service_healthy
    networks:
      - pacs-network
    healthcheck:
      test: ["CMD-SHELL", "python3 -c 'import socket; s = socket.socket(); s.settimeout(2); s.connect((\"127.0.0.1\", 8080)); s.close()'"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 25s

volumes:
  postgres-data:
    name: meddream_postgres_data
  orthanc-data:
    name: meddream_orthanc_data

networks:
  pacs-network:
    name: meddream_pacs_net
    driver: bridge
```

---

## 🐬 Option 2: Migrating to MySQL / MariaDB

If your infrastructure is standardized on MySQL or MariaDB:

### 1. Database Service Definition in Compose
```yaml
  mariadb:
    image: mariadb:11
    container_name: meddream-mariadb
    restart: unless-stopped
    environment:
      MARIADB_DATABASE: orthanc_db
      MARIADB_USER: orthanc
      MARIADB_PASSWORD: orthanc_password
      MARIADB_ROOT_PASSWORD: root_password
    volumes:
      - mariadb-data:/var/lib/mysql
    networks:
      - pacs-network
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 5s
      timeout: 3s
      retries: 5
```

### 2. Orthanc Environment Configuration
```yaml
    environment:
      # --- MySQL Backend Configuration ---
      MYSQL__ENABLE_INDEX: "true"
      MYSQL__ENABLE_STORAGE: "false"
      MYSQL__HOST: "mariadb"
      MYSQL__PORT: "3306"
      MYSQL__DATABASE: "orthanc_db"
      MYSQL__USERNAME: "orthanc"
      MYSQL__PASSWORD: "orthanc_password"
```

---

## 🔄 How to Transfer Existing DICOMs from SQLite to PostgreSQL

To migrate studies from SQLite into the new database without losing data:

### Method A: Re-import via Scripts (Easiest)
If you have raw DICOM files on disk (e.g., in `./Dicoms`):
1. Start the PostgreSQL-backed stack (`docker compose up -d`).
2. Run the import script:
   ```bash
   ./scripts/import_sample.sh ./Dicoms/
   ```

### Method B: Orthanc-to-Orthanc Network Transfer (Zero Downtime)
If migrating a live PACS server:
1. Keep the old SQLite instance running on port `8042`.
2. Start the new PostgreSQL instance on port `8043` (DICOM port `4243`).
3. Push all studies directly via DICOM C-MOVE / REST API:
   ```bash
   # Register new PACS as a peer in old Orthanc, then trigger replication:
   curl -X POST http://localhost:8042/peers/new_pacs/store -d "1.2.410.200010.1092106.8044.599992.698635.698635"
   ```

---

## 💾 Backup & Restore Procedures

### 1. PostgreSQL Database Backup
```bash
# Export metadata database:
docker exec meddream-postgres pg_dump -U orthanc orthanc_db > orthanc_backup_$(date +%F).sql

# Restore metadata database:
cat orthanc_backup.sql | docker exec -i meddream-postgres psql -U orthanc -d orthanc_db
```

### 2. Storage Directory Backup (Raw Images)
```bash
# Backup the raw storage volume:
docker run --rm \
  -v meddream_orthanc_data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/orthanc_storage_$(date +%F).tar.gz -C /data .
```
