# Sentinel-AI Edge Security Hardening Architecture (Phase 5E)

## 1. Overview & Threat Model

Sentinel-AI operates as an edge-native municipal surveillance and incident response appliance. Unlike pure cloud platforms, edge devices are exposed to distinct threat vectors:
* Physical device tampering or theft.
* Local network snooping or unauthorized operator terminal access.
* Malicious input injections (CSV formulas, SQL injection, audio/video data spoofing).
* Brute-force authentication attacks on local operator dashboards.

Phase 5E implements defense-in-depth security controls tailored for edge appliances operating on Raspberry Pi 4/5 hardware and Windows workstations.

---

## 2. Core Security Controls

### 2.1 Zero Hardcoded Secrets & Secrets Hygiene
- **Environment-Driven Configuration**: All sensitive keys (session secrets, cloud API keys, admin bootstrap passwords) are loaded strictly via environment variables.
- **`.env.example` Template**: A sanitized template is maintained with placeholder values.
- **Git Protection**: `.gitignore` strictly excludes `.env`, `.env.*` (while whitelisting `.env.example`), and local user databases (`dashboard_users.local.json`).

### 2.2 Cryptographic Password Storage & Transparent Migration
- **Bcrypt Salted Hashes**: Passwords are saved with bcrypt hashing (`rounds=12`), providing robust resistance against offline dictionary and GPU cracking attacks.
- **Automatic Migration**: Any legacy plain-text accounts (e.g., from earlier phases) are automatically upgraded to bcrypt hashes on their first successful login.
- **Batch Migration CLI**: Administrators can run `python -m src.modules.security migrate-passwords` to hash all existing accounts in bulk.

### 2.3 First-Run Bootstrap Flow
- When no user accounts exist in the database, the system enters `first_run` mode.
- Operators can bootstrap the initial administrative account via:
  ```bash
  python -m src.modules.security setup-admin --username commander --role COMMANDER
  ```
  or through the first-run web setup dialog on the dashboard.

### 2.4 Session Lifecycle & CSRF Defense
- **Dual Expiration Windows**:
  - **Idle Timeout**: Sessions expire after 30 minutes (`1800s`) of user inactivity.
  - **Absolute Timeout**: Sessions are unconditionally revoked after 8 hours (`28800s`), requiring re-authentication.
- **Server-Side Invalidation**: `/api/auth/logout` explicitly deletes the session token from server memory.
- **CSRF Token Validation**: Every session issues a cryptographically random CSRF token (`X-CSRF-Token`). State-changing requests (`POST`, `PUT`, `DELETE`) require a valid matching CSRF header.
- **Cookie Security Flags**: Session cookies emit `HttpOnly`, `SameSite=Strict`, and conditionally `Secure` flags when served over HTTPS.

### 2.5 Brute-Force Rate Limiting & Audit Trail
- **Sliding-Window Limiting**: Enforces a 5-attempt limit per 15-minute window (`SENTINEL_LOGIN_MAX_ATTEMPTS=5`).
- **Account Lockout**: 5 failed login attempts trigger an immediate 15-minute lockout (`SENTINEL_LOGIN_LOCKOUT_SECONDS=900`).
- **Audit Logging**: Every failed authentication attempt is permanently written to the immutable SQLite `operator_actions` audit ledger with client IP, username, reason code, and timestamp.

### 2.6 Hardened HTTP Response Headers
Every HTTP response issued by Sentinel-AI includes standard security headers:
* `X-Content-Type-Options: nosniff`
* `X-Frame-Options: DENY`
* `X-XSS-Protection: 1; mode=block`
* `Referrer-Policy: strict-origin-when-cross-origin`
* `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:;`

### 2.7 Role-Permission Matrix & Introspection Regression Guard
Every HTTP endpoint is explicitly bound to allowed roles (`COMMANDER`, `OPERATOR`, `ENGINEER`, `VIEWER`, or Unauthenticated).
* **Automated Introspection Guard**: An automated pytest test (`test_endpoint_permission_matrix_introspection_guard`) parses `src/modules/dashboard/app.py` at build time. If any developer introduces an endpoint without a corresponding rule in `permission_matrix.py`, the test suite fails immediately.

---

## 3. Security Management CLI

```bash
# 1. First-run administrator bootstrap
python -m src.modules.security setup-admin --username commander --role COMMANDER

# 2. Add or update an operator account
python -m src.modules.security add-user operator_charlie --role OPERATOR

# 3. List registered operator accounts (redacted passwords)
python -m src.modules.security list-users

# 4. Delete an account
python -m src.modules.security delete-user test_account

# 5. Migrate all plain-text passwords to bcrypt hashes
python -m src.modules.security migrate-passwords
```

---

## 4. Assessment of Remaining Security Risks

While Phase 5E addresses authentication, session management, CSRF, and authorization, edge deployments retain inherent hardware-level and operational risks that must be managed during physical deployment:

1. **Unencrypted MicroSD Flash Storage**:
   - *Risk*: An attacker with physical access to the Raspberry Pi can extract the microSD card and read the SQLite database directly, bypassing dashboard authentication.
   - *Mitigation Recommendation*: Enable full-disk encryption (LUKS / dm-crypt) on the Pi's root filesystem, or utilize hardware TPM / secure element chips for disk key unlocking.

2. **Plaintext Local HTTP in Default Edge Mode**:
   - *Risk*: In offline local network deployments where operators connect directly to `http://<pi_ip>:8080`, unencrypted Wi-Fi or Ethernet traffic is vulnerable to packet sniffing.
   - *Mitigation Recommendation*: Terminate TLS locally using an internal reverse proxy (Caddy or Nginx) with self-signed or internal CA certificates, or bind the server strictly to `localhost` and access via SSH tunnel (`ssh -L 8080:localhost:8080 pi@edge-node`).

3. **In-Memory Session Storage**:
   - *Risk*: Dashboard sessions are stored in application memory. A service restart invalidates all active operator sessions, requiring re-login.
   - *Mitigation Recommendation*: Acceptable for edge appliances; ensures sessions do not survive cold-boot attacks.

4. **Hardware Sensor Contention / DoS**:
   - *Risk*: A malicious local process with hardware privileges could hold locks on `/dev/video0` or `/dev/i2c-1`, denying camera or sensor access to Sentinel-AI.
   - *Mitigation Recommendation*: Enforce strict Linux user permissions (`udev` rules, dedicated `sentinel` service user without root privileges) as documented in `docs/DEPLOYMENT.md`.
