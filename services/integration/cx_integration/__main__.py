"""Command line entry point.

    python -m cx_integration --base-url http://localhost:8000 --open-only --out tickets.json

Prints the run report as JSON on stdout; optionally writes the canonical
tickets to a file.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from .client import ServiceRequestClient
from .errors import IntegrationError
from .pipeline import extract_tickets

OPEN_ONLY_FILTER = "StatusTypeCd='ORA_SVC_OPEN'"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cx_integration", description="Extract canonical tickets.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--q", help="Source filter expression, e.g. SeverityCd='ORA_SVC_SEV1'")
    parser.add_argument("--open-only", action="store_true", help="Only open tickets (backlog)")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--out", type=Path, help="Write canonical tickets to this JSON file")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    q = ";".join(part for part in (OPEN_ONLY_FILTER if args.open_only else None, args.q) if part) or None

    try:
        with ServiceRequestClient(args.base_url, page_size=args.page_size) as client:
            report = extract_tickets(client, q=q)
    except IntegrationError as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1

    if args.out:
        args.out.write_text(json.dumps([t.model_dump(mode="json") for t in report.tickets], indent=2))
    print(json.dumps(report.summary(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
