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

from Bibliometrics.GoogleScholar.schemas import BEST_PANEL_FIELDS, GS_PANEL_FIELDS, validate_enrichment_record
from Bibliometrics.build_openalex_panel import load_csv, latest_path, resolve_path, write_csv, write_json


BIBLIO_PANEL_PATTERN = re.compile(r"^Bibliometric_Panel_(\d{6})\.csv$")
GS_VALIDATION_PATTERN = re.compile(r"^GS_Validation_(\d{6})\.csv$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge Google Scholar enrichment into the bibliometric panel")
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
        for pattern in (BIBLIO_PANEL_PATTERN, GS_VALIDATION_PATTERN):
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


def blank_gs_panel_fields() -> dict[str, str]:
    return {field: "" for field in GS_PANEL_FIELDS}


def best_google_scholar_paper(enrichment: dict[str, Any]) -> dict[str, Any]:
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


def extract_gs_panel_fields(enrichment: dict[str, Any]) -> dict[str, str]:
    google_scholar = enrichment.get("google_scholar") or {}
    personal_website = enrichment.get("personal_website") or {}
    best_paper = best_google_scholar_paper(enrichment)
    interests = google_scholar.get("interests") or []

    return {
        "gs_lookup_status": str(enrichment.get("lookup_status", "") or ""),
        "gs_confidence": str(enrichment.get("confidence", "") or ""),
        "gs_url": str(google_scholar.get("url", "") or ""),
        "gs_name_on_profile": str(google_scholar.get("name_on_profile", "") or ""),
        "gs_affiliation": str(google_scholar.get("affiliation_on_profile", "") or ""),
        "gs_interests": "; ".join(str(item).strip() for item in interests if str(item).strip()),
        "gs_works_count": int_to_cell(parse_int(google_scholar.get("works_count"))),
        "gs_cited_by_count": int_to_cell(parse_int(google_scholar.get("cited_by_count"))),
        "gs_h_index": int_to_cell(parse_int(google_scholar.get("h_index"))),
        "gs_i10_index": int_to_cell(parse_int(google_scholar.get("i10_index"))),
        "gs_most_cited_title": str(best_paper.get("title", "") or ""),
        "gs_most_cited_year": int_to_cell(parse_int(best_paper.get("year"))),
        "gs_most_cited_citations": int_to_cell(parse_int(best_paper.get("citations"))),
        "gs_most_cited_venue": str(best_paper.get("venue", "") or ""),
        "gs_personal_website": str(personal_website.get("url", "") or ""),
        "gs_self_described_field": str(personal_website.get("self_described_field", "") or ""),
        "gs_enrichment_status": "",
    }


def compute_best_field(row: dict[str, Any]) -> str:
    interests = [item.strip() for item in str(row.get("gs_interests", "") or "").split(";") if item.strip()]
    if interests:
        return interests[0]
    self_described = str(row.get("gs_self_described_field", "") or "").strip()
    if self_described:
        return self_described
    return str(row.get("primary_field", "") or "").strip()


def compute_best_h_index(row: dict[str, Any]) -> str:
    gs_value = parse_int(row.get("gs_h_index"))
    if gs_value is not None:
        return str(gs_value)
    openalex_value = parse_int(row.get("h_index"))
    return "" if openalex_value is None else str(openalex_value)


def compute_best_citations(row: dict[str, Any]) -> str:
    gs_value = parse_int(row.get("gs_cited_by_count"))
    if gs_value is not None:
        return str(gs_value)
    openalex_value = parse_int(row.get("cited_by_count"))
    return "" if openalex_value is None else str(openalex_value)


def insert_panel_fields(fieldnames: list[str]) -> list[str]:
    cleaned = [field for field in fieldnames if not (field.startswith("gs_") or field.startswith("best_"))]
    insert_after = "suspicious_flags"
    extra_fields = GS_PANEL_FIELDS + BEST_PANEL_FIELDS
    if insert_after in cleaned:
        index = cleaned.index(insert_after) + 1
        return cleaned[:index] + extra_fields + cleaned[index:]
    return cleaned + extra_fields


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


def google_scholar_payload(enrichment: dict[str, Any] | None, gs_status: str) -> dict[str, Any]:
    if enrichment is None:
        return {
            "lookup_status": "",
            "confidence": "",
            "enrichment_status": gs_status,
            "url": "",
            "name_on_profile": "",
            "affiliation_on_profile": "",
            "interests": [],
            "works_count": None,
            "cited_by_count": None,
            "h_index": None,
            "i10_index": None,
            "coauthors": [],
            "personal_website": "",
            "self_described_field": "",
            "top_papers": [],
        }

    google_scholar = enrichment.get("google_scholar") or {}
    personal_website = enrichment.get("personal_website") or {}
    top_papers_payload = []
    for paper in enrichment.get("top_papers") or []:
        if not isinstance(paper, dict):
            continue
        top_papers_payload.append(
            {
                "title": str(paper.get("title", "") or ""),
                "year": parse_int(paper.get("year")),
                "citations": parse_int(paper.get("citations")),
                "venue": str(paper.get("venue", "") or ""),
            }
        )

    return {
        "lookup_status": str(enrichment.get("lookup_status", "") or ""),
        "confidence": str(enrichment.get("confidence", "") or ""),
        "enrichment_status": gs_status,
        "url": str(google_scholar.get("url", "") or ""),
        "name_on_profile": str(google_scholar.get("name_on_profile", "") or ""),
        "affiliation_on_profile": str(google_scholar.get("affiliation_on_profile", "") or ""),
        "interests": [str(item).strip() for item in google_scholar.get("interests") or [] if str(item).strip()],
        "works_count": parse_int(google_scholar.get("works_count")),
        "cited_by_count": parse_int(google_scholar.get("cited_by_count")),
        "h_index": parse_int(google_scholar.get("h_index")),
        "i10_index": parse_int(google_scholar.get("i10_index")),
        "coauthors": [str(item).strip() for item in google_scholar.get("coauthors") or [] if str(item).strip()],
        "personal_website": str(personal_website.get("url", "") or ""),
        "self_described_field": str(personal_website.get("self_described_field", "") or ""),
        "top_papers": top_papers_payload[:5],
    }


def merge_row(
    row: dict[str, str],
    validation_row: dict[str, str] | None,
    enrichment_row: dict[str, Any] | None,
    *,
    skip_failed: bool,
) -> dict[str, str]:
    merged = {key: value for key, value in row.items() if not (key.startswith("gs_") or key.startswith("best_"))}
    gs_fields = blank_gs_panel_fields()
    gs_status = (validation_row or {}).get("overall_status", "missing") or "missing"

    should_merge = gs_status in {"pass", "warn"} or (gs_status == "fail" and not skip_failed)
    if should_merge and enrichment_row is not None:
        gs_fields.update(extract_gs_panel_fields(enrichment_row))

    gs_fields["gs_enrichment_status"] = gs_status
    merged.update(gs_fields)
    merged["best_field"] = compute_best_field(merged)
    merged["best_h_index"] = compute_best_h_index(merged)
    merged["best_citations"] = compute_best_citations(merged)
    return merged


def merge_json_scholar(
    base_scholar: dict[str, Any],
    merged_row: dict[str, str],
    enrichment_row: dict[str, Any] | None,
    *,
    skip_failed: bool,
) -> dict[str, Any]:
    scholar = copy.deepcopy(base_scholar)
    gs_status = merged_row.get("gs_enrichment_status", "")
    should_merge = gs_status in {"pass", "warn"} or (gs_status == "fail" and not skip_failed)
    scholar["google_scholar"] = google_scholar_payload(enrichment_row if should_merge else None, gs_status)
    scholar["best_field"] = merged_row.get("best_field", "")
    scholar["best_h_index"] = parse_int(merged_row.get("best_h_index"))
    scholar["best_citations"] = parse_int(merged_row.get("best_citations"))
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


def main() -> None:
    args = parse_args()
    date_token = infer_date_token(args)

    panel_default = PROJECT_ROOT / "Data" / "Derived" / f"Bibliometric_Panel_{date_token}.csv"
    validation_default = PROJECT_ROOT / "Data" / "Derived" / f"GS_Validation_{date_token}.csv"
    output_panel_default = PROJECT_ROOT / "Data" / "Derived" / f"Bibliometric_Panel_GS_{date_token}.csv"
    output_json_default = PROJECT_ROOT / "Data" / "Derived" / f"Bibliometric_Panel_GS_{date_token}.json"

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
    built_at = now_iso
    if base_json_payload and base_json_payload.get("source") == "OpenAlex + Google Scholar":
        built_at = str(base_json_payload.get("built_at") or now_iso)

    merged_payload = {
        "snapshot_date": date_token,
        "source": "OpenAlex + Google Scholar",
        "built_at": built_at,
        "scholars": merged_scholars,
    }

    if not args.dry_run:
        write_csv(output_panel_path, output_fieldnames, merged_rows)
        write_json(output_json_path, merged_payload)
        if website_output_path:
            write_json(website_output_path, merged_payload)

    total_columns = len(output_fieldnames)
    gs_status_counts: dict[str, int] = {}
    for row in merged_rows:
        status = row.get("gs_enrichment_status", "")
        gs_status_counts[status] = gs_status_counts.get(status, 0) + 1

    print(f"Panel CSV:    {panel_path}")
    print(f"Validation:   {validation_path}")
    print(f"Enrichment:   {len(enrichment_paths)} file(s)")
    print(f"Rows:         {len(merged_rows)}")
    print(f"Columns:      {total_columns}")
    if args.dry_run:
        print("Dry run:      yes")
    else:
        print(f"Output CSV:   {output_panel_path}")
        print(f"Output JSON:  {output_json_path}")
        if website_output_path:
            print(f"Website JSON: {website_output_path}")
    for status in ("pass", "warn", "fail", "missing"):
        if status in gs_status_counts:
            print(f"{status:>11}: {gs_status_counts[status]}")


if __name__ == "__main__":
    main()
