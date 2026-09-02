"""
MWLSCP Command Line Interface (CLI)
===================================
Unified entry point for running the server, sending queries, verifying connections,
listing worklists, and generating sample data.

Usage examples:
    # 1. Run the MWL SCP server:
    python -m MWLSCP run --port 11112 --aet MWL_SCP

    # 2. Test connection with C-ECHO (DICOM ping):
    python -m MWLSCP echo --host localhost --port 11112

    # 3. Query worklists via C-FIND:
    python -m MWLSCP query --host localhost --port 11112 --modality CT

    # 4. List all stored worklist files locally:
    python -m MWLSCP list

    # 5. Generate sample worklist files:
    python -m MWLSCP sample
"""

import sys
import os
import argparse
import logging
from pathlib import Path

if __package__ is None or __package__ == "":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import ServerConfig, get_default_config
    from server import MWLServer, run_server_cli
    from client import MWLClient, format_mwl_results_table
    from storage import WorklistDirectoryStorage
    from generator import create_sample_worklist_files, create_worklist_dataset
else:
    from .config import ServerConfig, get_default_config
    from .server import MWLServer, run_server_cli
    from .client import MWLClient, format_mwl_results_table
    from .storage import WorklistDirectoryStorage
    from .generator import create_sample_worklist_files, create_worklist_dataset


def cmd_run(args: argparse.Namespace) -> None:
    """Start MWL SCP Server."""
    config = ServerConfig(
        host=args.host,
        port=args.port,
        ae_title=args.aet,
        worklists_dir=Path(args.worklists_dir),
        log_level=args.log_level.upper(),
        hot_reload=not args.no_reload,
    )
    run_server_cli(config)


def cmd_echo(args: argparse.Namespace) -> None:
    """Send C-ECHO to an SCP server."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    client = MWLClient(calling_aet=args.calling_aet)
    print(f"Pinging DICOM SCP at {args.host}:{args.port} [Called AE: {args.called_aet}]...")
    success = client.echo(host=args.host, port=args.port, called_aet=args.called_aet)
    if success:
        print("\n  [SUCCESS] C-ECHO Verification Succeeded! Server is responsive.\n")
    else:
        print("\n  [FAILED] C-ECHO Verification Failed! Could not reach or verify server.\n")
        sys.exit(1)


def cmd_query(args: argparse.Namespace) -> None:
    """Send C-FIND MWL query to an SCP server."""
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    client = MWLClient(calling_aet=args.calling_aet)
    print(f"Querying MWL SCP at {args.host}:{args.port} [Called AE: {args.called_aet}]...")

    filters = {}
    if args.patient_id:
        filters["patient_id"] = args.patient_id
    if args.patient_name:
        filters["patient_name"] = args.patient_name
    if args.modality:
        filters["modality"] = args.modality
    if args.date:
        filters["scheduled_date"] = args.date
    if args.accession:
        filters["accession_number"] = args.accession
    if args.station_ae:
        filters["station_ae"] = args.station_ae

    try:
        results = client.query(
            host=args.host,
            port=args.port,
            called_aet=args.called_aet,
            **filters,
        )
        print("\n" + format_mwl_results_table(results) + "\n")
    except Exception as err:
        print(f"\n[ERROR] Query failed: {err}\n", file=sys.stderr)
        sys.exit(1)


def cmd_list(args: argparse.Namespace) -> None:
    """List all stored worklists in local directory."""
    storage_dir = Path(args.worklists_dir)
    storage = WorklistDirectoryStorage(storage_dir, hot_reload=False)
    summaries = storage.get_summary_list()

    print(f"\nStorage Directory: {storage_dir.resolve()}")
    print(f"Total Worklist Files: {len(summaries)}\n")

    if not summaries:
        print("No .wl or .dcm files found. You can create samples with: python -m MWLSCP sample")
        return

    headers = ["File", "Patient ID", "Patient Name", "Modality", "Date", "Time", "Accession", "Status"]
    rows = []
    for s in summaries:
        rows.append([
            s["file"][:22],
            s["patient_id"][:12],
            s["patient_name"][:20],
            s["modality"][:8],
            s["scheduled_date"][:10],
            s["scheduled_time"][:8],
            s["accession_number"][:14],
            s["status"][:10],
        ])

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    sep_line = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"

    print(sep_line)
    print(header_line)
    print(sep_line)
    for row in rows:
        print("| " + " | ".join(val.ljust(col_widths[i]) for i, val in enumerate(row)) + " |")
    print(sep_line + "\n")


def cmd_sample(args: argparse.Namespace) -> None:
    """Generate sample worklist files."""
    output_dir = Path(args.output_dir)
    created = create_sample_worklist_files(output_dir)
    print(f"\nSuccessfully generated {len(created)} sample worklist file(s) in: {output_dir.resolve()}\n")
    for p in created:
        print(f"  - {p.name}")
    print("\nYou can now start the server and query these files:\n  python -m MWLSCP run\n")


def cmd_create(args: argparse.Namespace) -> None:
    """Create a single custom worklist file."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    fname = args.filename or f"mwl_{args.patient_id}_{args.modality}.wl"
    if not fname.endswith(".wl") and not fname.endswith(".dcm"):
        fname += ".wl"

    ds = create_worklist_dataset(
        patient_id=args.patient_id,
        patient_name=args.patient_name,
        patient_sex=args.patient_sex,
        patient_dob=args.patient_dob,
        accession_number=args.accession,
        modality=args.modality,
        requested_procedure_desc=args.procedure_desc,
        scheduled_date=args.date,
        scheduled_time=args.time,
        scheduled_station_ae=args.station_ae,
    )
    target_path = output_dir / fname
    import pydicom
    pydicom.dcmwrite(target_path, ds, enforce_file_format=True)
    print(f"\nCreated worklist file: {target_path.resolve()}\n")


def main() -> None:
    """CLI Argument Parser."""
    default_cfg = get_default_config()

    parser = argparse.ArgumentParser(
        prog="python -m MWLSCP",
        description="DICOM Modality Worklist (MWL) SCP Server & SCU Client Toolkit",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. 'run' subcommand
    run_parser = subparsers.add_parser("run", aliases=["serve"], help="Run MWL SCP Server")
    run_parser.add_argument("-p", "--port", type=int, default=default_cfg.port, help=f"Port to listen on (default: {default_cfg.port})")
    run_parser.add_argument("-a", "--aet", type=str, default=default_cfg.ae_title, help=f"SCP AE Title (default: {default_cfg.ae_title})")
    run_parser.add_argument("-H", "--host", type=str, default=default_cfg.host, help=f"Host address (default: {default_cfg.host})")
    run_parser.add_argument("-w", "--worklists-dir", type=str, default=str(default_cfg.worklists_dir), help="Path to worklists directory")
    run_parser.add_argument("-l", "--log-level", type=str, default=default_cfg.log_level, choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log verbosity level")
    run_parser.add_argument("--no-reload", action="store_true", help="Disable hot reloading of worklist directory")
    run_parser.set_defaults(func=cmd_run)

    # 2. 'echo' subcommand
    echo_parser = subparsers.add_parser("echo", aliases=["ping"], help="Ping SCP server with C-ECHO")
    echo_parser.add_argument("-H", "--host", type=str, default="localhost", help="SCP Host (default: localhost)")
    echo_parser.add_argument("-p", "--port", type=int, default=default_cfg.port, help=f"SCP Port (default: {default_cfg.port})")
    echo_parser.add_argument("-c", "--called-aet", type=str, default=default_cfg.ae_title, help="SCP Called AE Title")
    echo_parser.add_argument("-a", "--calling-aet", type=str, default="MWL_SCU", help="SCU Calling AE Title")
    echo_parser.set_defaults(func=cmd_echo)

    # 3. 'query' subcommand
    query_parser = subparsers.add_parser("query", aliases=["find"], help="Query MWL SCP server with C-FIND")
    query_parser.add_argument("-H", "--host", type=str, default="localhost", help="SCP Host (default: localhost)")
    query_parser.add_argument("-p", "--port", type=int, default=default_cfg.port, help=f"SCP Port (default: {default_cfg.port})")
    query_parser.add_argument("-c", "--called-aet", type=str, default=default_cfg.ae_title, help="SCP Called AE Title")
    query_parser.add_argument("-a", "--calling-aet", type=str, default="MWL_SCU", help="SCU Calling AE Title")
    query_parser.add_argument("--patient-id", type=str, help="Filter by Patient ID")
    query_parser.add_argument("--patient-name", type=str, help="Filter by Patient Name (supports wildcards * and ?)")
    query_parser.add_argument("-m", "--modality", type=str, help="Filter by Modality (CT, MR, US, DX, etc.)")
    query_parser.add_argument("-d", "--date", type=str, help="Filter by Scheduled Date (YYYYMMDD or range YYYYMMDD-YYYYMMDD)")
    query_parser.add_argument("--accession", type=str, help="Filter by Accession Number")
    query_parser.add_argument("--station-ae", type=str, help="Filter by Station AE Title")
    query_parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose DICOM logging")
    query_parser.set_defaults(func=cmd_query)

    # 4. 'list' subcommand
    list_parser = subparsers.add_parser("list", aliases=["ls"], help="List all local worklist files")
    list_parser.add_argument("-w", "--worklists-dir", type=str, default=str(default_cfg.worklists_dir), help="Path to worklists directory")
    list_parser.set_defaults(func=cmd_list)

    # 5. 'sample' subcommand
    sample_parser = subparsers.add_parser("sample", aliases=["create-samples"], help="Create sample worklist files")
    sample_parser.add_argument("-o", "--output-dir", type=str, default=str(default_cfg.worklists_dir), help="Output directory")
    sample_parser.set_defaults(func=cmd_sample)

    # 6. 'create' subcommand
    create_parser = subparsers.add_parser("create", help="Create custom worklist file")
    create_parser.add_argument("--patient-id", required=True, help="Patient ID")
    create_parser.add_argument("--patient-name", required=True, help="Patient Name (e.g. Doe^Jane)")
    create_parser.add_argument("--patient-sex", default="O", choices=["M", "F", "O"], help="Patient Sex")
    create_parser.add_argument("--patient-dob", default="19900101", help="Birth Date (YYYYMMDD)")
    create_parser.add_argument("--accession", default="ACC001", help="Accession Number")
    create_parser.add_argument("--modality", default="CT", help="Modality (CT, MR, US, DX, etc.)")
    create_parser.add_argument("--procedure-desc", default="Diagnostic Examination", help="Procedure Description")
    create_parser.add_argument("--date", default=None, help="Scheduled Date (YYYYMMDD)")
    create_parser.add_argument("--time", default="090000", help="Scheduled Time (HHMMSS)")
    create_parser.add_argument("--station-ae", default="MODALITY_1", help="Scheduled Station AE Title")
    create_parser.add_argument("-o", "--output-dir", default=str(default_cfg.worklists_dir), help="Output directory")
    create_parser.add_argument("-f", "--filename", default=None, help="Custom filename")
    create_parser.set_defaults(func=cmd_create)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        # Default behavior when run with no arguments: show help or run server
        parser.print_help()


if __name__ == "__main__":
    main()
