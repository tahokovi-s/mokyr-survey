#!/usr/bin/env python3
"""Merge reviewed OpenAlex decisions into the canonical union file."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CODE_ROOT = PROJECT_ROOT / "Code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from Bibliometrics.openalex_review_pipeline import (  # noqa: E402
    DECISION_FIELDNAMES,
    extract_date_token,
    load_csv,
    load_manual_decisions,
    read_decisions_csv,
    resolve_existing_all_decisions,
    write_decisions_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge reviewed OpenAlex decisions into OpenAlex_All_Decisions")
    parser.add_argument(
        "--audited",
        required=True,
        help="Path to audited decisions CSV or raw reviewer decisions CSV",
    )
    parser.add_argument("--date", default=None, help="Date suffix for the base decisions file (MMDDYY)")
    parser.add_argument(
        "--existing-decisions",
        default=None,
        help="Optional existing OpenAlex_All_Decisions CSV path",
    )
    parser.add_argument("--output", default=None, help="Optional merged output CSV path")
    parser.add_argument(
        "--skip-flagged",
        dest="skip_flagged",
        action="store_true",
        default=True,
        help="Skip rows with audit_verdict=flag (default)",
    )
    parser.add_argument(
        "--include-flagged",
        dest="skip_flagged",
        action="store_false",
        help="Apply rows even when audit_verdict=flag",
    )
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the bibliometric panel after merge")
    parser.add_argument("--api-key", default=os.environ.get("OPENALEX_API_KEY", ""), help="OpenAlex API key for rebuild")
    parser.add_argument("--mailto", default=os.environ.get("OPENALEX_MAILTO", ""), help="OpenAlex mailto for rebuild")
    parser.add_argument("--website-output", default=None, help="Optional website JSON output passed through on rebuild")
    parser.add_argument("--refresh-cache", action="store_true", help="Pass --refresh-cache to rebuild")
    parser.add_argument("--max-works-pages", type=int, default=1, help="Pass-through max works pages for rebuild")
    return parser


def canonical_row(row: dict[str, str]) -> dict[str, str]:
    return {field: (row.get(field, "") or "").strip() for field in DECISION_FIELDNAMES}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    audited_path = Path(args.audited)
    if not audited_path.is_absolute():
        audited_path = PROJECT_ROOT / audited_path
    input_rows = read_decisions_csv(audited_path)

    date_token = args.date or extract_date_token(audited_path.name)
    existing_path = resolve_existing_all_decisions(
        date_token=date_token,
        decisions_path=args.existing_decisions,
    )
    existing_rows = load_csv(existing_path)

    updates_by_node: dict[str, dict[str, str]] = {}
    flagged_skipped = 0
    for row in input_rows:
        if args.skip_flagged and (row.get("audit_verdict", "") or "").strip().lower() == "flag":
            flagged_skipped += 1
            continue
        updates_by_node[(row.get("node_id", "") or "").strip()] = canonical_row(row)

    merged_rows: list[dict[str, str]] = []
    seen_nodes: set[str] = set()
    preserved_count = 0
    applied_count = 0
    for existing_row in existing_rows:
        node_id = (existing_row.get("node_id", "") or "").strip()
        if node_id in updates_by_node:
            merged_rows.append(updates_by_node[node_id])
            applied_count += 1
            seen_nodes.add(node_id)
        else:
            merged_rows.append(canonical_row(existing_row))
            preserved_count += 1
            seen_nodes.add(node_id)

    for node_id, row in updates_by_node.items():
        if node_id in seen_nodes:
            continue
        merged_rows.append(row)
        applied_count += 1

    output_path = (
        Path(args.output)
        if args.output
        else PROJECT_ROOT / "Data" / "Derived" / f"OpenAlex_All_Decisions_{extract_date_token(existing_path.name) or date_token}_reviewed.csv"
    )
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    temp_output = output_path.with_name(output_path.name + ".tmp")
    write_decisions_csv(temp_output, merged_rows)
    load_manual_decisions(temp_output)
    temp_output.replace(output_path)

    deferred_total = sum(1 for row in merged_rows if (row.get("decision", "") or "").strip() == "needs_more_review")

    print(f"Existing base file:    {existing_path}")
    print(f"Input decisions:       {len(input_rows)} from {audited_path}")
    print(f"Applied updates:       {applied_count}")
    print(f"Flagged skipped:       {flagged_skipped}")
    print(f"Existing preserved:    {preserved_count}")
    print(f"Deferred in merged:    {deferred_total}")
    print(f"Merged decisions CSV:  {output_path}")

    if not args.rebuild:
        return

    api_key = (args.api_key or "").strip()
    if not api_key:
        raise SystemExit("Rebuild requested, but no OpenAlex API key was supplied via --api-key or OPENALEX_API_KEY.")

    rebuild_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "Code" / "Bibliometrics" / "build_openalex_panel.py"),
        "--date",
        extract_date_token(existing_path.name) or date_token or "",
        "--manual-decisions",
        str(output_path),
        "--api-key",
        api_key,
        "--max-works-pages",
        str(args.max_works_pages),
    ]
    if args.mailto:
        rebuild_cmd.extend(["--mailto", args.mailto])
    if args.website_output:
        rebuild_cmd.extend(["--website-output", args.website_output])
    if args.refresh_cache:
        rebuild_cmd.append("--refresh-cache")

    subprocess.run(rebuild_cmd, check=True, cwd=PROJECT_ROOT)
    print("Rebuild completed successfully.")


if __name__ == "__main__":
    main()
