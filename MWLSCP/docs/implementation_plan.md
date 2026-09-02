# DICOM Modality Worklist (MWL) SCP Provider Implementation Plan

We will build a clean, production-ready, and straightforward **DICOM Modality Worklist (MWL) Service Class Provider (SCP)** using `pydicom` and `pynetdicom`. All code, configuration, sample data, and tests will be placed under the `MWLSCP/` directory.

---

## User Review Required

> [!IMPORTANT]
> - **Default Port & AE Title**: The MWL SCP will default to AE Title `MWL_SCP` and Port `11112` (configurable via CLI options `-a / --aet` and `-p / --port` or environment variables).
> - **Worklist Data Source**: The provider will support hot-reloading `.wl` and `.dcm` DICOM files directly from a directory (defaulting to `./worklists` or `MWLSCP/worklists`), as well as importing from JSON. Any new or modified `.wl` file dropped into the folder is instantly queryable without restarting the server.
> - **Zero External Heavy Dependencies**: Only requires `pydicom` and `pynetdicom` (which are already installed in `.venv`).

---

## Proposed Architecture & File Structure

```
MWLSCP/
├── __init__.py            # Package initialization & exports
├── __main__.py            # Entry point for 'python -m MWLSCP'
├── server.py              # Main MWL SCP server (C-FIND & C-ECHO handlers, AE lifecycle)
├── matcher.py             # Standard DICOM C-FIND matching engine (wildcards, date ranges, sequences)
├── storage.py             # Worklist file loader & repository manager (hot-reloading, caching)
├── client.py              # Built-in C-ECHO & C-FIND SCU client for testing and verification
├── generator.py           # Quick CLI utility to create / convert MWL entries (.wl files)
├── config.py              # Server settings & default configuration
├── worklists/             # Default directory for .wl / .dcm worklist files (includes sample entries)
│   ├── sample_01_ct.wl
│   ├── sample_02_mr.wl
│   └── sample_03_xr.wl
├── tests/                 # Comprehensive test suite
│   ├── test_matcher.py    # Unit tests for matching engine (wildcards, dates, sequences)
│   ├── test_storage.py    # Unit tests for file loading and caching
│   └── test_server.py     # End-to-end integration tests (C-ECHO and C-FIND queries)
├── README.md              # Detailed documentation, usage examples, modality setup guide
└── Dockerfile             # Optional Dockerfile for standalone containerized deployment
```

---

## Key Features & Matching Logic

1. **DICOM Protocol Standards Supported**:
   - **Verification SOP Class** (`1.2.840.10008.1.1` - C-ECHO): Responds to ping/echo tests from imaging modalities.
   - **Modality Worklist Information Model - FIND** (`1.2.840.10008.5.1.4.31` - C-FIND): Responds to standard worklist queries.
   - **Transfer Syntaxes**: Explicit VR Little Endian, Implicit VR Little Endian, Explicit VR Big Endian, Deflated Explicit VR Little Endian.

2. **Standards-Compliant Matching Engine (`matcher.py`)**:
   - **Universal Matching**: Empty tags in query dataset (`PatientName=""`, `Modality=""`) return the corresponding value from the record.
   - **Single Value Matching**: Exact matching for identifiers, codes, and IDs (e.g. `PatientID="P1001"`, `AccessionNumber="ACC123"`).
   - **Wildcard Matching**: Supports `*` (any sequence of characters) and `?` (any single character) according to DICOM PS 3.4 (e.g. `PatientName="Smith*"` or `*John*`).
   - **Date & Date Range Matching**: Supports DICOM `DA` / `DT` single dates (`20260902`) and ranges (`20260901-20260930`, `20260901-`, `-20260930`).
   - **Sequence Matching**: Full support for matching attributes inside `ScheduledProcedureStepSequence` `(0040,0100)` such as `Modality`, `ScheduledStationAETitle`, `ScheduledProcedureStepStartDate`, `ScheduledPerformingPhysicianName`.
   - **Return Keys Filtering**: Dynamically populates the response dataset with the exact set of requested return attributes, retaining all sequence hierarchies.

3. **Live Hot-Reload Storage (`storage.py`)**:
   - Scans a directory for `.wl` and `.dcm` files.
   - Checks file modification timestamps (`mtime`) on queries so new files can be added dynamically without server restart.
   - Supports validation and gracefully skips malformed files with clear warnings.

4. **Rich CLI & Interactive Diagnostics**:
   - Starting the server: `python -m MWLSCP run --port 11112 --aet MWL_SCP`
   - Testing connectivity (Echo): `python -m MWLSCP echo --host localhost --port 11112`
   - Querying worklists (Find): `python -m MWLSCP query --modality CT --patient-name "Smith*"`
   - Adding a quick sample worklist: `python -m MWLSCP create-sample`

---

## Proposed Changes

### [NEW] `MWLSCP/__init__.py`
- Package exports (`MWLServer`, `MWLMatcher`, `WorklistDirectoryStorage`, `MWLClient`).

### [NEW] `MWLSCP/config.py`
- Configuration defaults (host, port, AE title, worklists directory, log level).

### [NEW] `MWLSCP/matcher.py`
- DICOM MWL C-FIND matching algorithm implementation with full wildcard, date range, and sequence support.

### [NEW] `MWLSCP/storage.py`
- Directory-based worklist repository with timestamp-based caching and hot reloading.

### [NEW] `MWLSCP/server.py`
- `pynetdicom` AE server with `EVT_C_ECHO` and `EVT_C_FIND` handlers, graceful shutdown, and informative logging.

### [NEW] `MWLSCP/client.py`
- Built-in C-ECHO and C-FIND SCU client to query any MWL SCP and print formatted tables.

### [NEW] `MWLSCP/generator.py`
- Helper script to generate valid `.wl` files with realistic clinical data.

### [NEW] `MWLSCP/__main__.py`
- Unified CLI interface supporting subcommands: `run`, `query`, `echo`, `list`, `create-sample`.

### [NEW] `MWLSCP/worklists/sample_*.wl`
- Sample worklist files for CT, MR, and XR modalities.

### [NEW] `MWLSCP/tests/test_*.py`
- Comprehensive test suite testing matching rules, file storage, C-ECHO, and C-FIND end-to-end.

### [NEW] `MWLSCP/README.md`
- Complete documentation, architecture diagram, usage guide, integration with modalities (GE, Siemens, Philips, Canon, etc.), and troubleshooting tips.

---

## Verification Plan

### Automated Tests
- Run unit and integration tests using `.venv/bin/python -m unittest discover -s MWLSCP/tests` or `pytest`.
- Test wildcard matching (`*`, `?`), date range matching, modality filtering, and empty return keys.
- Test C-ECHO and C-FIND over loopback network connection.

### Manual / CLI Verification
1. Start `MWLSCP` in background or test process.
2. Execute C-ECHO ping test: `python -m MWLSCP echo`
3. Execute C-FIND queries:
   - Query all records
   - Query with modality filter (`--modality CT`)
   - Query with wildcard patient name (`--patient-name "Smith*"`)
   - Query with date filter
4. Drop a new `.wl` file into `MWLSCP/worklists/` and verify immediate detection without server restart.
5. Query using the existing `scripts/query_mwl.py` to confirm interoperability with existing tools.
