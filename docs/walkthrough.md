# Walkthrough - MedDream Token-Enabled Authentication Integration

We have updated the MedDream viewer integration to use **Token-Based Authentication** (`http://SERVER:8080/?token={TOKEN}`) following MedDream's official HIS authentication architecture, completely replacing unauthenticated direct study parameter URLs.

---

## 🔒 Security Architecture & Workflow

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

### Key Security Implementations:
1. **Cryptographically Secure Tokens**:
   - Backend generates 256-bit cryptographically secure random tokens (`crypto.randomBytes(32).toString('hex')`).
   - Time-to-Live (TTL): 5 minutes (300 seconds). Expired tokens are purged automatically.
2. **Backend Validation Endpoint (`/api/token/v4/validate`)**:
   - MedDream contacts this validator when a token URL is accessed.
   - Valid tokens return Softneta's `com.softneta.token.model.v4.Request` JSON schema with study instance UID, PACS storage ID, permissions, and institution user details.
   - Invalid, missing, or expired tokens return `401 Unauthorized`.
3. **Restricted Direct Access**:
   - Configured `authentication.his.tokenServiceAddress=http://host.docker.internal:3000/api/token` in `config/application.properties`.
   - MedDream automatically rejects unauthenticated direct study/patient parameters (`?study=...`, `?patient=...`, `?accnum=...`) without a valid token.
4. **No Client-Side Secrets**:
   - No signing secrets, database credentials, or PACS master keys are exposed to the browser.
   - Frontend only requests temporary tokens per viewing session.

---

## 🧪 Verification Results

| Test Scenario | Request | Expected Result | Actual Result | Status |
|---|---|---|---|---|
| **Token Generation** | `POST /api/token/generate` | Returns 64-char hex token & viewer URL | 200 OK with `token: "4ccfbd8..."` | ✅ PASSED |
| **Token Validation** | `GET /api/token/v4/validate?token={VALID_TOKEN}` | Returns Softneta JSON Schema | 200 OK with `items`, `permissions`, `user` | ✅ PASSED |
| **Invalid Token Rejection (Backend)** | `GET /api/token/v4/validate?token=fake_or_tampered_token` | HTTP 401 Unauthorized | 401 Unauthorized (`"Token is invalid or has expired"`) | ✅ PASSED |
| **MedDream Authorized Access** | `GET http://localhost:8080/his?token={VALID_TOKEN}` | HTTP 200 OK with study details | 200 OK (`{"studyIds":[{"studyUid":"1.2.410...","storageId":"PACS","modality":"CR"}]}`) | ✅ PASSED |
| **MedDream Invalid Token Rejection** | `GET http://localhost:8080/his?token=fake_or_tampered_token` | HTTP 403 Forbidden | 403 Forbidden | ✅ PASSED |
| **Direct Unauthenticated Param Rejection** | `GET http://localhost:8080/his?study=1.2.410...` | HTTP 403 Forbidden | 403 Forbidden | ✅ PASSED |

---

## 🛡️ Production Recommendations & Security Checklist

1. **HTTPS / TLS Enforcement**:
   - Always run MedDream and the token validation service behind HTTPS/TLS in production (e.g. reverse proxy like NGINX or Traefik) to prevent token interception over the network.
2. **Shared Secret / Basic Auth on Token Service**:
   - In `config/application.properties`, configure `authentication.his.tokenServiceAuthUsername` and `authentication.his.tokenServiceAuthPassword` so only MedDream can query the `/api/token/v4/validate` endpoint.
3. **Single-Use Token Consumption**:
   - In high-security environments, tokens can be invalidated immediately upon first successful validation by MedDream (`tokenStore.delete(token)`), ensuring replay protection.
4. **CORS & Framing Policies**:
   - Configure `security.contentSecurityPolicy` in `config/application.properties` with explicit `frame-ancestors` origins matching your production domain.
