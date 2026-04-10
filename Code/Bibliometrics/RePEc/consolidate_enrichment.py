#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CODE_ROOT = PROJECT_ROOT / "Code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from Bibliometrics.RePEc.schemas import validate_enrichment_record, validate_manifest_record
from Bibliometrics.build_openalex_panel import write_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consolidate RePEc enrichment JSONL batches into one canonical file")
    parser.add_argument("--manifest", default=None, help="Optional manifest JSONL for summary fields and completeness checks")
    parser.add_argument("--enrichment", nargs="+", required=True, help="One or more enrichment JSONL paths or globs")
    parser.add_argument("--output", required=True, help="Output consolidated enrichment JSONL")
    parser.add_argument("--summary-output", default=None, help="Optional CSV summary path")
    return parser.parse_args()


def resolve(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    path = Path(path_str)
    return path if path.is_absolute() else PROJECT_ROOT / path


def expand_paths(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen = set()
    for value in values:
        matches = glob.glob(value)
        if not matches:
            matches = [value]
        for match in matches:
            path = Path(match)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)
    return paths


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected object JSON in {path}:{line_number}")
            rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def status_rank(record: dict[str, Any]) -> int:
    return {
        "found": 3,
        "ambiguous": 2,
        "not_found": 1,
    }.get(str(record.get("lookup_status") or ""), 0)


def review_rank(record: dict[str, Any]) -> int:
    return {
        "override_applied": 2,
        "candidate_review": 1,
        "none": 0,
    }.get(str(record.get("review_status") or "none"), 0)


def confidence_rank(record: dict[str, Any]) -> int:
    return {
        "high": 3,
        "medium": 2,
        "low": 1,
    }.get(str(record.get("confidence") or ""), 0)


def selection_key(record: dict[str, Any], source_index: int, row_index: int) -> tuple[int, int, int, int, int]:
    return (
        status_rank(record),
        review_rank(record),
        confidence_rank(record),
        source_index,
        row_index,
    )


def summarize_source(record: dict[str, Any], source_path: Path) -> dict[str, Any]:
    repec = record.get("repec") or {}
    return {
        "source_file": str(source_path),
        "repec_url": str(repec.get("url") or ""),
    }


def main() -> None:
    args = parse_args()
    manifest_path = resolve(args.manifest)
    output_path = resolve(args.output)
    summary_output_path = resolve(args.summary_output)
    enrichment_paths = expand_paths(args.enrichment)
    if not enrichment_paths:
        raise ValueError("No enrichment inputs matched")

    manifest_lookup: dict[str, dict[str, Any]] = {}
    if manifest_path is not None:
        for row in load_jsonl(manifest_path):
            errors = validate_manifest_record(row)
            if errors:
                raise ValueError(f"Invalid manifest record for {row.get('node_id')}: {'; '.join(errors)}")
            node_id = str(row.get("node_id") or "").strip()
            if node_id:
                manifest_lookup[node_id] = row

    chosen: dict[str, dict[str, Any]] = {}
    chosen_meta: dict[str, dict[str, Any]] = {}
    duplicate_counts: Counter[str] = Counter()
    invalid_rows = 0

    for source_index, enrichment_path in enumerate(enrichment_paths):
        for row_index, record in enumerate(load_jsonl(enrichment_path), start=1):
            errors = validate_enrichment_record(record)
            if errors:
                invalid_rows += 1
                print(
                    f"[warn] invalid enrichment row in {enrichment_path}:{row_index}: {'; '.join(errors)}",
                    file=sys.stderr,
                )
                continue

            node_id = str(record.get("node_id") or "").strip()
            if not node_id:
                continue
            duplicate_counts[node_id] += 1

            candidate_key = selection_key(record, source_index, row_index)
            current_meta = chosen_meta.get(node_id)
            if current_meta is None or candidate_key > current_meta["selection_key"]:
                chosen[node_id] = record
                chosen_meta[node_id] = {
                    "selection_key": candidate_key,
                    **summarize_source(record, enrichment_path),
                }

    ordered_node_ids = sorted(chosen)
    consolidated_rows = [chosen[node_id] for node_id in ordered_node_ids]
    write_jsonl(output_path, consolidated_rows)

    if summary_output_path is not None:
        summary_rows: list[dict[str, Any]] = []
        for node_id in ordered_node_ids:
            record = chosen[node_id]
            manifest_row = manifest_lookup.get(node_id, {})
            meta = chosen_meta[node_id]
            summary_rows.append(
                {
                    "node_id": node_id,
                    "full_name": str(manifest_row.get("full_name") or ""),
                    "generation": str(manifest_row.get("generation") or ""),
                    "lookup_status": str(record.get("lookup_status") or ""),
                    "confidence": str(record.get("confidence") or ""),
                    "review_status": str(record.get("review_status") or "none"),
                    "source_file": meta["source_file"],
                    "repec_url": meta["repec_url"],
                    "duplicate_records_seen": duplicate_counts[node_id],
                }
            )

        fieldnames = [
            "node_id",
            "full_name",
            "generation",
            "lookup_status",
            "confidence",
            "review_status",
            "source_file",
            "repec_url",
            "duplicate_records_seen",
        ]
        write_csv(summary_output_path, fieldnames, summary_rows)

    status_counts = Counter(str(row.get("lookup_status") or "") for row in consolidated_rows)
    review_counts = Counter(str(row.get("review_status") or "none") for row in consolidated_rows)

    print(f"Inputs:      {len(enrichment_paths)}")
    print(f"Rows kept:   {len(consolidated_rows)}")
    print(f"Invalid:     {invalid_rows}")
    print(f"Output:      {output_path}")
    if summary_output_path is not None:
        print(f"Summary:     {summary_output_path}")
    for status in ("found", "ambiguous", "not_found"):
        if status in status_counts:
            print(f"{status:>11}: {status_counts[status]}")
    for review_status in ("override_applied", "candidate_review", "none"):
        if review_status in review_counts:
            print(f"{review_status:>11}: {review_counts[review_status]}")

    if manifest_lookup:
        missing = sorted(set(manifest_lookup) - set(ordered_node_ids))
        print(f"Manifest:    {len(manifest_lookup)} rows")
        print(f"Missing:     {len(missing)}")
        if missing:
            preview = ",".join(missing[:10])
            suffix = "..." if len(missing) > 10 else ""
            print(f"Missing IDs: {preview}{suffix}")


if __name__ == "__main__":
    main()
