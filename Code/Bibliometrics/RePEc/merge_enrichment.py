#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import glob
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CODE_ROOT = PROJECT_ROOT / "Code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from Bibliometrics.RePEc.schemas import REPEC_PANEL_FIELDS, validate_enrichment_record
from Bibliometrics.build_openalex_panel import load_csv, latest_path, resolve_path, write_csv, write_json


BIBLIO_PANEL_PATTERN = re.compile(r"^Bibliometric_Panel_(\d{6})\.csv$")
REPEC_VALIDATION_PATTERN = re.compile(r"^RePEc_Validation_(\d{6})\.csv$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge RePEc enrichment into the bibliometric panel")
    parser.add_argument("--date", default=None, help="Date suffix for default input/output paths (MMDDYY)")
    parser.add_argument("--panel", default=None, help="Input bibliometric panel CSV")
    parser.add_argument("--enrichment", nargs="+", required=True, help="One or more enrichment JSONL paths or globs")
    parser.add_argument("--validation", default=None, help="Validation CSV")
    parser.add_argument("--output-panel", default=None, help="Merged CSV output path")
    parser.add_argument("--output-json", default=None, help="Merged JSON output path")
    parser.add_argument("--website-output", default=None, help="Optional second JSON copy")
    parser.add_argument("--skip-failed", action="store_true", help="Leave failed enrichment rows blank in the CSV/JSON")
    parser.add_argument("--dry-run", action="store_true", help="Compute merge results without writing outputs")
    return parser.parse_args()


def infer_date_token(args: argparse.Namespace) -> str:
    if args.date:
        return args.date
    for candidate in (args.panel, args.validation):
        if not candidate:
            continue
        name = Path(candidate).name
        for pattern in (BIBLIO_PANEL_PATTERN, REPEC_VALIDATION_PATTERN):
            match = pattern.match(name)
            if match:
                return match.group(1)
    panel_path = latest_path(BIBLIO_PANEL_PATTERN)
    match = BIBLIO_PANEL_PATTERN.match(panel_path.name)
    if not match:
        raise ValueError("Unable to infer date token")
    return match.group(1)


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
    return sorted(paths)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Expected object JSON in {path}:{line_number}")
            rows.append(payload)
    return rows


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    return None


def int_to_cell(value: int | None) -> str:
    return "" if value is None else str(value)


def blank_repec_panel_fields() -> dict[str, str]:
    return {field: "" for field in REPEC_PANEL_FIELDS}


def best_repec_paper(enrichment: dict[str, Any]) -> dict[str, Any]:
    top_papers = enrichment.get("top_papers") or []
    best_paper: dict[str, Any] = {}
    best_score = -1
    for paper in top_papers:
        if not isinstance(paper, dict):
            continue
        citations = parse_int(paper.get("citations"))
        score = citations if citations is not None else -1
        if score > best_score:
            best_score = score
            best_paper = paper
    return best_paper


def extract_repec_panel_fields(enrichment: dict[str, Any]) -> dict[str, str]:
    repec = enrichment.get("repec") or {}
    best_paper = best_repec_paper(enrichment)
    jel_codes = repec.get("jel_codes") or []

    return {
        "repec_lookup_status": str(enrichment.get("lookup_status", "") or ""),
        "repec_confidence": str(enrichment.get("confidence", "") or ""),
        "repec_url": str(repec.get("url", "") or ""),
        "repec_handle": str(repec.get("handle", "") or ""),
        "repec_name_on_profile": str(repec.get("name_on_profile", "") or ""),
        "repec_affiliation": str(repec.get("affiliation_on_profile", "") or ""),
        "repec_homepage": str(repec.get("homepage", "") or ""),
        "repec_jel_codes": "; ".join(str(item).strip() for item in jel_codes if str(item).strip()),
        "repec_works_count": int_to_cell(parse_int(repec.get("works_count"))),
        "repec_citec_url": str(repec.get("citec_url", "") or ""),
        "repec_citec_h_index": int_to_cell(parse_int(repec.get("citec_h_index"))),
        "repec_citec_cited_by_count": int_to_cell(parse_int(repec.get("citec_cited_by_count"))),
        "repec_most_cited_title": str(best_paper.get("title", "") or ""),
        "repec_most_cited_year": int_to_cell(parse_int(best_paper.get("year"))),
        "repec_most_cited_citations": int_to_cell(parse_int(best_paper.get("citations"))),
        "repec_most_cited_venue": str(best_paper.get("venue", "") or ""),
        "repec_enrichment_status": "",
    }


def insert_panel_fields(fieldnames: list[str]) -> list[str]:
    cleaned = [field for field in fieldnames if not field.startswith("repec_")]
    if "gs_enrichment_status" in cleaned:
        index = cleaned.index("gs_enrichment_status") + 1
        return cleaned[:index] + REPEC_PANEL_FIELDS + cleaned[index:]
    if "suspicious_flags" in cleaned:
        index = cleaned.index("suspicious_flags") + 1
        return cleaned[:index] + REPEC_PANEL_FIELDS + cleaned[index:]
    return cleaned + REPEC_PANEL_FIELDS


def validation_lookup_by_node(path: Path) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for row in load_csv(path):
        node_id = (row.get("node_id") or "").strip()
        if not node_id:
            continue
        if node_id in lookup:
            raise ValueError(f"Validation CSV contains duplicate node_id {node_id}")
        lookup[node_id] = row
    return lookup


def enrichment_lookup_by_node(paths: list[Path]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for path in paths:
        for record in load_jsonl(path):
            node_id = (record.get("node_id") or "").strip()
            if not node_id:
                raise ValueError(f"Enrichment record in {path} is missing node_id")
            if node_id in lookup:
                raise ValueError(f"Duplicate node_id in enrichment inputs: {node_id}")
            working = copy.deepcopy(record)
            validate_enrichment_record(working)
            lookup[node_id] = working
    return lookup


def build_openalex_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("openalex_id", ""),
        "display_name": row.get("openalex_display_name", ""),
        "works_count": parse_int(row.get("works_count")),
        "cited_by_count": parse_int(row.get("cited_by_count")),
        "h_index": parse_int(row.get("h_index")),
        "i10_index": parse_int(row.get("i10_index")),
        "current_institution": row.get("current_institution_openalex", ""),
        "primary_field": row.get("primary_field", ""),
        "primary_subfield": row.get("primary_subfield", ""),
        "primary_topic": row.get("primary_topic", ""),
        "primary_domain": row.get("primary_domain", ""),
        "counts_by_year": json.loads(row["counts_by_year_json"]) if row.get("counts_by_year_json") else [],
        "institutions": json.loads(row["institutions_openalex_json"]) if row.get("institutions_openalex_json") else [],
        "topics": json.loads(row["topics_json"]) if row.get("topics_json") else [],
    }


def build_most_cited_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "openalex_work_id": row.get("most_cited_paper_id", ""),
        "title": row.get("most_cited_paper_title", ""),
        "doi": row.get("most_cited_paper_doi", ""),
        "publication_year": parse_int(row.get("most_cited_paper_year")),
        "cited_by_count": parse_int(row.get("most_cited_paper_cited_by_count")),
        "venue": row.get("most_cited_paper_venue", ""),
        "primary_topic": row.get("most_cited_paper_topic", ""),
    }


def build_fallback_scholar_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": row.get("node_id", ""),
        "name": row.get("full_name", ""),
        "first_name": row.get("first_name", ""),
        "last_name": row.get("last_name", ""),
        "generation": row.get("generation", ""),
        "advisor": row.get("advisor", ""),
        "phd_institution": row.get("phd_institution", ""),
        "phd_year": row.get("phd_year", ""),
        "current_employer": row.get("current_employer", ""),
        "match_status": row.get("match_status", ""),
        "match_confidence": float(row.get("match_confidence") or 0),
        "needs_manual_review": (row.get("needs_manual_review") or "") == "1",
        "manual_decision": row.get("manual_decision", ""),
        "decision_source": row.get("decision_source", "automatic"),
        "public_ready": (row.get("public_ready") or "") == "1",
        "suspicious_flags": [item for item in str(row.get("suspicious_flags", "") or "").split("; ") if item],
        "openalex": build_openalex_payload_from_row(row),
        "most_cited_paper": build_most_cited_payload_from_row(row),
        "top_papers": [],
    }


def repec_payload(enrichment: dict[str, Any] | None, repec_status: str) -> dict[str, Any]:
    if enrichment is None:
        return {
            "lookup_status": "",
            "confidence": "",
            "enrichment_status": repec_status,
            "url": None,
            "handle": None,
            "name_on_profile": None,
            "affiliation_on_profile": None,
            "homepage": None,
            "jel_codes": None,
            "works_count": None,
            "coauthors": None,
            "citec_url": None,
            "citec_h_index": None,
            "citec_cited_by_count": None,
            "top_papers": [],
        }

    repec = enrichment.get("repec") or {}
    top_papers_payload = []
    for paper in enrichment.get("top_papers") or []:
        if not isinstance(paper, dict):
            continue
        top_papers_payload.append(
            {
                "title": paper.get("title"),
                "year": parse_int(paper.get("year")),
                "citations": parse_int(paper.get("citations")),
                "venue": paper.get("venue"),
            }
        )

    return {
        "lookup_status": str(enrichment.get("lookup_status", "") or ""),
        "confidence": str(enrichment.get("confidence", "") or ""),
        "enrichment_status": repec_status,
        "url": repec.get("url"),
        "handle": repec.get("handle"),
        "name_on_profile": repec.get("name_on_profile"),
        "affiliation_on_profile": repec.get("affiliation_on_profile"),
        "homepage": repec.get("homepage"),
        "jel_codes": [str(item).strip() for item in repec.get("jel_codes") or [] if str(item).strip()] or None,
        "works_count": parse_int(repec.get("works_count")),
        "coauthors": [str(item).strip() for item in repec.get("coauthors") or [] if str(item).strip()] or None,
        "citec_url": repec.get("citec_url"),
        "citec_h_index": parse_int(repec.get("citec_h_index")),
        "citec_cited_by_count": parse_int(repec.get("citec_cited_by_count")),
        "top_papers": top_papers_payload[:5],
    }


def merge_row(
    row: dict[str, str],
    validation_row: dict[str, str] | None,
    enrichment_row: dict[str, Any] | None,
    *,
    skip_failed: bool,
) -> dict[str, str]:
    merged = {key: value for key, value in row.items() if not key.startswith("repec_")}
    repec_fields = blank_repec_panel_fields()
    repec_status = (validation_row or {}).get("overall_status", "missing") or "missing"

    should_merge = repec_status in {"pass", "warn"} or (repec_status == "fail" and not skip_failed)
    if should_merge and enrichment_row is not None:
        repec_fields.update(extract_repec_panel_fields(enrichment_row))

    repec_fields["repec_enrichment_status"] = repec_status
    merged.update(repec_fields)
    return merged


def merge_json_scholar(
    base_scholar: dict[str, Any],
    merged_row: dict[str, str],
    enrichment_row: dict[str, Any] | None,
    *,
    skip_failed: bool,
) -> dict[str, Any]:
    scholar = copy.deepcopy(base_scholar)
    repec_status = merged_row.get("repec_enrichment_status", "")
    should_merge = repec_status in {"pass", "warn"} or (repec_status == "fail" and not skip_failed)
    scholar["repec"] = repec_payload(enrichment_row if should_merge else None, repec_status)
    return scholar


def load_panel_json_payload(panel_csv_path: Path) -> dict[str, Any] | None:
    panel_json_path = panel_csv_path.with_suffix(".json")
    if not panel_json_path.exists():
        return None
    payload = json.loads(panel_json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("scholars"), list):
        return None
    return payload


def merged_source_name(base_json_payload: dict[str, Any] | None) -> str:
    source = str((base_json_payload or {}).get("source") or "").strip()
    if not source:
        return "RePEc"
    parts = [part.strip() for part in source.split(" + ") if part.strip()]
    if "RePEc" not in parts:
        parts.append("RePEc")
    return " + ".join(parts)


def main() -> None:
    args = parse_args()
    date_token = infer_date_token(args)

    panel_default = PROJECT_ROOT / "Data" / "Derived" / f"Bibliometric_Panel_{date_token}.csv"
    validation_default = PROJECT_ROOT / "Data" / "Derived" / f"RePEc_Validation_{date_token}.csv"
    output_panel_default = PROJECT_ROOT / "Data" / "Derived" / f"Bibliometric_Panel_RePEc_{date_token}.csv"
    output_json_default = PROJECT_ROOT / "Data" / "Derived" / f"Bibliometric_Panel_RePEc_{date_token}.json"

    panel_path = resolve_path(args.panel, panel_default)
    validation_path = resolve_path(args.validation, validation_default)
    output_panel_path = resolve_path(args.output_panel, output_panel_default)
    output_json_path = resolve_path(args.output_json, output_json_default)
    website_output_path = resolve_path(args.website_output) if args.website_output else None
    enrichment_paths = expand_paths(args.enrichment)
    if not enrichment_paths:
        raise ValueError("No enrichment files matched the provided --enrichment inputs")

    panel_rows = load_csv(panel_path)
    if not panel_rows:
        raise ValueError(f"Input panel is empty: {panel_path}")
    original_fieldnames = list(panel_rows[0].keys())
    output_fieldnames = insert_panel_fields(original_fieldnames)

    validation_lookup = validation_lookup_by_node(validation_path)
    enrichment_lookup = enrichment_lookup_by_node(enrichment_paths)

    merged_rows: list[dict[str, str]] = []
    for row in panel_rows:
        node_id = (row.get("node_id") or "").strip()
        validation_row = validation_lookup.get(node_id)
        enrichment_row = enrichment_lookup.get(node_id)
        merged_rows.append(
            merge_row(
                row,
                validation_row,
                enrichment_row,
                skip_failed=args.skip_failed,
            )
        )

    base_json_payload = load_panel_json_payload(panel_path)
    base_json_lookup: dict[str, dict[str, Any]] = {}
    if base_json_payload:
        for scholar in base_json_payload.get("scholars", []):
            if isinstance(scholar, dict) and scholar.get("node_id"):
                base_json_lookup[str(scholar["node_id"])] = scholar

    merged_scholars: list[dict[str, Any]] = []
    for row in merged_rows:
        node_id = row.get("node_id", "")
        base_scholar = base_json_lookup.get(node_id) or build_fallback_scholar_json(row)
        merged_scholars.append(
            merge_json_scholar(
                base_scholar,
                row,
                enrichment_lookup.get(node_id),
                skip_failed=args.skip_failed,
            )
        )

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    built_at = str((base_json_payload or {}).get("built_at") or now_iso)

    merged_payload = {
        "snapshot_date": date_token,
        "source": merged_source_name(base_json_payload),
        "built_at": built_at,
        "scholars": merged_scholars,
    }

    if not args.dry_run:
        write_csv(output_panel_path, output_fieldnames, merged_rows)
        write_json(output_json_path, merged_payload)
        if website_output_path:
            write_json(website_output_path, merged_payload)

    status_counts: dict[str, int] = {}
    for row in merged_rows:
        status = row.get("repec_enrichment_status", "")
        status_counts[status] = status_counts.get(status, 0) + 1

    print(f"Panel CSV:    {panel_path}")
    print(f"Validation:   {validation_path}")
    print(f"Enrichment:   {len(enrichment_paths)} file(s)")
    print(f"Rows:         {len(merged_rows)}")
    print(f"Columns:      {len(output_fieldnames)}")
    if args.dry_run:
        print("Dry run:      yes")
    else:
        print(f"Output CSV:   {output_panel_path}")
        print(f"Output JSON:  {output_json_path}")
        if website_output_path:
            print(f"Website JSON: {website_output_path}")
    for status in ("pass", "warn", "fail", "missing"):
        if status in status_counts:
            print(f"{status:>11}: {status_counts[status]}")


if __name__ == "__main__":
    main()
