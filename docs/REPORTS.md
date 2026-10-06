# Sentinel-AI Compliance Reporting & Forensic Exports (Phase 5C)

## 1. Overview & Architectural Principles

The Sentinel-AI Reporting & Forensic Export engine generates cryptographically verified, print-ready compliance reports and forensic data exports directly on the edge. Designed for deployment on Raspberry Pi 4/5 and Windows workstations, it provides tamper-evident documentation for safety auditors, emergency responders, and system engineers without cloud dependencies.

### Core Architecture Rules:
1. **Local Report Generation & Storage**: Reports are written directly into a managed `reports/` directory with an immutable JSON manifest (`reports/manifest.json`). Every generated artifact is stamped with its cryptographic SHA-256 digest.
2. **Audit Ledger Logging**: Every report generation and download action is permanently recorded in the `operator_actions` table with the operator ID, role, client IP, report type, and target file hash.
3. **Role-Based Access Control (RBAC)**: Only authorized roles can generate or download specific report types. Viewers and unauthenticated sessions cannot initiate exports or access forensic archives.
4. **Streamed & Injection-Safe CSV Export**: Incident CSV exports are streamed chunk-by-chunk to maintain a minimal memory footprint on the Raspberry Pi. All cells are sanitized against spreadsheet formula and DDE injection attacks.
5. **Print-Friendly HTML + PDF Fallback**: Reports are formatted with high-contrast, print-optimized HTML templates (`@media print` CSS rules, page-break management). If a PDF engine (such as ReportLab) is available, PDFs are compiled directly; otherwise, standard print-ready HTML is delivered without failure.
6. **Forensic Integrity & Tamper Detection**: The built-in evidence verification engine re-hashes physical media files (keyframes, audio recordings, sensor dumps) and compares them against SQLite ledger digests to flag any unauthorized tampering or file deletion.

---

## 2. Supported Report Types

| Type Identifier | Report Name | Authorized Roles | Content & Scope |
|---|---|---|---|
| `monthly` | **Monthly Operations Report** | `COMMANDER`, `OPERATOR` | Executive overview of incident volume, MTTA/MTTR response times, false alarm rate, zone risk distribution, and peak alert periods. |
| `assurance` | **Model Assurance & Verification** | `COMMANDER`, `ENGINEER` | Machine learning model inventory, verification statuses, held-out F1 scores, runtime usage restrictions, and degraded fallback states. |
| `drift` | **Model Drift Monitoring Report** | `COMMANDER`, `ENGINEER` | Population Stability Index (PSI) timelines, feature distribution shifts, out-of-distribution (OOD) rates, and model retirement recommendations. |
| `health` | **Device Health & Availability** | `COMMANDER`, `ENGINEER` | Sensor uptime percentages (Camera, Audio, I2C/SPI), hardware fault histories, thermal throttling incidents, and stream degradation logs. |
| `evidence` | **Forensic Evidence Package Index** | `COMMANDER`, `OPERATOR`, `ENGINEER` | Index of all captured media files (MP4, WAV, JPG), linked incident IDs, capture timestamps, file sizes, and SHA-256 hashes. |
| `csv` | **Incident Records CSV Export** | `COMMANDER`, `OPERATOR` | Raw tabular export of incidents matching query filters, sanitized against formula injection. |

---

## 3. CSV Formula Injection Defense

Spreadsheet programs (Microsoft Excel, LibreOffice Calc, Google Sheets) interpret cells starting with specific characters as executable formulas or Dynamic Data Exchange (DDE) commands:
* `=`, `+`, `-`, `@`
* Tab (`\t`), Carriage Return (`\r`)

If an attacker crafts an incident payload or outcome string such as:
```text
=CMD|' /C calc'!A0
```
Opening an unescaped CSV export could execute arbitrary system commands on the operator's workstation.

### Defense Mechanism:
Before writing any cell to the CSV stream, Sentinel-AI invokes `sanitize_csv_cell()`:
```python
def sanitize_csv_cell(value: Any) -> str:
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s
```
By prefixing dangerous leading characters with a single apostrophe (`'`), spreadsheet software treats the cell value strictly as plain text, preventing code execution while preserving human readability.

---

## 4. Evidence Verification & Tamper Detection

The `EvidenceVerifier` engine validates chain-of-custody integrity by re-computing the SHA-256 hash of each evidence file on disk:

$$H_{\text{actual}} = \text{SHA256}(\text{file\_bytes})$$

* **Match**: $H_{\text{actual}} == H_{\text{ledger}}$ $\rightarrow$ Status: `VERIFIED`.
* **Tampered**: $H_{\text{actual}} \neq H_{\text{ledger}}$ $\rightarrow$ Status: `TAMPERED` (Expected vs Actual recorded).
* **Missing**: File not present at registered path $\rightarrow$ Status: `MISSING`.

Any discrepancy is flagged immediately in the CLI output and permanently logged to the SQLite audit trail.

---

## 5. Command-Line Interface (CLI)

The reporting module provides a command-line interface:

### 5.1 Generate Reports
```bash
# Generate monthly operations report for October 2026
python -m src.reports generate --type monthly --month 2026-10

# Generate model assurance report as PDF
python -m src.reports generate --type assurance --format pdf --role ENGINEER

# Generate device health report into a custom directory
python -m src.reports generate --type health --output-dir /opt/sentinel/reports --role ENGINEER
```

### 5.2 Verify Evidence Integrity
```bash
# Re-hash all physical evidence files against SQLite database records
python -m src.reports verify-evidence

# Verify a standalone exported evidence package against its manifest.json
python -m src.reports verify-evidence --manifest /path/to/exported/manifest.json
```

### 5.3 List Generated Reports
```bash
python -m src.reports list
```

---

## 6. HTTP REST API Endpoints

| Endpoint | Method | Role Required | Description |
|---|---|---|---|
| `/api/reports/generate` | `POST` | Role-Specific | Triggers background or synchronous generation of a report artifact. |
| `/api/reports/list` | `GET` | Authenticated | Lists all generated reports in the local manifest. |
| `/api/reports/download` | `GET` | Role-Specific | Streams a generated HTML or PDF report artifact; audit-logged. |
| `/api/export/incidents.csv` | `GET` | `COMMANDER`, `OPERATOR` | Streams filtered incident records as injection-safe CSV. |
| `/api/evidence/verify` | `POST` | `COMMANDER`, `ENGINEER` | Executes on-demand evidence file re-hashing and reports results. |

All endpoints require active session authentication with strict CSRF verification on state-changing requests.
