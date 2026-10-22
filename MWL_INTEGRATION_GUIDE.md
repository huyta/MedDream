# Dynamic DICOM Modality Worklist (MWL) Integration Guide
## Orthanc PACS & .NET Core RIS API Integration

This guide documents the architecture, data flow, DICOM tag mappings, and operational steps for running a dynamic DICOM Modality Worklist (MWL) Service Class Provider (SCP) using Orthanc PACS, an Orthanc Python Plugin, and a .NET Core RIS API backed by PostgreSQL.

---

## 1. System Architecture & C-FIND Flow

```
+-----------------------------------------------------------------------------------+
|                            Hospital Network / VLAN                                |
|                                                                                   |
|  +--------------------+                                                           |
|  | Imaging Modalities | (CT, MRI, Ultrasound, Digital X-Ray)                      |
|  +---------+----------+                                                           |
|            |                                                                      |
|            | 1. DICOM DIMSE C-FIND Request (SOP: 1.2.840.10008.5.1.4.31)          |
|            |    Filters: Modality (0008,0060), Date (0040,0002) in (0040,0100)    |
|            v                                                                      |
|  +-------------------------------------------------------------+                  |
|  | Orthanc PACS Server (:4242 DICOM)                           |                  |
|  |                                                             |                  |
|  |  [Python Plugin: worklist_plugin.py]                        |                  |
|  |  Registered via orthanc.RegisterWorklistCallback()          |                  |
|  |  * Intercepts C-FIND queries dynamically                    |                  |
|  |  * Parses query tags & extracts Modality & Scheduled Date   |                  |
|  +-----------------------------+-------------------------------+                  |
|                                |                                                  |
|                                | 2. Synchronous HTTP GET                          |
|                                |    /api/worklist?modality=CT&date=20261022       |
|                                v                                                  |
|  +-------------------------------------------------------------+                  |
|  | .NET Core RIS Web API                                       |                  |
|  |                                                             |                  |
|  |  [WorklistController: GET /api/worklist]                    |                  |
|  |  * Queries PostgreSQL via EF Core                           |                  |
|  |  * Formats scheduled exams to DICOM Hexadecimal Tags        |                  |
|  +-----------------------------+-------------------------------+                  |
|                                |                                                  |
|                                | 3. SQL Query (Indexed SARGable Date & Status)    |
|                                v                                                  |
|  +-------------------------------------------------------------+                  |
|  | PostgreSQL Database                                         |                  |
|  | Tables: Exams (joined with Patients)                        |                  |
|  +-------------------------------------------------------------+                  |
|                                                                                   |
|  Response Path:                                                                   |
|  PostgreSQL -> .NET API (JSON Array) -> Python Plugin -> Orthanc -> Modality      |
+-----------------------------------------------------------------------------------+
```

---

## 2. DICOM Hexadecimal Tag Mapping Specifications

The .NET Core controller returns an array of JSON objects where each property is an explicit DICOM hexadecimal tag key (with commas).

| DICOM Tag | Tag Name | VR | Description / Source |
|---|---|---|---|
| `(0008,0005)` | Specific Character Set | CS | `ISO_IR 100` (Latin-1) or `ISO_IR 192` (UTF-8) |
| `(0008,0016)` | SOP Class UID | UI | `1.2.840.10008.5.1.4.31` (Modality Worklist FIND) |
| `(0008,0050)` | Accession Number | SH | `Exam.AccessionNumber` |
| `(0008,0090)` | Referring Physician's Name | PN | `Exam.ReferringPhysician` |
| `(0010,0010)` | Patient's Name | PN | Formatted as `LastName^FirstName` |
| `(0010,0020)` | Patient ID | LO | `Patient.PatientId` / `Patient.Mrn` |
| `(0010,0030)` | Patient's Birth Date | DA | `YYYYMMDD` from `Patient.BirthDate` |
| `(0010,0040)` | Patient's Sex | CS | `M`, `F`, or `O` |
| `(0020,000d)` | Study Instance UID | UI | `Exam.StudyInstanceUid` (auto-generated if null) |
| `(0032,1060)` | Requested Procedure Description | LO | `Exam.ProcedureDescription` |
| `(0040,1001)` | Requested Procedure ID | SH | `Exam.RequestedProcedureId` |
| `(0040,0100)` | Scheduled Procedure Step Sequence | SQ | Nested Array containing scheduled step item |
| ↳ `(0040,0001)` | Scheduled Station AE Title | AE | `Exam.StationAeTitle` (e.g. `CT_SCANNER_1`) |
| ↳ `(0040,0002)` | Scheduled Step Start Date | DA | `YYYYMMDD` from `Exam.ScheduledDateTime` |
| ↳ `(0040,0003)` | Scheduled Step Start Time | TM | `HHMMSS` from `Exam.ScheduledDateTime` |
| ↳ `(0008,0060)` | Modality | CS | `Exam.Modality` (`CT`, `MR`, `US`, etc.) |
| ↳ `(0040,0007)` | Scheduled Step Description | LO | `Exam.ProcedureDescription` |
| ↳ `(0040,0009)` | Scheduled Step ID | SH | `Exam.ScheduledProcedureStepId` |
| ↳ `(0040,0006)` | Scheduled Performing Physician | PN | `Exam.PerformingPhysician` |

---

## 3. Deployment Configuration

### Orthanc `orthanc.json` configuration snippet:
```json
{
  "DicomPort": 4242,
  "DicomAet": "ORTHANC",
  "DicomAlwaysAllowFindWorklist": true,
  "DicomAlwaysAllowFind": true,

  "Worklists": {
    "Enable": false
  },

  "Plugins": [
    "/usr/share/orthanc/plugins"
  ],

  "Python": {
    "ScriptPath": "/etc/orthanc/worklist_plugin.py",
    "Verbose": false
  }
}
```

> **IMPORTANT**: Ensure `"Worklists": { "Enable": false }` is set so Orthanc does not use the static file-based worklist plugin, enabling the dynamic Python callback to handle all C-FIND queries.

---

## 4. Testing & Verification

### Test 1: Verify the .NET Core RIS Controller
```bash
# Query scheduled exams for today
curl -s http://localhost:5000/api/worklist | jq .

# Query by specific modality and date
curl -s "http://localhost:5000/api/worklist?modality=CT&date=20261022" | jq .
```

### Test 2: Verify DICOM C-FIND against Orthanc
Using the provided `scripts/query_mwl.py` or DCMTK `findscu`:
```bash
# Query all worklist entries from Orthanc via C-FIND
python scripts/query_mwl.py --host localhost --port 4242 --called-aet ORTHANC

# Query specific modality
python scripts/query_mwl.py --host localhost --port 4242 --called-aet ORTHANC --modality CT
```

---

## 5. Automated Exam Status Completion (C-STORE Webhook)

When an imaging modality stores images into Orthanc (via DICOM C-STORE or REST API upload):
1. **Event Interception**: Orthanc triggers `OnStoredInstance` callback in `worklist_plugin.py`.
2. **Metadata Extraction**: Extracts Accession Number (`0008,0050`), Study Instance UID (`0020,000d`), and Modality.
3. **Non-Blocking Debouncing**: For multi-frame/CT/MRI studies containing hundreds of slices, a sliding debounce window (default: 3.0 seconds) waits for the transmission stream to settle.
4. **Asynchronous Webhook**: A background daemon worker thread posts to:
   ```
   POST /api/exams/complete
   Payload: {"accessionNumber": "...", "studyInstanceUid": "...", "instanceCount": 120}
   ```
5. **Database Transition**: `ExamStatusController.cs` updates the exam status in PostgreSQL from `Scheduled` to `Completed` with `CompletionDateTime = DateTime.UtcNow`.

### Manual Testing the Webhook
```bash
# Mark exam as completed via REST webhook directly:
curl -i -X POST http://localhost:5000/api/exams/complete \
  -H "Content-Type: application/json" \
  -d '{"accessionNumber": "ACC2026102203"}'

# Or upload a DICOM file to Orthanc to trigger it automatically:
curl -X POST http://localhost:8042/tools/create-dicom \
  -u orthanc:orthanc \
  -H "Content-Type: application/json" \
  -d '{"PatientName": "Doe^John", "PatientID": "PAT-10047", "AccessionNumber": "ACC2026102203"}'
```

