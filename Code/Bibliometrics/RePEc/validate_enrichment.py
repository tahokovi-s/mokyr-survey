#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import glob
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CODE_ROOT = PROJECT_ROOT / "Code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from Bibliometrics.RePEc.schemas import validate_enrichment_record, validate_manifest_record
from Bibliometrics.build_openalex_panel import (
    MASTER_PATTERN,
    normalize_affiliation,
    resolve_path,
    split_parenthetical_variants,
    token_overlap_ratio,
    write_csv,
)
from Shared.name_normalization import normalize_person_text


REPEC_MANIFEST_PATTERN = re.compile(r"^RePEc_Manifest_(\d{6})\.jsonl$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate RePEc enrichment JSONL output")
    parser.add_argument("--date", default=None, help="Date suffix for default input/output paths (MMDDYY)")
    parser.add_argument("--manifest", default=None, help="Path to RePEc manifest JSONL")
    parser.add_argument("--enrichment", nargs="+", required=True, help="One or more enrichment JSONL paths or globs")
    parser.add_argument("--output", default=None, help="Output CSV path")
    return parser.parse_args()


def infer_date_token(args: argparse.Namespace) -> str:
    if args.date:
        return args.date
    if args.manifest:
        match = REPEC_MANIFEST_PATTERN.match(Path(args.manifest).name)
        if match:
            return match.group(1)
    latest_master = resolve_path(None, None, MASTER_PATTERN)
    match = MASTER_PATTERN.match(latest_master.name)
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
                print(f"[warn] Skipping malformed JSON in {path}:{line_number}: {exc}", file=sys.stderr)
                continue
            if not isinstance(payload, dict):
                print(f"[warn] Skipping non-object JSON in {path}:{line_number}", file=sys.stderr)
                continue
            rows.append(payload)
    return rows


def build_name_variants(manifest_record: dict[str, Any]) -> list[str]:
    first_name = manifest_record.get("first_name", "") or ""
    last_name = manifest_record.get("last_name", "") or ""
    if first_name or last_name:
        variants = split_parenthetical_variants(first_name, last_name)
    else:
        full_name = (manifest_record.get("full_name", "") or "").strip()
        variants = [full_name] if full_name else []
    full_name = (manifest_record.get("full_name", "") or "").strip()
    if full_name:
        variants.append(full_name)

    deduped: list[str] = []
    seen = set()
    for variant in variants:
        normalized = normalize_person_text(variant)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(variant)
    return deduped


def cross_check_name(manifest: dict[str, Any], enrichment: dict[str, Any]) -> str:
    repec = enrichment.get("repec") or {}
    profile_name = str(repec.get("name_on_profile") or "").strip()
    if not profile_name:
        return "skip"

    candidate_norm = normalize_person_text(profile_name)
    if not candidate_norm:
        return "skip"

    for variant in build_name_variants(manifest):
        variant_norm = normalize_person_text(variant)
        if not variant_norm:
            continue
        if candidate_norm == variant_norm:
            return "pass"

        variant_tokens = variant_norm.split()
        candidate_tokens = candidate_norm.split()
        if not variant_tokens or not candidate_tokens:
            continue
        if set(variant_tokens) == set(candidate_tokens):
            return "pass"
        if variant_tokens[-1] == candidate_tokens[-1]:
            if variant_tokens[0] == candidate_tokens[0]:
                return "pass"
            if len(variant_tokens[0]) == 1 and candidate_tokens[0].startswith(variant_tokens[0]):
                return "pass"
            if len(candidate_tokens[0]) == 1 and variant_tokens[0].startswith(candidate_tokens[0]):
                return "pass"
    return "fail"


def cross_check_affiliation(manifest: dict[str, Any], enrichment: dict[str, Any]) -> str:
    repec = enrichment.get("repec") or {}
    profile_affiliation = str(repec.get("affiliation_on_profile") or "").strip()
    if not profile_affiliation:
        return "skip"

    candidates = [
        (manifest.get("phd_institution") or "").strip(),
        (manifest.get("current_employer") or "").strip(),
    ]
    candidates = [value for value in candidates if value]
    if not candidates:
        return "skip"

    best_overlap = 0.0
    for candidate in candidates:
        overlap = token_overlap_ratio(normalize_affiliation(candidate), normalize_affiliation(profile_affiliation))
        best_overlap = max(best_overlap, overlap)

    if best_overlap >= 0.60:
        return "pass"
    if best_overlap >= 0.40:
        return "warn"
    return "fail"


def check_temporal_plausibility(manifest: dict[str, Any], enrichment: dict[str, Any]) -> str:
    phd_year_raw = (manifest.get("phd_year") or "").strip()
    repec = enrichment.get("repec") or {}
    h_index = repec.get("citec_h_index")
    cited_by_count = repec.get("citec_cited_by_count")
    if not phd_year_raw or (h_index is None and cited_by_count is None):
        return "skip"
    try:
        phd_year = int(phd_year_raw)
    except ValueError:
        return "skip"

    years_since_phd = datetime.now().year - phd_year
    if years_since_phd <= 0:
        return "skip"

    if isinstance(h_index, int) and h_index > 5 * years_since_phd:
        return "fail"
    # Citation totals vary sharply for senior scholars, so keep this threshold loose
    # enough to catch only clear mismatches rather than strong but valid profiles.
    if isinstance(cited_by_count, int) and cited_by_count > 500 * years_since_phd:
        return "fail"
    return "pass"


def check_source_urls(enrichment: dict[str, Any]) -> str:
    if enrichment.get("lookup_status") != "found":
        return "skip"
    repec = enrichment.get("repec") or {}
    ideas_url = str(repec.get("url") or "").strip()
    if not ideas_url or not ideas_url.startswith("https://ideas.repec.org/"):
        return "fail"

    citec_url = str(repec.get("citec_url") or "").strip()
    if citec_url and not (
        citec_url.startswith("https://citec.repec.org/")
        or citec_url.startswith("https://ideas.repec.org/e/c/")
    ):
        return "fail"
    return "pass"


def summarize_overall_status(
    *,
    schema_valid: str,
    lookup_status: str,
    review_status: str,
    name_check: str,
    affiliation_check: str,
    temporal_check: str,
    source_url_check: str,
    issues: list[str],
) -> str:
    if "unknown_node_id" in issues:
        return "fail"
    if schema_valid == "fail" or source_url_check == "fail":
        return "fail"
    if lookup_status == "ambiguous":
        return "warn"
    if review_status == "candidate_review":
        return "warn"
    if name_check == "fail":
        return "warn"
    if affiliation_check in {"warn", "fail"}:
        return "warn"
    if temporal_check == "fail":
        return "warn"
    if any(issue.startswith("duplicate_node_id") for issue in issues):
        return "warn"
    return "pass"


def validate_one(
    manifest: dict[str, Any] | None,
    enrichment: dict[str, Any],
    *,
    issues: list[str] | None = None,
) -> dict[str, str]:
    row_issues = list(issues or [])
    working = copy.deepcopy(enrichment)
    schema_errors = validate_enrichment_record(working)
    schema_valid = "pass" if not schema_errors else "fail"
    if schema_errors:
        row_issues.extend(f"schema:{error}" for error in schema_errors)

    if manifest is None:
        row_issues.append("unknown_node_id")
        name_check = "skip"
        affiliation_check = "skip"
        temporal_check = "skip"
        full_name = ""
        generation = ""
    else:
        manifest_errors = validate_manifest_record(manifest)
        if manifest_errors:
            row_issues.extend(f"manifest:{error}" for error in manifest_errors)
        name_check = cross_check_name(manifest, working) if schema_valid == "pass" else "skip"
        affiliation_check = cross_check_affiliation(manifest, working) if schema_valid == "pass" else "skip"
        temporal_check = check_temporal_plausibility(manifest, working) if schema_valid == "pass" else "skip"
        full_name = str(manifest.get("full_name") or "")
        generation = str(manifest.get("generation") or "")

    source_url_check = check_source_urls(working) if schema_valid == "pass" else "fail"
    review_status = str(working.get("review_status") or "none")
    overall_status = summarize_overall_status(
        schema_valid=schema_valid,
        lookup_status=str(working.get("lookup_status") or ""),
        review_status=review_status,
        name_check=name_check,
        affiliation_check=affiliation_check,
        temporal_check=temporal_check,
        source_url_check=source_url_check,
        issues=row_issues,
    )

    repec = working.get("repec") or {}
    return {
        "node_id": str(working.get("node_id") or ""),
        "full_name": full_name,
        "generation": generation,
        "lookup_status": str(working.get("lookup_status") or ""),
        "confidence": str(working.get("confidence") or ""),
        "review_status": review_status,
        "schema_valid": schema_valid,
        "name_check": name_check,
        "affiliation_check": affiliation_check,
        "temporal_check": temporal_check,
        "source_url_check": source_url_check,
        "repec_url": str(repec.get("url") or ""),
        "overall_status": overall_status,
        "issues": "; ".join(row_issues),
    }


def missing_validation_row(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "node_id": str(manifest.get("node_id") or ""),
        "full_name": str(manifest.get("full_name") or ""),
        "generation": str(manifest.get("generation") or ""),
        "lookup_status": "",
        "confidence": "",
        "review_status": "",
        "schema_valid": "skip",
        "name_check": "skip",
        "affiliation_check": "skip",
        "temporal_check": "skip",
        "source_url_check": "skip",
        "repec_url": "",
        "overall_status": "missing",
        "issues": "missing_enrichment",
    }


def main() -> None:
    args = parse_args()
    date_token = infer_date_token(args)

    manifest_default = PROJECT_ROOT / "Data" / "Derived" / f"RePEc_Manifest_{date_token}.jsonl"
    output_default = PROJECT_ROOT / "Data" / "Derived" / f"RePEc_Validation_{date_token}.csv"
    manifest_path = resolve_path(args.manifest, manifest_default)
    output_path = resolve_path(args.output, output_default)
    enrichment_paths = expand_paths(args.enrichment)
    if not enrichment_paths:
        raise ValueError("No enrichment files matched the provided --enrichment inputs")

    manifest_rows = load_jsonl(manifest_path)
    manifest_lookup = {(row.get("node_id") or "").strip(): row for row in manifest_rows if (row.get("node_id") or "").strip()}

    enrichment_lookup: dict[str, dict[str, Any]] = {}
    enrichment_issues: dict[str, list[str]] = {}
    duplicate_counts: Counter[str] = Counter()

    for enrichment_path in enrichment_paths:
        for record in load_jsonl(enrichment_path):
            node_id = (record.get("node_id") or "").strip()
            if node_id and node_id in enrichment_lookup:
                duplicate_counts[node_id] += 1
            enrichment_lookup[node_id] = record

    for node_id, count in duplicate_counts.items():
        enrichment_issues.setdefault(node_id, []).append(f"duplicate_node_id_overridden:{count + 1}_records")

    rows: list[dict[str, str]] = []
    seen_node_ids = set()

    for manifest_row in manifest_rows:
        node_id = (manifest_row.get("node_id") or "").strip()
        if not node_id:
            continue
        seen_node_ids.add(node_id)
        enrichment_row = enrichment_lookup.get(node_id)
        if enrichment_row is None:
            rows.append(missing_validation_row(manifest_row))
            continue
        rows.append(validate_one(manifest_row, enrichment_row, issues=enrichment_issues.get(node_id)))

    for node_id, enrichment_row in enrichment_lookup.items():
        if not node_id or node_id in seen_node_ids:
            continue
        rows.append(validate_one(None, enrichment_row, issues=enrichment_issues.get(node_id)))

    fieldnames = [
        "node_id",
        "full_name",
        "generation",
        "lookup_status",
        "confidence",
        "review_status",
        "schema_valid",
        "name_check",
        "affiliation_check",
        "temporal_check",
        "source_url_check",
        "repec_url",
        "overall_status",
        "issues",
    ]
    write_csv(output_path, fieldnames, rows)

    status_counts = Counter(row["overall_status"] for row in rows)
    print(f"Manifest:    {manifest_path}")
    print(f"Enrichment:  {len(enrichment_paths)} file(s)")
    print(f"Rows:        {len(rows)}")
    print(f"Output:      {output_path}")
    for status in ("pass", "warn", "fail", "missing"):
        if status in status_counts:
            print(f"{status:>11}: {status_counts[status]}")


if __name__ == "__main__":
    main()
