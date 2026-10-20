from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="GroundworkNYC offline data and model pipeline")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    normalize = sub.add_parser("normalize")
    normalize.add_argument("--input", required=True)
    normalize.add_argument("--output", required=True)
    normalize.add_argument("--mapping", required=True)
    normalize.add_argument("--geography")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("path")
    huff = sub.add_parser("build-huff")
    huff.add_argument("--snapshot", required=True)
    huff.add_argument("--boundary", required=True)
    huff.add_argument("--vintages", required=True, help="JSON file selecting source vintages")
    huff.add_argument("--weights", help="JSON file with residents/workers/transit_inflow weights")
    huff.add_argument("--radius", type=int, default=3)
    screening = sub.add_parser("export-screening")
    screening.add_argument("--snapshot", required=True)
    screening.add_argument("--query", required=True, help="JSON file containing dashboard query arguments")
    predict = sub.add_parser("precompute")
    predict.add_argument("--snapshot", required=True)
    predict.add_argument("--artifact", required=True)
    predict.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if args.command == "normalize":
        from .normalize import normalize_csv

        print(
            json.dumps(
                {
                    "command": "normalize",
                    "result": normalize_csv(args.input, args.output, args.mapping, args.geography),
                }
            )
        )
        return
    if not args.database_url:
        parser.error("Set DATABASE_URL or --database-url.")
    if hasattr(args, "snapshot"):
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.snapshot):
            parser.error("Snapshot must contain 1-80 letters, digits, underscores or hyphens.")
    from .pipeline import build_huff, export_screening, precompute
    from .pipeline import ingest as ingest_source
    from .store import migrate

    if args.command == "migrate":
        migrate(args.database_url)
        result = "Schema ready"
    elif args.command == "ingest":
        result = ingest_source(args.database_url, args.path)
    elif args.command == "build-huff":
        result = build_huff(
            args.database_url,
            args.snapshot,
            args.boundary,
            json.loads(Path(args.vintages).read_text()),
            json.loads(Path(args.weights).read_text()) if args.weights else None,
            args.radius,
        )
    elif args.command == "export-screening":
        result = export_screening(args.database_url, args.snapshot, json.loads(Path(args.query).read_text()))
    else:
        result = precompute(args.database_url, args.snapshot, args.artifact, args.manifest)
    print(json.dumps({"command": args.command, "result": result}))


if __name__ == "__main__":
    main()
