# DICOM Modality Worklist (MWL) SCP Provider

A lightweight, high-performance, and standards-compliant **DICOM Modality Worklist (MWL) Service Class Provider (SCP)** built with `pydicom` and `pynetdicom`.

Designed to serve imaging modalities (CT, MR, US, DX, CR, XA, etc.) and PACS systems with zero complex database setup required.

---

## Features

- **DICOM Standards Compliant**:
  - **Verification SOP Class** (`1.2.840.10008.1.1` - C-ECHO SCP) for modality ping / echo connection tests.
  - **Modality Worklist Information Model - FIND** (`1.2.840.10008.5.1.4.31` - C-FIND SCP).
  - Transfer Syntaxes: Explicit VR Little Endian, Implicit VR Little Endian, Explicit VR Big Endian, Deflated Explicit VR Little Endian.
- **Advanced C-FIND Matching Engine**:
  - Single-value exact matching (Patient ID, Accession Number, etc.).
  - Wildcard matching (`*` and `?`) for Patient Names, Descriptions, and IDs.
  - DICOM Date & Date-Range matching (`YYYYMMDD`, `YYYYMMDD-YYYYMMDD`, `YYYYMMDD-`, `-YYYYMMDD`).
  - Sequence matching for `ScheduledProcedureStepSequence` (`(0040,0100)`: Modality, Date, Station AE Title, Performing Physician).
  - Return Keys filtering: accurately reconstructs and returns only the requested DICOM attributes.
- **Live Hot-Reload Storage**:
  - Dynamically reads `.wl` and `.dcm` files from disk without restarting the server.
- **Built-in CLI & SCU Client**:
  - Test DICOM ping (`C-ECHO`) and worklist query (`C-FIND`) directly from the command line with clean tabular output.

---

## Installation & Requirements

Requires Python 3.9+ with `pydicom` and `pynetdicom`:

```bash
pip install pydicom pynetdicom
```

---

## Quick Start

### 1. Generate Sample Worklists
```bash
python -m MWLSCP sample
```
This populates `MWLSCP/worklists/` with sample `.wl` files (CT, MR, DX, US).

### 2. Start the MWL SCP Server
```bash
python -m MWLSCP run --port 11112 --aet MWL_SCP
```

### 3. Verify Connection (C-ECHO)
In another terminal:
```bash
python -m MWLSCP echo --host localhost --port 11112
```

### 4. Query Worklists (C-FIND)
```bash
# Query all worklists:
python -m MWLSCP query --host localhost --port 11112

# Query by Modality:
python -m MWLSCP query --host localhost --port 11112 --modality CT

# Query by Patient Name with wildcard:
python -m MWLSCP query --host localhost --port 11112 --patient-name "*Smith*"

# Query by Scheduled Date:
python -m MWLSCP query --host localhost --port 11112 --date 20260902
```

---

## CLI Reference

| Command | Description | Example |
|---|---|---|
| `run` | Starts the MWL SCP daemon | `python -m MWLSCP run -p 11112 -a MWL_SCP -w ./worklists` |
| `echo` | Sends a C-ECHO DICOM ping | `python -m MWLSCP echo -H localhost -p 11112 -c MWL_SCP` |
| `query` | Queries worklists with filters | `python -m MWLSCP query -H localhost -p 11112 -m MR` |
| `list` | Lists all local `.wl` files | `python -m MWLSCP list -w ./worklists` |
| `sample` | Generates sample `.wl` files | `python -m MWLSCP sample -o ./worklists` |
| `create` | Creates a custom `.wl` file | `python -m MWLSCP create --patient-id P1010 --patient-name "Doe^Jane" --modality CT` |

---

## Python API Usage

### Running the Server Programmatically
```python
from MWLSCP import MWLServer, ServerConfig

config = ServerConfig(
    host="0.0.0.0",
    port=11112,
    ae_title="MWL_SCP",
    worklists_dir="./worklists",
    log_level="INFO",
    hot_reload=True,
)

server = MWLServer(config)
server.start(block=True)
```

### Querying the Server (SCU) Programmatically
```python
from MWLSCP import MWLClient, format_mwl_results_table

client = MWLClient(calling_aet="MY_MODALITY")

# Ping server
if client.echo(host="localhost", port=11112, called_aet="MWL_SCP"):
    print("SCP is responsive!")

# Search worklists
results = client.query(
    host="localhost",
    port=11112,
    called_aet="MWL_SCP",
    modality="CT",
    patient_name="*Smith*",
)

print(format_mwl_results_table(results))

for ds in results:
    print(f"Patient: {ds.PatientName}, ID: {ds.PatientID}, Modality: {ds.ScheduledProcedureStepSequence[0].Modality}")
```

### Generating Custom `.wl` Files Programmatically
```python
from pathlib import Path
import pydicom
from MWLSCP import create_worklist_dataset

ds = create_worklist_dataset(
    patient_id="PAT-9001",
    patient_name="Wayne^Bruce",
    patient_sex="M",
    patient_dob="19750219",
    accession_number="ACC-9001",
    modality="CT",
    requested_procedure_desc="CT Brain without Contrast",
    scheduled_date="20260902",
    scheduled_time="140000",
    scheduled_station_ae="CT_ROOM_1",
)

pydicom.dcmwrite("worklists/pat9001.wl", ds, enforce_file_format=True)
```

---

## Modality Configuration Guide

To connect an imaging modality (GE, Siemens, Philips, Canon, Hologic, etc.) or a DICOM workstation to this MWL SCP:

1. In the modality's Worklist / HIS-RIS / DICOM Service settings:
   - **Service Name**: `Modality Worklist (MWL)` / `DICOM C-FIND`
   - **Called AE Title**: `MWL_SCP` (or your chosen `-a` AE title)
   - **Host / IP Address**: IP address of the machine running MWL SCP
   - **Port**: `11112` (or your chosen `-p` port)
   - **Calling AE Title**: The station's AE title (e.g. `CT_SCANNER_1`)
2. Click **Echo / Verify / Ping** on the modality to test the link.
3. Perform a **Query / Refresh Worklist** on the modality console.

---

## Testing

Run the full automated test suite:
```bash
python -m unittest discover -s MWLSCP/tests -v
```
