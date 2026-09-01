# MedDream Token-Based Authentication Integration Plan

Update the MedDream viewer integration from token-disabled URL (`?study={UID}`) to MedDream's official **Token-Enabled Authentication** (`?token={SECURE_TOKEN}`).

---

## Architecture & Security Workflow

```
+------------------+         1. POST /api/token/generate          +-------------------+
|  Demo Frontend   | -------------------------------------------> |   Demo Backend    |
| (No secrets held)| <------------------------------------------- | (Express Service) |
+------------------+     2. Returns { token, viewerUrl }          +-------------------+
        |                                                                   ^
        | 3. Opens http://SERVER:8080/?token={TOKEN}                        |
        v                                                                   |
+------------------+       4. GET /api/token/v4/validate?token=...          |
| MedDream Viewer  | -------------------------------------------------------+
|  (Spring HIS)    | <------------------------------------------------------+
+------------------+       5. Returns Softneta Token Model JSON
```

### Key Security Principles:
1. **No Sensitive Secrets on Client**: The browser never sees or handles signing keys, credentials, or internal PACS auth headers.
2. **Cryptographically Secure Tokens**: 256-bit entropy (`crypto.randomBytes(32).toString('hex')`) with automatic TTL expiration (default: 5 minutes) and single/multi-use controls.
3. **Restricted Direct Parameter Access**: In `application.properties`, setting `authentication.his.valid-his-params=token` ensures that unauthenticated direct study access without a valid token is rejected by MedDream.
4. **Scope-Limited Access**: Each token grants access *strictly* to the specified study/patient with configured permissions (`DOCUMENT_VIEW`, `SEARCH`, etc.).
5. **Auditing & Invalidation**: Expired or invalid tokens return `401 Unauthorized`, rejecting unauthorized viewer access.

---

## Proposed Changes

### 1. MedDream Server Configuration
#### [MODIFY] [config/application.properties](file:///Users/matt/Documents/MedDream/config/application.properties)
- Configure `authentication.his.valid-his-params=token` (reject unauthenticated `?study=...` URLs).
- Configure `authentication.his.tokenServiceAddress=http://host.docker.internal:3000/api/token` (or `http://demo:3000/api/token` in docker-compose).
- Set `authentication.his.useSameSession=false` for isolated secure token sessions.

### 2. Backend Server Token Service
#### [MODIFY] [demo/server.js](file:///Users/matt/Documents/MedDream/demo/server.js)
- Add secure in-memory / cache token store with automatic TTL pruning.
- Add `POST /api/token/generate` endpoint:
  - Validates requested study with Orthanc PACS.
  - Generates a cryptographically secure token.
  - Returns `{ success: true, token, viewerUrl: "http://SERVER:8080/?token=" + token }`.
- Add `GET /api/token/v4/validate` (and fallback `/api/token/validate`):
  - Validates incoming token query parameter (`?token=...`).
  - Returns official Softneta `com.softneta.token.model.v4.Request` JSON payload with study instance UID, PACS storage ID, permissions, and institution metadata.
  - Returns `401 Unauthorized` if token is missing, expired, or invalid.

### 3. Frontend Viewer Integration
#### [MODIFY] [demo/public/js/api.js](file:///Users/matt/Documents/MedDream/demo/public/js/api.js)
- Add `ApiService.generateViewerToken(studyData)` to request a secure token before opening the viewer.

#### [MODIFY] [demo/public/js/viewer.js](file:///Users/matt/Documents/MedDream/demo/public/js/viewer.js)
- Update `openInNewTab(study)` and `openEmbedded(study)` to dynamically obtain a secure viewer token and load `http://SERVER_IP:8080/?token={TOKEN}`.
- Preserve fullscreen, copy link, and embedded iframe features seamlessly.

### 4. Docker & Orchestration Updates
#### [MODIFY] [demo/docker-compose.yml](file:///Users/matt/Documents/MedDream/demo/docker-compose.yml) & [docker-compose.demo.yml](file:///Users/matt/Documents/MedDream/docker-compose.demo.yml)
- Pass `TOKEN_SERVICE_HOST` and container network mappings.

---

## Verification Plan

### Automated & API Verification
1. **Token Generation**: Call `POST /api/token/generate` with valid study UID, verify returned 64-char hex token and URL format.
2. **Valid Token Validation**: Call `GET /api/token/v4/validate?token={VALID_TOKEN}`, verify 200 OK with Softneta JSON schema (`items`, `permissions`, `user`).
3. **Invalid Token Rejection**: Call `GET /api/token/v4/validate?token=invalid_or_fake_token`, verify 401 Unauthorized response.
4. **Expired Token Rejection**: Test token TTL expiration after expiry window.
5. **Direct Parameter Rejection**: Attempt to access MedDream directly via `http://localhost:8080/?study=1.2.410...` without token, verify rejection/login redirect.
6. **Viewer Loading**: Open `http://localhost:8080/?token={VALID_TOKEN}` in browser, verify MedDream loads the DICOM images properly.
