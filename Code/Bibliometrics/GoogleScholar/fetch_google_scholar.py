#!/usr/bin/env python3
"""
fetch_google_scholar.py — Automated Google Scholar enrichment using scholarly.

Reads a GS manifest JSONL produced by scholar_manifest.py and writes one
enrichment record per line to an output JSONL, ready for validate_enrichment.py.

Usage:
    python Code/Bibliometrics/GoogleScholar/fetch_google_scholar.py \
        --manifest Data/Derived/GS_Manifest_040126.jsonl \
        --output Data/Derived/GS_Enrichment_scholarly_040126.jsonl

Options:
    --delay FLOAT      Seconds between scholars (default: 5.0)
    --limit N          Process at most N scholars
    --node-ids x,y     Comma-separated node_ids to process (default: all)
    --use-proxy        Enable scholarly free proxy pool (reduces bot detection)
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CODE_ROOT = PROJECT_ROOT / "Code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from Bibliometrics.GoogleScholar.schemas import (
    MAX_TOP_PAPERS,
    empty_enrichment_record,
    validate_enrichment_record,
)

try:
    from scholarly import ProxyGenerator, scholarly
    SCHOLARLY_AVAILABLE = True
except ImportError:
    SCHOLARLY_AVAILABLE = False

MAX_SEARCH_RESULTS = 5

# These terms are useful in a web search engine but are noise for scholarly's
# author index, which already searches inside Google Scholar.
_QUERY_NOISE = ["Google Scholar", "google scholar", "economics", "professor"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Google Scholar profiles via scholarly")
    parser.add_argument("--manifest", required=True, help="Input GS manifest JSONL path")
    parser.add_argument("--output", required=True, help="Output enrichment JSONL path")
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds between scholars (default: 5.0)")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N scholars")
    parser.add_argument("--node-ids", default=None, help="Comma-separated node_ids to process")
    parser.add_argument("--use-proxy", action="store_true", help="Enable scholarly free proxy pool")
    return parser.parse_args()


def resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Bad JSON in {path}:{lineno}: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _institution_tokens(name: str) -> set[str]:
    return {tok.lower() for tok in name.split() if len(tok) > 3}


def _name_matches(candidate_name: str, last_name: str, first_initial: str) -> bool:
    parts = candidate_name.lower().split()
    if not parts or not last_name:
        return False
    if last_name.lower() not in parts:
        return False
    if first_initial and not parts[0].startswith(first_initial.lower()):
        return False
    return True


def _institution_matches(candidate_affil: str, institution: str) -> bool:
    tokens = _institution_tokens(institution)
    if not tokens:
        return False
    affil_lower = candidate_affil.lower()
    matched = sum(1 for tok in tokens if tok in affil_lower)
    return matched / len(tokens) >= 0.5


def _extract_venue(bib: dict[str, Any]) -> str:
    for key in ("venue", "journal", "conference", "booktitle"):
        val = (bib.get(key) or "").strip()
        if val:
            return val
    return ""


def build_enrichment(
    node_id: str,
    author: dict[str, Any],
    confidence: str,
    query_used: str,
) -> dict[str, Any]:
    record = empty_enrichment_record(node_id)

    scholar_id = (author.get("scholar_id") or "").strip()
    gs_url = f"https://scholar.google.com/citations?user={scholar_id}" if scholar_id else ""

    interests = [str(i).strip() for i in (author.get("interests") or []) if str(i).strip()]

    coauthors: list[str] = []
    for c in author.get("coauthors") or []:
        name = (c.get("name") if isinstance(c, dict) else str(c) if c else "").strip()
        if name:
            coauthors.append(name)

    publications = author.get("publications") or []
    works_count = len(publications) if publications else None

    pub_rows: list[dict[str, Any]] = []
    for pub in publications:
        if not isinstance(pub, dict):
            continue
        bib = pub.get("bib") or {}
        title = (bib.get("title") or "").strip()
        if not title:
            continue
        num_citations = pub.get("num_citations")
        if not isinstance(num_citations, int):
            continue
        year_raw = bib.get("pub_year") or bib.get("year")
        try:
            year: int | None = int(year_raw) if year_raw is not None else None
        except (ValueError, TypeError):
            year = None
        pub_rows.append({"title": title, "year": year, "citations": num_citations, "venue": _extract_venue(bib)})

    pub_rows.sort(key=lambda p: (p["citations"] or 0), reverse=True)

    profile_name = (author.get("name") or "").strip()
    affiliation = (author.get("affiliation") or "").strip()
    citedby = author.get("citedby")
    hindex = author.get("hindex")
    i10index = author.get("i10index")

    record["lookup_status"] = "found"
    record["confidence"] = confidence
    record["google_scholar"] = {
        "url": gs_url,
        "name_on_profile": profile_name,
        "affiliation_on_profile": affiliation,
        "interests": interests,
        "works_count": works_count,
        "cited_by_count": citedby if isinstance(citedby, int) else None,
        "h_index": hindex if isinstance(hindex, int) else None,
        "i10_index": i10index if isinstance(i10index, int) else None,
        "coauthors": coauthors,
    }
    record["top_papers"] = pub_rows[:MAX_TOP_PAPERS]
    record["disambiguation_notes"] = (
        f"Matched '{profile_name}' at '{affiliation}' via query '{query_used}'. "
        f"Signals: name=yes, institution={'yes' if confidence == 'high' else 'no (name only)'}."
    )
    return record


def _scholarly_queries(manifest_row: dict[str, Any]) -> list[str]:
    """Build a deduplicated list of queries suitable for scholarly.search_author().

    The manifest queries were designed for a web search engine and often contain
    noise like 'Google Scholar' or 'economics'. scholarly searches the Google
    Scholar author index directly, so clean name-only queries work best.
    """
    full_name = (manifest_row.get("full_name") or "").strip()
    raw_queries = manifest_row.get("search_queries") or []

    cleaned: list[str] = []
    seen: set[str] = set()

    def _add(q: str) -> None:
        for noise in _QUERY_NOISE:
            q = q.replace(noise, "")
        q = " ".join(q.split())
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            cleaned.append(q)

    # Always try the bare full name first.
    _add(full_name)
    for q in raw_queries:
        _add(q)

    return cleaned


def lookup_scholar(manifest_row: dict[str, Any]) -> dict[str, Any]:
    node_id = manifest_row["node_id"]
    full_name = manifest_row.get("full_name", "")
    last_name = (manifest_row.get("last_name") or (full_name.split()[-1] if full_name else "")).strip()
    first_name = (manifest_row.get("first_name") or (full_name.split()[0] if full_name else "")).strip()
    first_initial = first_name[0] if first_name else ""
    institution = (manifest_row.get("current_employer") or manifest_row.get("phd_institution") or "").strip()
    queries = _scholarly_queries(manifest_row)

    for query in queries:
        try:
            results = list(itertools.islice(scholarly.search_author(query), MAX_SEARCH_RESULTS))
        except Exception as exc:
            print(f"  [warn] search failed for '{query}': {exc}", file=sys.stderr)
            continue

        high: list[dict[str, Any]] = []
        medium: list[dict[str, Any]] = []

        for result in results:
            candidate_name = (result.get("name") or "").strip()
            candidate_affil = (result.get("affiliation") or "").strip()
            if not _name_matches(candidate_name, last_name, first_initial):
                continue
            if institution and _institution_matches(candidate_affil, institution):
                high.append(result)
            else:
                medium.append(result)

        if len(high) > 1:
            record = empty_enrichment_record(node_id)
            record["lookup_status"] = "ambiguous"
            record["confidence"] = "low"
            record["disambiguation_notes"] = (
                f"Query '{query}' returned {len(high)} candidates matching name + institution. "
                f"Manual review required."
            )
            return record

        chosen = high[0] if high else (medium[0] if medium else None)
        if chosen is None:
            continue

        confidence = "high" if high else "medium"

        try:
            author = scholarly.fill(chosen)
        except Exception as exc:
            print(f"  [warn] fill failed for '{full_name}': {exc}", file=sys.stderr)
            author = chosen

        return build_enrichment(node_id, author, confidence, query)

    record = empty_enrichment_record(node_id)
    record["lookup_status"] = "not_found"
    record["confidence"] = "medium"
    record["disambiguation_notes"] = (
        f"Tried scholarly queries: {queries!r}. No result with matching name and institution."
    )
    return record


def main() -> None:
    if not SCHOLARLY_AVAILABLE:
        print("scholarly is not installed. Run: pip install scholarly", file=sys.stderr)
        sys.exit(1)

    args = parse_args()
    manifest_path = resolve(args.manifest)
    output_path = resolve(args.output)

    if args.use_proxy:
        pg = ProxyGenerator()
        pg.FreeProxies()
        scholarly.use_proxy(pg)
        print("Free proxy pool enabled.", file=sys.stderr)

    manifest_rows = load_jsonl(manifest_path)
    node_id_filter: set[str] = set()
    if args.node_ids:
        node_id_filter = {s.strip() for s in args.node_ids.split(",") if s.strip()}

    results: list[dict[str, Any]] = []
    processed = 0

    for manifest_row in manifest_rows:
        node_id = (manifest_row.get("node_id") or "").strip()
        if not node_id:
            continue
        if node_id_filter and node_id not in node_id_filter:
            continue
        if args.limit is not None and processed >= args.limit:
            break

        if processed > 0:
            time.sleep(args.delay)

        print(f"[{processed + 1}] {node_id} — {manifest_row.get('full_name', '')}", file=sys.stderr)

        enrichment = lookup_scholar(manifest_row)
        errors = validate_enrichment_record(enrichment)
        if errors:
            print(f"  [warn] validation: {'; '.join(errors)}", file=sys.stderr)
        results.append(enrichment)
        processed += 1
        print(f"  -> {enrichment.get('lookup_status', '')}", file=sys.stderr)

    write_jsonl(output_path, results)

    print(f"\nProcessed:  {processed}", file=sys.stderr)
    print(f"Output:     {output_path}", file=sys.stderr)
    status_counts: dict[str, int] = {}
    for r in results:
        s = r.get("lookup_status", "")
        status_counts[s] = status_counts.get(s, 0) + 1
    for status in ("found", "not_found", "ambiguous"):
        if status in status_counts:
            print(f"  {status}: {status_counts[status]}", file=sys.stderr)


if __name__ == "__main__":
    main()
