# MedDream DICOM Study Hub (Demo Web Application)

A modern, responsive web application demonstrating DICOM study management and seamless integration with the **MedDream DICOM Viewer** and **Orthanc PACS**.

---

## 🌟 Key Features

- **Live DICOM Study List**: Queries Orthanc PACS in real-time, displaying patient names, IDs, study dates, modalities, descriptions, series/instances count, and Study Instance UIDs.
- **Instant Search & Filtering**: Fast search across Patient Name, ID, Accession Number, Study Description, and UID.
- **Dynamic Modality Badges**: Visual color-coded tags for `CT`, `MR`, `CR`, `DX`, `US`, `XA`, `NM`, etc., with one-click filter pills.
- **Dual View Modes**: Switch seamlessly between **Table View** and **Card Grid View**.
- **MedDream Viewer Integration**:
  - **Direct Launch**: Opens the study in a new tab using the URL scheme:
    ```text
    http://<SERVER_IP>:8080/?study=<STUDY_INSTANCE_UID>
    ```
  - **Embedded Viewer Modal**: Full-featured interactive modal with embedded `<iframe>`, fullscreen mode, and URL copy.
- **Slide-in Study Details Drawer**: Deep metadata inspection and series breakdown with instance counts.
- **Loading, Empty, and Error States**: Polished skeleton loading animation, customizable empty states, and diagnostic PACS error banners.
- **Sample Import & DICOM Upload**: One-click standard sample study import from Cornerstone repository, plus drag-and-drop DICOM `.dcm` upload.
- **Server IP / Port Configurator**: Easily adjust target viewer IP/port for LAN or WAN deployments.

---

## 🚀 Getting Started

### Option A: Run Entire Stack via Docker Compose (Recommended)
From the repository root, start all services (Orthanc PACS + MedDream Viewer + Demo Hub):
```bash
docker compose -f docker-compose.demo.yml up -d --build
```

### Option B: Run Web App Locally with Node.js
```bash
# 1. Start backend PACS & Viewer services (from root)
docker compose up -d

# 2. Run Demo App (from demo folder)
cd demo
npm install
npm start
```

### Option C: Run Demo Container Standalone
```bash
cd demo
docker compose up -d --build
```

Open your browser and navigate to:
```text
http://localhost:3000
```

---

## 🔌 API Endpoints Provided by Demo Backend

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/studies` | Returns normalized list of all DICOM studies |
| `GET` | `/api/studies/:id` | Detailed study breakdown with series & instances |
| `GET` | `/api/config` | Runtime config (server IP, MedDream viewer URL) |
| `GET` | `/api/health` | Healthcheck for Orthanc PACS and MedDream |
| `POST` | `/api/import-sample` | Downloads & imports standard test CT DICOM to Orthanc |
| `POST` | `/api/upload` | Uploads multipart `.dcm` files to Orthanc |

---

## 📁 Demo Project Structure

```text
demo/
├── package.json          # Node.js project manifest & scripts
├── server.js             # Express API server & PACS proxy
├── README.md             # Demo documentation
└── public/
    ├── index.html        # Main single-page web app
    ├── css/
    │   └── style.css     # Clinical PACS design system & animations
    └── js/
        ├── api.js        # REST API client
        ├── viewer.js     # MedDream viewer URL builder & iframe manager
        └── app.js        # App state, filtering, rendering, event listeners
```
