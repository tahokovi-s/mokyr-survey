#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CODE_ROOT = PROJECT_ROOT / "Code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from Bibliometrics.RePEc.schemas import validate_manifest_record
from Bibliometrics.build_openalex_panel import (
    MASTER_PATTERN,
    NODES_PATTERN,
    build_full_name,
    build_name_queries,
    latest_path,
    load_csv,
    resolve_path,
    strip_diacritics,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate RePEc enrichment manifests for Mokyr scholars")
    parser.add_argument("--date", default=None, help="Date suffix for default input/output paths (MMDDYY)")
    parser.add_argument("--master", default=None, help="Path to Master_Contact_List CSV")
    parser.add_argument("--nodes", default=None, help="Path to Network_Nodes CSV")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of scholars emitted")
    parser.add_argument("--node-ids", default=None, help="Comma-separated node_ids to include")
    parser.add_argument("--generations", default=None, help="Comma-separated generation values to include")
    parser.add_argument("--batch-size", type=int, default=20, help="Optional batch file size; use 0 to disable")
    parser.add_argument("--output", default=None, help="Output JSONL path")
    return parser.parse_args()


def infer_date_token(args: argparse.Namespace) -> str:
    if args.date:
        return args.date

    if args.master:
        master_name = Path(args.master).name
        match = MASTER_PATTERN.match(master_name)
        if match:
            return match.group(1)

    latest_master = latest_path(MASTER_PATTERN)
    match = MASTER_PATTERN.match(latest_master.name)
    if not match:
        raise ValueError("Unable to infer date token from Master_Contact_List filename")
    return match.group(1)


def parse_csv_filter(raw_value: str | None) -> set[str]:
    if not raw_value:
        return set()
    return {item.strip() for item in raw_value.split(",") if item.strip()}


def dedupe_queries(queries: list[str]) -> list[str]:
    seen = set()
    deduped: list[str] = []
    for query in queries:
        cleaned = re.sub(r"\s+", " ", query).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            deduped.append(cleaned)
    return deduped


def build_search_queries(scholar: dict[str, Any]) -> list[str]:
    full_name = build_full_name(scholar)
    name_variants = build_name_queries(scholar)
    institution = (scholar.get("current_employer") or scholar.get("phd_institution") or "").strip()

    queries: list[str] = []
    queries.extend(name_variants)

    if full_name:
        queries.append(full_name)
        if institution:
            queries.append(f"{full_name} {institution}")

    folded_full_name = strip_diacritics(full_name)
    if folded_full_name and folded_full_name != full_name:
        queries.append(folded_full_name)
        if institution:
            queries.append(f"{folded_full_name} {institution}")

    return dedupe_queries(queries)


def build_manifest_record(master_row: dict[str, str], node_row: dict[str, str]) -> dict[str, Any]:
    first_name = (master_row.get("first_name") or node_row.get("first_name") or "").strip()
    last_name = (master_row.get("last_name") or node_row.get("last_name") or "").strip()
    phd_institution = (
        master_row.get("phd_institution")
        or node_row.get("phd_institution_canon")
        or node_row.get("phd_institution_raw")
        or ""
    ).strip()
    current_employer = (
        master_row.get("current_employer")
        or node_row.get("current_employer_canon")
        or node_row.get("current_employer_raw")
        or ""
    ).strip()
    repec_handle_override = (
        master_row.get("repec_handle_override")
        or node_row.get("repec_handle_override")
        or ""
    ).strip()

    merged = {
        "node_id": (master_row.get("node_id") or node_row.get("node_id") or "").strip(),
        "first_name": first_name,
        "last_name": last_name,
        "full_name": build_full_name({"first_name": first_name, "last_name": last_name}),
        "generation": (master_row.get("generation") or node_row.get("generation") or "").strip(),
        "advisor": (master_row.get("advisor") or "").strip(),
        "phd_institution": phd_institution,
        "phd_year": (node_row.get("phd_year") or "").strip(),
        "current_employer": current_employer,
        "repec_handle_override": repec_handle_override,
    }
    merged["search_queries"] = build_search_queries(merged)
    return merged


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def batch_path_for(output_path: Path, date_token: str, batch_index: int, total_batches: int) -> Path:
    width = max(2, len(str(total_batches)))
    suffix = output_path.suffix or ".jsonl"
    stem = output_path.stem
    date_suffix = f"_{date_token}"
    if stem.endswith(date_suffix):
        stem = stem[: -len(date_suffix)]
    batch_name = f"{stem}_Batch_{batch_index:0{width}d}_{date_token}{suffix}"
    return output_path.with_name(batch_name)


def main() -> None:
    args = parse_args()
    date_token = infer_date_token(args)

    master_default = PROJECT_ROOT / "Data" / "Derived" / f"Master_Contact_List_{date_token}.csv"
    nodes_default = PROJECT_ROOT / "Data" / "Derived" / f"Network_Nodes_{date_token}.csv"
    output_default = PROJECT_ROOT / "Data" / "Derived" / f"RePEc_Manifest_{date_token}.jsonl"

    master_path = resolve_path(
        args.master,
        master_default if master_default.exists() else None,
        MASTER_PATTERN if args.master is None else None,
    )
    nodes_path = resolve_path(
        args.nodes,
        nodes_default if nodes_default.exists() else None,
        NODES_PATTERN if args.nodes is None else None,
    )
    output_path = resolve_path(args.output, output_default)

    master_rows = load_csv(master_path)
    node_rows = load_csv(nodes_path)
    node_lookup = {(row.get("node_id") or "").strip(): row for row in node_rows if (row.get("node_id") or "").strip()}

    node_id_filter = parse_csv_filter(args.node_ids)
    generation_filter = parse_csv_filter(args.generations)

    manifest_rows: list[dict[str, Any]] = []
    for master_row in master_rows:
        node_id = (master_row.get("node_id") or "").strip()
        if not node_id:
            raise ValueError("Master contact list contains a row with no node_id")
        if node_id_filter and node_id not in node_id_filter:
            continue

        node_row = node_lookup.get(node_id)
        if node_row is None:
            raise ValueError(f"node_id {node_id} appears in the master list but not in Network_Nodes")

        record = build_manifest_record(master_row, node_row)
        if generation_filter and record.get("generation", "") not in generation_filter:
            continue

        errors = validate_manifest_record(record)
        if errors:
            raise ValueError(f"Invalid manifest record for {node_id}: {'; '.join(errors)}")
        manifest_rows.append(record)

        if args.limit is not None and len(manifest_rows) >= args.limit:
            break

    write_jsonl(output_path, manifest_rows)

    batch_paths: list[Path] = []
    if args.batch_size and args.batch_size > 0:
        total_batches = max(1, (len(manifest_rows) + args.batch_size - 1) // args.batch_size)
        for batch_index, start in enumerate(range(0, len(manifest_rows), args.batch_size), start=1):
            batch_rows = manifest_rows[start : start + args.batch_size]
            path = batch_path_for(output_path, date_token, batch_index, total_batches)
            write_jsonl(path, batch_rows)
            batch_paths.append(path)

    print(f"Date token:  {date_token}")
    print(f"Master CSV:  {master_path}")
    print(f"Nodes CSV:   {nodes_path}")
    print(f"Scholars:    {len(manifest_rows)}")
    print(f"Manifest:    {output_path}")
    if batch_paths:
        print(f"Batches:     {len(batch_paths)}")
        for path in batch_paths:
            print(f"  - {path}")


if __name__ == "__main__":
    main()
