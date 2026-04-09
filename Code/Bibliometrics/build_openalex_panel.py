#!/usr/bin/env python3
"""
Build an OpenAlex-enriched bibliometric panel from the master contact list.

Outputs:
  Data/Derived/OpenAlex_Scholar_Matches_{date}.csv
  Data/Derived/OpenAlex_Match_Review_{date}.csv
  Data/Derived/OpenAlex_Top_Papers_{date}.csv
  Data/Derived/Bibliometric_Panel_{date}.csv
  Data/Derived/Bibliometric_Panel_{date}.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CODE_ROOT = PROJECT_ROOT / "Code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from Bibliometrics.fetch_openalex import OpenAlexClient  # noqa: E402


MASTER_PATTERN = re.compile(r"^Master_Contact_List_(\d{6})\.csv$")
NODES_PATTERN = re.compile(r"^Network_Nodes_(\d{6})\.csv$")
DEFAULT_AUTHOR_SEARCH_PAGE_SIZE = 25
TOP_PAPERS_LIMIT = 10
WORKS_PAGE_SIZE = 200
AUTO_MATCH_SCORE = 0.78
SECONDARY_AUTO_MATCH_SCORE = 0.68
AMBIGUOUS_SCORE = 0.50
MIN_CLEAR_GAP = 0.10
NICKNAME_GROUPS = [
    {"jon", "jonathan"},
    {"mike", "michael"},
    {"tom", "thomas"},
    {"chris", "christopher"},
    {"matt", "matthew"},
    {"josh", "joshua"},
    {"nick", "nicholas", "nicolas"},
    {"ben", "benjamin"},
    {"liz", "elizabeth"},
    {"bill", "william"},
    {"alex", "alexander", "alexandra"},
]


def parse_mmddyy(token: str) -> datetime:
    return datetime.strptime(token, "%m%d%y")


def latest_path(pattern: re.Pattern[str]) -> Path:
    derived = PROJECT_ROOT / "Data" / "Derived"
    matches = []
    for path in derived.iterdir():
        match = pattern.match(path.name)
        if match:
            matches.append((parse_mmddyy(match.group(1)), path))
    if not matches:
        raise FileNotFoundError(f"No files found for pattern {pattern.pattern}")
    matches.sort()
    return matches[-1][1]


def resolve_path(raw_path: str | None, default_path: Path | None = None, pattern: re.Pattern[str] | None = None) -> Path:
    if raw_path:
        path = Path(raw_path)
        return path if path.is_absolute() else PROJECT_ROOT / path
    if default_path is not None:
        return default_path
    if pattern is not None:
        return latest_path(pattern)
    raise ValueError("resolve_path needs a raw path, default path, or pattern")


def load_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_text(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("\u2019", "'").replace("\u02bc", "'")
    text = re.sub(r"[()]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_affiliation(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"\bdepartment of\b", " ", text)
    text = re.sub(r"\bschool of\b", " ", text)
    text = re.sub(r"\bcollege of\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def first_name_alias_match(left: str, right: str) -> bool:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if left_norm == right_norm:
        return True
    for group in NICKNAME_GROUPS:
        if left_norm in group and right_norm in group:
            return True
    return False


def split_parenthetical_variants(first_name: str, last_name: str) -> list[str]:
    full_name = " ".join(part for part in (first_name.strip(), last_name.strip()) if part).strip()
    if not full_name:
        return []

    variants = [full_name]
    stripped_last = re.sub(r"\([^)]*\)", " ", last_name).strip()
    stripped_last = re.sub(r"\s+", " ", stripped_last)
    if stripped_last and stripped_last != last_name.strip():
        variants.append(" ".join(part for part in (first_name.strip(), stripped_last) if part).strip())

    paren_bits = re.findall(r"\(([^)]*)\)", last_name)
    if paren_bits:
        remaining_last = re.sub(r"\([^)]*\)", " ", last_name).strip()
        remaining_last = re.sub(r"\s+", " ", remaining_last)
        for bit in paren_bits:
            combo_last = " ".join(part for part in (bit.strip(), remaining_last) if part).strip()
            combo_last = re.sub(r"\s+", " ", combo_last)
            if combo_last:
                variants.append(" ".join(part for part in (first_name.strip(), combo_last) if part).strip())

    deduped = []
    seen = set()
    for variant in variants:
        key = normalize_text(variant)
        if key and key not in seen:
            seen.add(key)
            deduped.append(variant)
    return deduped


def build_name_queries(row: dict[str, Any]) -> list[str]:
    queries = split_parenthetical_variants(row.get("first_name", ""), row.get("last_name", ""))
    first_name = (row.get("first_name", "") or "").strip()
    last_name = (row.get("last_name", "") or "").strip()
    if first_name and last_name:
        queries.append(f"{first_name} {last_name}")
    deduped = []
    seen = set()
    for query in queries:
        key = normalize_text(query)
        if key and key not in seen:
            seen.add(key)
            deduped.append(query)
    return deduped


def build_full_name(row: dict[str, Any]) -> str:
    return " ".join(
        part for part in ((row.get("first_name", "") or "").strip(), (row.get("last_name", "") or "").strip()) if part
    ).strip()


def candidate_name_variants(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("display_name", "full_name"):
        value = candidate.get(field)
        if value:
            values.append(str(value))
    for field in ("display_name_alternatives", "raw_author_names"):
        for value in candidate.get(field) or []:
            if value and ";" not in value:
                values.append(str(value))

    deduped = []
    seen = set()
    for value in values:
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            deduped.append(value)
    return deduped


def candidate_institution_names(candidate: dict[str, Any]) -> list[str]:
    names = []
    for institution in candidate.get("last_known_institutions") or []:
        display_name = (institution or {}).get("display_name")
        if display_name:
            names.append(display_name)
    for affiliation in candidate.get("affiliations") or []:
        display_name = ((affiliation or {}).get("institution") or {}).get("display_name")
        if display_name:
            names.append(display_name)
    deduped = []
    seen = set()
    for name in names:
        key = normalize_affiliation(name)
        if key and key not in seen:
            seen.add(key)
            deduped.append(name)
    return deduped


def token_overlap_ratio(left: str, right: str) -> float:
    left_tokens = set(normalize_affiliation(left).split())
    right_tokens = set(normalize_affiliation(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def institution_similarity(left: str, right: str) -> float:
    left_norm = normalize_affiliation(left)
    right_norm = normalize_affiliation(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if len(left_norm) >= 8 and (left_norm in right_norm or right_norm in left_norm):
        return 0.75
    overlap = token_overlap_ratio(left_norm, right_norm)
    if overlap >= 0.80:
        return 0.60
    if overlap >= 0.60:
        return 0.40
    return 0.0


def extract_primary_topic(candidate: dict[str, Any]) -> dict[str, str]:
    source = candidate.get("topic_share") or candidate.get("topics") or []
    if not source:
        return {"primary_topic": "", "primary_subfield": "", "primary_field": "", "primary_domain": ""}
    topic = source[0]
    return {
        "primary_topic": str(topic.get("display_name", "") or ""),
        "primary_subfield": str(((topic.get("subfield") or {}).get("display_name", "")) or ""),
        "primary_field": str(((topic.get("field") or {}).get("display_name", "")) or ""),
        "primary_domain": str(((topic.get("domain") or {}).get("display_name", "")) or ""),
    }


def extract_current_institution(candidate: dict[str, Any]) -> str:
    institutions = candidate.get("last_known_institutions") or []
    if institutions:
        return str((institutions[0] or {}).get("display_name", "") or "")
    institutions = candidate_institution_names(candidate)
    return institutions[0] if institutions else ""


def earliest_publication_year(candidate: dict[str, Any]) -> int | None:
    years = []
    for entry in candidate.get("counts_by_year") or []:
        try:
            year = int(entry.get("year"))
        except (TypeError, ValueError):
            continue
        works_count = entry.get("works_count", 0) or entry.get("oa_works_count", 0) or 0
        try:
            works_count_num = int(works_count)
        except (TypeError, ValueError):
            works_count_num = 0
        if works_count_num > 0:
            years.append(year)
    return min(years) if years else None


def name_match_details(scholar: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, str]:
    aliases = [normalize_text(query) for query in build_name_queries(scholar)]
    alias_set = {alias for alias in aliases if alias}
    candidate_names = [normalize_text(value) for value in candidate_name_variants(candidate)]

    for candidate_name in candidate_names:
        if candidate_name and candidate_name in alias_set:
            return 0.65, "exact_name"

    scholar_first = normalize_text(scholar.get("first_name", ""))
    scholar_last = normalize_text(re.sub(r"\([^)]*\)", " ", scholar.get("last_name", "")))
    scholar_last = re.sub(r"\s+", " ", scholar_last).strip()
    scholar_initial = scholar_first[:1]

    for raw_name in candidate_name_variants(candidate):
        candidate_name = normalize_text(raw_name)
        if not candidate_name or not scholar_last:
            continue
        candidate_parts = candidate_name.split()
        candidate_first = candidate_parts[0] if candidate_parts else ""
        if candidate_name.endswith(scholar_last):
            if candidate_first and first_name_alias_match(candidate_first, scholar_first):
                return 0.55, "first_last_match"
            if candidate_first and scholar_initial and candidate_first.startswith(scholar_initial):
                return 0.45, "first_initial_last_match"
        if scholar_first and scholar_first in candidate_name and scholar_last in candidate_name:
            return 0.50, "contains_first_last"
    return 0.0, "no_name_match"


def institution_match_details(scholar: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, list[str]]:
    known_institutions = []
    for field in ("phd_institution", "current_employer"):
        value = (scholar.get(field, "") or "").strip()
        if value:
            known_institutions.append(value)

    candidate_institutions = candidate_institution_names(candidate)
    matched_pairs = []
    best_similarity = 0.0
    for known in known_institutions:
        known_best = 0.0
        known_best_candidate = ""
        for candidate_institution in candidate_institutions:
            similarity = institution_similarity(known, candidate_institution)
            if similarity > known_best:
                known_best = similarity
                known_best_candidate = candidate_institution
        if known_best_candidate and known_best >= 0.40:
            matched_pairs.append(f"{known} ↔ {known_best_candidate}")
            best_similarity = max(best_similarity, known_best)

    if not matched_pairs:
        return 0.0, []

    exact_matches = sum(
        1
        for pair in matched_pairs
        if institution_similarity(pair.split(" ↔ ")[0], pair.split(" ↔ ")[1]) >= 1.0
    )
    score = 0.0
    if exact_matches:
        score += min(0.30, 0.20 + 0.10 * max(0, exact_matches - 1))
    elif best_similarity >= 0.75:
        score += 0.18
    else:
        score += 0.12
    return min(score, 0.30), matched_pairs


def timing_match_score(scholar: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, str]:
    phd_year_raw = (scholar.get("phd_year", "") or "").strip()
    if not phd_year_raw:
        return 0.0, ""
    try:
        phd_year = int(phd_year_raw)
    except ValueError:
        return 0.0, ""

    earliest_year = earliest_publication_year(candidate)
    if earliest_year is None:
        return 0.0, ""
    if phd_year - 12 <= earliest_year <= phd_year + 8:
        return 0.10, f"earliest_pub={earliest_year}"
    if earliest_year > phd_year + 15:
        return -0.10, f"earliest_pub={earliest_year}"
    return 0.0, f"earliest_pub={earliest_year}"


def score_candidate(scholar: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    name_score, name_match_type = name_match_details(scholar, candidate)
    institution_score, institution_pairs = institution_match_details(scholar, candidate)
    timing_score, timing_note = timing_match_score(scholar, candidate)
    total_score = max(0.0, min(1.0, name_score + institution_score + timing_score))

    return {
        "candidate": candidate,
        "score": round(total_score, 4),
        "name_score": round(name_score, 4),
        "institution_score": round(institution_score, 4),
        "timing_score": round(timing_score, 4),
        "name_match_type": name_match_type,
        "institution_pairs": institution_pairs,
        "timing_note": timing_note,
    }


def determine_match_status(scored_candidates: list[dict[str, Any]]) -> tuple[str, str]:
    if not scored_candidates:
        return "no_match", "No candidates returned by OpenAlex search."

    best = scored_candidates[0]
    second = scored_candidates[1] if len(scored_candidates) > 1 else None
    gap = best["score"] - (second["score"] if second else 0.0)

    if best["score"] >= AUTO_MATCH_SCORE and (second is None or gap >= MIN_CLEAR_GAP):
        return "matched", "High-confidence unique match."

    if (
        best["score"] >= SECONDARY_AUTO_MATCH_SCORE
        and best["name_score"] >= 0.55
        and best["institution_score"] >= 0.12
        and (second is None or gap >= 0.15)
    ):
        return "matched", "Name and institution align strongly."

    if best["score"] >= AMBIGUOUS_SCORE:
        if second and second["score"] >= best["score"] - MIN_CLEAR_GAP:
            return "ambiguous_manual_review", "Top candidates are too close to auto-resolve safely."
        return "ambiguous_manual_review", "Candidate is plausible but below auto-match threshold."

    return "no_match", "No candidate cleared the minimum plausibility threshold."


def cache_key(path: str, params: dict[str, Any] | None) -> str:
    raw = json.dumps({"path": path, "params": params or {}}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CachedOpenAlexClient(OpenAlexClient):
    def __init__(self, api_key: str, mailto: str | None, cache_dir: Path, refresh_cache: bool = False) -> None:
        super().__init__(api_key=api_key, mailto=mailto)
        self.cache_dir = cache_dir
        self.refresh_cache = refresh_cache

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
        key = cache_key(path, params)
        cache_path = self.cache_dir / f"{key}.json"
        if cache_path.exists() and not self.refresh_cache:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return payload["data"], payload.get("headers", {})

        data, headers = super().get_json(path, params)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"path": path, "params": params or {}, "headers": headers, "data": data}, ensure_ascii=False),
            encoding="utf-8",
        )
        return data, headers


def search_openalex_candidates(client: CachedOpenAlexClient, scholar: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    queries = build_name_queries(scholar)
    deduped_candidates: dict[str, dict[str, Any]] = {}
    for query in queries:
        data, _headers = client.get_json("/authors", {"search": query, "per-page": DEFAULT_AUTHOR_SEARCH_PAGE_SIZE})
        for candidate in data.get("results", []):
            candidate_id = str(candidate.get("id", "") or "")
            if candidate_id and candidate_id not in deduped_candidates:
                deduped_candidates[candidate_id] = candidate
    return list(deduped_candidates.values()), queries


def fetch_all_works_for_author(
    client: CachedOpenAlexClient,
    author_id: str,
    max_pages: int = 1,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cursor = "*"
    pages_fetched = 0
    while cursor:
        params = {
            "filter": f"authorships.author.id:https://openalex.org/{author_id}",
            "sort": "cited_by_count:desc",
            "per-page": WORKS_PAGE_SIZE,
            "cursor": cursor,
            "select": "id,display_name,doi,publication_year,cited_by_count,primary_location,primary_topic",
        }
        data, _headers = client.get_json("/works", params)
        results.extend(data.get("results", []))
        pages_fetched += 1
        if max_pages and pages_fetched >= max_pages:
            break
        cursor = data.get("meta", {}).get("next_cursor")
    return results


def choose_best_candidate(scholar: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [score_candidate(scholar, candidate) for candidate in candidates]
    scored.sort(
        key=lambda item: (
            -item["score"],
            -int((item["candidate"].get("works_count") or 0)),
            -int((item["candidate"].get("cited_by_count") or 0)),
            str(item["candidate"].get("display_name", "") or "").lower(),
        )
    )
    return scored


def json_cell(value: Any) -> str:
    if value in ("", None, [], {}, ()):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def top_paper_rows_for_scholar(node_id: str, author_id: str, works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for rank, work in enumerate(works[:TOP_PAPERS_LIMIT], start=1):
        venue = (((work.get("primary_location") or {}).get("source") or {}).get("display_name") or "")
        topic = (work.get("primary_topic") or {}).get("display_name") or ""
        rows.append(
            {
                "node_id": node_id,
                "openalex_author_id": author_id,
                "paper_rank": rank,
                "openalex_work_id": str(work.get("id", "") or ""),
                "title": str(work.get("display_name", "") or ""),
                "doi": str(work.get("doi", "") or ""),
                "publication_year": str(work.get("publication_year", "") or ""),
                "cited_by_count": str(work.get("cited_by_count", "") or ""),
                "venue": str(venue),
                "primary_topic": str(topic),
            }
        )
    return rows


def serialize_scholar_json(panel_row: dict[str, Any], top_papers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "node_id": panel_row["node_id"],
        "name": panel_row["full_name"],
        "first_name": panel_row["first_name"],
        "last_name": panel_row["last_name"],
        "generation": panel_row["generation"],
        "advisor": panel_row["advisor"],
        "phd_institution": panel_row["phd_institution"],
        "phd_year": panel_row["phd_year"],
        "current_employer": panel_row["current_employer"],
        "match_status": panel_row["match_status"],
        "match_confidence": float(panel_row["match_confidence"] or 0),
        "needs_manual_review": panel_row["needs_manual_review"] == "1",
        "openalex": {
            "id": panel_row["openalex_id"],
            "display_name": panel_row["openalex_display_name"],
            "works_count": int(panel_row["works_count"] or 0) if panel_row["works_count"] else None,
            "cited_by_count": int(panel_row["cited_by_count"] or 0) if panel_row["cited_by_count"] else None,
            "h_index": int(panel_row["h_index"] or 0) if panel_row["h_index"] else None,
            "i10_index": int(panel_row["i10_index"] or 0) if panel_row["i10_index"] else None,
            "current_institution": panel_row["current_institution_openalex"],
            "primary_field": panel_row["primary_field"],
            "primary_subfield": panel_row["primary_subfield"],
            "primary_topic": panel_row["primary_topic"],
            "primary_domain": panel_row["primary_domain"],
            "counts_by_year": json.loads(panel_row["counts_by_year_json"]) if panel_row["counts_by_year_json"] else [],
            "institutions": json.loads(panel_row["institutions_openalex_json"]) if panel_row["institutions_openalex_json"] else [],
            "topics": json.loads(panel_row["topics_json"]) if panel_row["topics_json"] else [],
        },
        "most_cited_paper": {
            "openalex_work_id": panel_row["most_cited_paper_id"],
            "title": panel_row["most_cited_paper_title"],
            "doi": panel_row["most_cited_paper_doi"],
            "publication_year": int(panel_row["most_cited_paper_year"]) if panel_row["most_cited_paper_year"] else None,
            "cited_by_count": int(panel_row["most_cited_paper_cited_by_count"]) if panel_row["most_cited_paper_cited_by_count"] else None,
            "venue": panel_row["most_cited_paper_venue"],
            "primary_topic": panel_row["most_cited_paper_topic"],
        },
        "top_papers": [
            {
                "rank": int(row["paper_rank"]),
                "openalex_work_id": row["openalex_work_id"],
                "title": row["title"],
                "doi": row["doi"],
                "publication_year": int(row["publication_year"]) if row["publication_year"] else None,
                "cited_by_count": int(row["cited_by_count"]) if row["cited_by_count"] else None,
                "venue": row["venue"],
                "primary_topic": row["primary_topic"],
            }
            for row in top_papers
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an OpenAlex bibliometric panel from the master contact list")
    parser.add_argument("--date", default=None, help="Date suffix for default input/output paths (MMDDYY)")
    parser.add_argument("--master", default=None, help="Path to Master_Contact_List CSV")
    parser.add_argument("--nodes", default=None, help="Optional path to Network_Nodes CSV for phd_year enrichment")
    parser.add_argument("--api-key", default="", help="OpenAlex API key (default: OPENALEX_API_KEY)")
    parser.add_argument("--mailto", default="", help="OpenAlex polite pool email (default: OPENALEX_MAILTO)")
    parser.add_argument("--limit", type=int, default=0, help="Optional row limit for smoke tests")
    parser.add_argument(
        "--max-works-pages",
        type=int,
        default=1,
        help="Pages to fetch per matched author when loading works; default 1 is sufficient for top-10 cited papers, use 0 for all pages",
    )
    parser.add_argument("--refresh-cache", action="store_true", help="Ignore cached OpenAlex responses and refetch")
    parser.add_argument("--cache-dir", default=None, help="Optional cache directory override")
    parser.add_argument("--output-matches", default=None, help="Output CSV for scholar match decisions")
    parser.add_argument("--output-review", default=None, help="Output CSV for candidate review rows")
    parser.add_argument("--output-top-papers", default=None, help="Output CSV for top papers")
    parser.add_argument("--output-panel", default=None, help="Output CSV for the canonical bibliometric panel")
    parser.add_argument("--output-json", default=None, help="Output JSON for the website-friendly panel")
    parser.add_argument("--website-output", default=None, help="Optional additional JSON copy for the static website")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    date_token = args.date
    if args.master:
        master_path = resolve_path(args.master)
        if not date_token:
            match = MASTER_PATTERN.match(master_path.name)
            if match:
                date_token = match.group(1)
    else:
        if date_token:
            master_path = resolve_path(None, PROJECT_ROOT / "Data" / "Derived" / f"Master_Contact_List_{date_token}.csv")
        else:
            master_path = latest_path(MASTER_PATTERN)
            match = MASTER_PATTERN.match(master_path.name)
            date_token = match.group(1) if match else None

    if not date_token:
        raise ValueError("Could not infer a date token. Pass --date explicitly.")

    nodes_default = PROJECT_ROOT / "Data" / "Derived" / f"Network_Nodes_{date_token}.csv"
    nodes_path = resolve_path(args.nodes, nodes_default if nodes_default.exists() else None, NODES_PATTERN if args.nodes is None else None)

    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    matches_out = resolve_path(args.output_matches, derived_dir / f"OpenAlex_Scholar_Matches_{date_token}.csv")
    review_out = resolve_path(args.output_review, derived_dir / f"OpenAlex_Match_Review_{date_token}.csv")
    top_papers_out = resolve_path(args.output_top_papers, derived_dir / f"OpenAlex_Top_Papers_{date_token}.csv")
    panel_out = resolve_path(args.output_panel, derived_dir / f"Bibliometric_Panel_{date_token}.csv")
    json_out = resolve_path(args.output_json, derived_dir / f"Bibliometric_Panel_{date_token}.json")
    website_out = resolve_path(args.website_output) if args.website_output else None

    api_key = args.api_key or os.environ.get("OPENALEX_API_KEY", "")
    mailto = args.mailto or os.environ.get("OPENALEX_MAILTO", "")
    if not api_key:
        sys.exit("OpenAlex API key is required. Pass --api-key or set OPENALEX_API_KEY.")

    cache_dir = resolve_path(args.cache_dir, PROJECT_ROOT / "tmp" / "openalex_cache" / date_token)
    cache_dir.mkdir(parents=True, exist_ok=True)
    client = CachedOpenAlexClient(api_key=api_key, mailto=mailto, cache_dir=cache_dir, refresh_cache=args.refresh_cache)

    master_rows = load_csv(master_path)
    node_rows = load_csv(nodes_path) if nodes_path.exists() else []
    node_by_id = {row.get("node_id", "").strip(): row for row in node_rows}

    if args.limit:
        master_rows = master_rows[: args.limit]

    matches_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    top_paper_rows: list[dict[str, Any]] = []
    panel_rows: list[dict[str, Any]] = []

    print(f"Loading master list: {master_path}")
    print(f"  {len(master_rows)} scholar rows")
    if node_rows:
        print(f"Loading network nodes: {nodes_path}")
        print(f"  {len(node_rows)} node rows")
    print(f"Using OpenAlex cache dir: {cache_dir}")

    for idx, master_row in enumerate(master_rows, start=1):
        node_id = (master_row.get("node_id", "") or "").strip()
        node_row = node_by_id.get(node_id, {})
        scholar = {
            "node_id": node_id,
            "first_name": (master_row.get("first_name", "") or "").strip(),
            "last_name": (master_row.get("last_name", "") or "").strip(),
            "advisor": (master_row.get("advisor", "") or "").strip(),
            "generation": (master_row.get("generation", "") or "").strip(),
            "phd_institution": (master_row.get("phd_institution", "") or "").strip(),
            "current_employer": (master_row.get("current_employer", "") or "").strip(),
            "phd_year": (node_row.get("phd_year", "") or "").strip(),
        }
        full_name = build_full_name(scholar)
        print(f"[{idx}/{len(master_rows)}] Matching {full_name or node_id}")

        candidates, queries = search_openalex_candidates(client, scholar)
        scored_candidates = choose_best_candidate(scholar, candidates)
        match_status, review_note = determine_match_status(scored_candidates)
        best = scored_candidates[0] if scored_candidates else None
        second = scored_candidates[1] if len(scored_candidates) > 1 else None

        openalex_candidate = best["candidate"] if best and match_status == "matched" else {}
        openalex_id = str(openalex_candidate.get("id", "") or "")
        openalex_display_name = str(openalex_candidate.get("display_name", "") or "")
        current_institution_openalex = extract_current_institution(openalex_candidate) if openalex_candidate else ""
        topic_info = extract_primary_topic(openalex_candidate) if openalex_candidate else {
            "primary_topic": "",
            "primary_subfield": "",
            "primary_field": "",
            "primary_domain": "",
        }
        candidate_institutions = candidate_institution_names(openalex_candidate) if openalex_candidate else []
        counts_by_year = openalex_candidate.get("counts_by_year") or []
        topic_share = openalex_candidate.get("topic_share") or openalex_candidate.get("topics") or []

        works = fetch_all_works_for_author(client, openalex_id.rsplit("/", 1)[-1], args.max_works_pages) if openalex_id else []
        scholar_top_papers = top_paper_rows_for_scholar(node_id, openalex_id, works)
        top_paper_rows.extend(scholar_top_papers)
        most_cited = scholar_top_papers[0] if scholar_top_papers else {}

        match_confidence = best["score"] if best else 0.0
        matched_institutions = "; ".join(best["institution_pairs"]) if best else ""
        matches_row = {
            "node_id": node_id,
            "first_name": scholar["first_name"],
            "last_name": scholar["last_name"],
            "full_name": full_name,
            "generation": scholar["generation"],
            "advisor": scholar["advisor"],
            "phd_institution": scholar["phd_institution"],
            "current_employer": scholar["current_employer"],
            "phd_year": scholar["phd_year"],
            "search_queries": "; ".join(queries),
            "match_status": match_status,
            "match_confidence": f"{match_confidence:.4f}" if best else "",
            "match_method": best["name_match_type"] if best else "",
            "review_notes": review_note,
            "candidate_count": len(scored_candidates),
            "best_candidate_score": f"{best['score']:.4f}" if best else "",
            "second_candidate_score": f"{second['score']:.4f}" if second else "",
            "matched_institutions": matched_institutions,
            "openalex_id": openalex_id,
            "openalex_display_name": openalex_display_name,
            "works_count": str(openalex_candidate.get("works_count", "") or ""),
            "cited_by_count": str(openalex_candidate.get("cited_by_count", "") or ""),
            "h_index": str(((openalex_candidate.get("summary_stats") or {}).get("h_index", "")) or ""),
            "i10_index": str(((openalex_candidate.get("summary_stats") or {}).get("i10_index", "")) or ""),
        }
        matches_rows.append(matches_row)

        if match_status != "matched" and scored_candidates:
            for rank, scored in enumerate(scored_candidates[:5], start=1):
                candidate = scored["candidate"]
                review_rows.append(
                    {
                        "node_id": node_id,
                        "full_name": full_name,
                        "match_status": match_status,
                        "candidate_rank": rank,
                        "candidate_score": f"{scored['score']:.4f}",
                        "name_score": f"{scored['name_score']:.4f}",
                        "institution_score": f"{scored['institution_score']:.4f}",
                        "timing_score": f"{scored['timing_score']:.4f}",
                        "name_match_type": scored["name_match_type"],
                        "timing_note": scored["timing_note"],
                        "search_queries": "; ".join(queries),
                        "institution_matches": "; ".join(scored["institution_pairs"]),
                        "candidate_openalex_id": str(candidate.get("id", "") or ""),
                        "candidate_display_name": str(candidate.get("display_name", "") or ""),
                        "candidate_works_count": str(candidate.get("works_count", "") or ""),
                        "candidate_cited_by_count": str(candidate.get("cited_by_count", "") or ""),
                        "candidate_h_index": str(((candidate.get("summary_stats") or {}).get("h_index", "")) or ""),
                        "candidate_current_institution": extract_current_institution(candidate),
                        "candidate_institutions": "; ".join(candidate_institution_names(candidate)),
                    }
                )
        elif match_status != "matched":
            review_rows.append(
                {
                    "node_id": node_id,
                    "full_name": full_name,
                    "match_status": match_status,
                    "candidate_rank": "",
                    "candidate_score": "",
                    "name_score": "",
                    "institution_score": "",
                    "timing_score": "",
                    "name_match_type": "",
                    "timing_note": "",
                    "search_queries": "; ".join(queries),
                    "institution_matches": "",
                    "candidate_openalex_id": "",
                    "candidate_display_name": "",
                    "candidate_works_count": "",
                    "candidate_cited_by_count": "",
                    "candidate_h_index": "",
                    "candidate_current_institution": "",
                    "candidate_institutions": "",
                }
            )

        panel_rows.append(
            {
                "node_id": node_id,
                "first_name": scholar["first_name"],
                "last_name": scholar["last_name"],
                "full_name": full_name,
                "generation": scholar["generation"],
                "advisor": scholar["advisor"],
                "phd_institution": scholar["phd_institution"],
                "phd_year": scholar["phd_year"],
                "current_employer": scholar["current_employer"],
                "openalex_id": openalex_id,
                "openalex_display_name": openalex_display_name,
                "openalex_url": openalex_id,
                "match_status": match_status,
                "match_confidence": f"{match_confidence:.4f}" if best else "",
                "match_method": best["name_match_type"] if best else "",
                "needs_manual_review": "1" if match_status != "matched" else "0",
                "review_notes": review_note,
                "works_count": str(openalex_candidate.get("works_count", "") or ""),
                "cited_by_count": str(openalex_candidate.get("cited_by_count", "") or ""),
                "h_index": str(((openalex_candidate.get("summary_stats") or {}).get("h_index", "")) or ""),
                "i10_index": str(((openalex_candidate.get("summary_stats") or {}).get("i10_index", "")) or ""),
                "current_institution_openalex": current_institution_openalex,
                "primary_field": topic_info["primary_field"],
                "primary_subfield": topic_info["primary_subfield"],
                "primary_topic": topic_info["primary_topic"],
                "primary_domain": topic_info["primary_domain"],
                "candidate_count": len(scored_candidates),
                "matched_institutions": matched_institutions,
                "institutions_openalex_json": json_cell(candidate_institutions),
                "topics_json": json_cell(topic_share[:10]),
                "counts_by_year_json": json_cell(counts_by_year),
                "most_cited_paper_id": most_cited.get("openalex_work_id", ""),
                "most_cited_paper_title": most_cited.get("title", ""),
                "most_cited_paper_doi": most_cited.get("doi", ""),
                "most_cited_paper_year": most_cited.get("publication_year", ""),
                "most_cited_paper_cited_by_count": most_cited.get("cited_by_count", ""),
                "most_cited_paper_venue": most_cited.get("venue", ""),
                "most_cited_paper_topic": most_cited.get("primary_topic", ""),
            }
        )

    match_fields = [
        "node_id",
        "first_name",
        "last_name",
        "full_name",
        "generation",
        "advisor",
        "phd_institution",
        "current_employer",
        "phd_year",
        "search_queries",
        "match_status",
        "match_confidence",
        "match_method",
        "review_notes",
        "candidate_count",
        "best_candidate_score",
        "second_candidate_score",
        "matched_institutions",
        "openalex_id",
        "openalex_display_name",
        "works_count",
        "cited_by_count",
        "h_index",
        "i10_index",
    ]
    review_fields = [
        "node_id",
        "full_name",
        "match_status",
        "candidate_rank",
        "candidate_score",
        "name_score",
        "institution_score",
        "timing_score",
        "name_match_type",
        "timing_note",
        "search_queries",
        "institution_matches",
        "candidate_openalex_id",
        "candidate_display_name",
        "candidate_works_count",
        "candidate_cited_by_count",
        "candidate_h_index",
        "candidate_current_institution",
        "candidate_institutions",
    ]
    top_paper_fields = [
        "node_id",
        "openalex_author_id",
        "paper_rank",
        "openalex_work_id",
        "title",
        "doi",
        "publication_year",
        "cited_by_count",
        "venue",
        "primary_topic",
    ]
    panel_fields = [
        "node_id",
        "first_name",
        "last_name",
        "full_name",
        "generation",
        "advisor",
        "phd_institution",
        "phd_year",
        "current_employer",
        "openalex_id",
        "openalex_display_name",
        "openalex_url",
        "match_status",
        "match_confidence",
        "match_method",
        "needs_manual_review",
        "review_notes",
        "works_count",
        "cited_by_count",
        "h_index",
        "i10_index",
        "current_institution_openalex",
        "primary_field",
        "primary_subfield",
        "primary_topic",
        "primary_domain",
        "candidate_count",
        "matched_institutions",
        "institutions_openalex_json",
        "topics_json",
        "counts_by_year_json",
        "most_cited_paper_id",
        "most_cited_paper_title",
        "most_cited_paper_doi",
        "most_cited_paper_year",
        "most_cited_paper_cited_by_count",
        "most_cited_paper_venue",
        "most_cited_paper_topic",
    ]

    write_csv(matches_out, match_fields, matches_rows)
    write_csv(review_out, review_fields, review_rows)
    write_csv(top_papers_out, top_paper_fields, top_paper_rows)
    write_csv(panel_out, panel_fields, panel_rows)

    top_papers_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in top_paper_rows:
        top_papers_by_node[row["node_id"]].append(row)
    for rows in top_papers_by_node.values():
        rows.sort(key=lambda row: int(row["paper_rank"]))

    website_payload = {
        "snapshot_date": date_token,
        "source": "OpenAlex",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scholars": [serialize_scholar_json(row, top_papers_by_node.get(row["node_id"], [])) for row in panel_rows],
    }
    write_json(json_out, website_payload)
    if website_out:
        write_json(website_out, website_payload)

    status_counts = defaultdict(int)
    for row in panel_rows:
        status_counts[row["match_status"]] += 1
    print("\n=== OpenAlex Panel Summary ===")
    print(f"Date token:             {date_token}")
    print(f"Scholars processed:     {len(panel_rows)}")
    for status in ("matched", "ambiguous_manual_review", "no_match"):
        print(f"{status}:".ljust(24) + f"{status_counts.get(status, 0)}")
    print(f"Top-paper rows:         {len(top_paper_rows)}")
    print(f"Matches CSV:            {matches_out}")
    print(f"Review CSV:             {review_out}")
    print(f"Top papers CSV:         {top_papers_out}")
    print(f"Panel CSV:              {panel_out}")
    print(f"Panel JSON:             {json_out}")
    if website_out:
        print(f"Website JSON copy:      {website_out}")


if __name__ == "__main__":
    main()
