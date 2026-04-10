#!/usr/bin/env python3
"""
fetch_repec.py — Automated RePEc/IDEAS/CitEc enrichment.

Reads a RePEc manifest JSONL and writes one enrichment record per line, ready
for validate_enrichment.py.

Usage:
    python3 Code/Bibliometrics/RePEc/fetch_repec.py \
        --manifest Data/Derived/RePEc_Manifest_040126.jsonl \
        --output Data/Derived/RePEc_Enrichment_040126.jsonl
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CODE_ROOT = PROJECT_ROOT / "Code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from Bibliometrics.RePEc.schemas import (
    MAX_TOP_PAPERS,
    empty_enrichment_record,
    validate_enrichment_record,
)
from Bibliometrics.build_openalex_panel import normalize_affiliation, split_parenthetical_variants, token_overlap_ratio
from Shared.name_normalization import normalize_person_text

try:
    import requests
    from bs4 import BeautifulSoup

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}
IDEAS_BASE = "https://ideas.repec.org"
IDEAS_BROWSE = IDEAS_BASE + "/cgi-bin/browse.pl?type=p&author={query}"
IDEAS_SEARCH = IDEAS_BASE + "/search.html?q={query}"
IDEAS_AUTHOR_SEARCH = IDEAS_BASE + "/cgi-bin/htsearch2"
IDEAS_PROFILE = IDEAS_BASE + "/e/{handle}.html"
IDEAS_PROFILE_ALT = IDEAS_BASE + "/f/{handle}.html"
REFS_EXPORT = IDEAS_BASE + "/cgi-bin/refs.cgi"
AUTHORS_PROFILE = "https://authors.repec.org/pro/{handle}/"
HANDLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,31}$")
IDEAS_HANDLE_PATTERN = re.compile(r"/(?:e|f)/([A-Za-z0-9]+)\.html")
AUTHORS_HANDLE_PATTERN = re.compile(r"authors\.repec\.org/pro/([A-Za-z0-9]+)/?")
RAW_SHORT_ID_PATTERN = re.compile(r"RePEc Short-ID:\s*([A-Za-z0-9]+)", re.IGNORECASE)
PAREN_CONTENT_PATTERN = re.compile(r"\(([^)]*)\)")
NAME_FRAGMENT_PATTERN = re.compile(r"[A-Za-z][A-Za-z' -]*")
NAME_STOPWORDS = {
    "and",
    "at",
    "but",
    "during",
    "for",
    "from",
    "formerly",
    "i",
    "in",
    "my",
    "nee",
    "née",
    "of",
    "the",
    "to",
    "was",
    "while",
    "with",
}
ROBUST_QUERY_LIMIT = 14
MAX_CANDIDATE_HANDLES = 8
NICKNAME_EXPANSIONS = {
    "ben": ["benjamin"],
    "chris": ["christopher"],
    "dan": ["daniel"],
    "jim": ["james"],
    "mike": ["michael"],
    "rick": ["richard"],
    "tom": ["thomas"],
    "tony": ["anthony"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch RePEc/IDEAS profiles")
    parser.add_argument("--manifest", required=True, help="Input RePEc manifest JSONL path")
    parser.add_argument("--output", required=True, help="Output enrichment JSONL path")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between outbound HTTP requests (default: 2.0)")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N scholars")
    parser.add_argument("--node-ids", default=None, help="Comma-separated node_ids to process")
    parser.add_argument("--prior-enrichment", default=None, help="Optional prior enrichment JSONL used to target sparse rows")
    parser.add_argument("--review-output", default=None, help="Optional CSV or JSONL path for robustness review rows")
    parser.add_argument("--override-csv", default=None, help="Optional CSV with node_id,repec_handle_override columns")
    parser.add_argument("--robustness-pass", action="store_true", help="Run broader discovery and review-oriented checks")
    return parser.parse_args()


def resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Bad JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Expected object JSON in {path}:{line_number}")
            rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_override_map(path: Path) -> dict[str, str]:
    overrides: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            node_id = str(row.get("node_id") or "").strip()
            override = normalize_handle(row.get("repec_handle_override"))
            if node_id and override:
                overrides[node_id] = override
    return overrides


def write_review_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".jsonl":
        write_jsonl(path, rows)
        return

    fieldnames = [
        "node_id",
        "full_name",
        "first_pass_status",
        "first_pass_confidence",
        "second_pass_status",
        "second_pass_confidence",
        "review_status",
        "recommended_action",
        "queries_tried",
        "candidate_handles",
        "candidate_profile_names",
        "candidate_affiliations",
        "candidate_urls",
        "candidate_scores",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def normalize_handle(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    for pattern in (IDEAS_HANDLE_PATTERN, AUTHORS_HANDLE_PATTERN):
        match = pattern.search(text)
        if match:
            return match.group(1).lower()

    short_id_match = RAW_SHORT_ID_PATTERN.search(text)
    if short_id_match:
        return short_id_match.group(1).lower()

    if HANDLE_PATTERN.fullmatch(text):
        return text.lower()
    return ""


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def strip_parenthetical_text(value: str) -> str:
    return collapse_whitespace(PAREN_CONTENT_PATTERN.sub(" ", value or ""))


def normalize_name_fragment(value: str) -> str:
    matches = NAME_FRAGMENT_PATTERN.findall(value or "")
    cleaned = collapse_whitespace(" ".join(matches))
    return cleaned.strip(" -'")


def parenthetical_chunks(value: str) -> list[str]:
    return [collapse_whitespace(chunk) for chunk in PAREN_CONTENT_PATTERN.findall(value or "") if collapse_whitespace(chunk)]


def extract_explicit_alternate_name(chunk: str) -> str:
    lowered = chunk.casefold()
    markers = ("but was ", "formerly ", "previously ", "nee ", "née ", "was ")
    for marker in markers:
        if marker in lowered:
            start = lowered.index(marker) + len(marker)
            candidate = chunk[start:]
            candidate = re.split(r"\b(?:while|when|at|during|from|in)\b", candidate, maxsplit=1, flags=re.IGNORECASE)[0]
            return normalize_name_fragment(candidate)
    return ""


def extract_alt_name_bits(value: str) -> list[str]:
    bits: list[str] = []
    for chunk in parenthetical_chunks(value):
        explicit = extract_explicit_alternate_name(chunk)
        if explicit:
            bits.append(explicit)
            continue
        cleaned = normalize_name_fragment(chunk)
        tokens = cleaned.split()
        if not tokens:
            continue
        if any(token.casefold() in NAME_STOPWORDS for token in tokens):
            continue
        if len(tokens) <= 2:
            bits.append(cleaned)
    return bits


def add_deduped(values: list[str], value: str) -> None:
    cleaned = collapse_whitespace(value)
    if not cleaned:
        return
    key = normalize_person_text(cleaned)
    if key and key not in {normalize_person_text(item) for item in values}:
        values.append(cleaned)


def first_name_variants(manifest_row: dict[str, Any], *, robustness: bool = False) -> list[str]:
    raw_first = str(manifest_row.get("first_name") or "").strip()
    variants: list[str] = []
    base_first = strip_parenthetical_text(raw_first)
    add_deduped(variants, base_first)
    for chunk in extract_alt_name_bits(raw_first):
        add_deduped(variants, chunk)

    full_name = str(manifest_row.get("full_name") or "").strip()
    if not variants and full_name:
        tokens = strip_parenthetical_text(full_name).split()
        if tokens:
            add_deduped(variants, tokens[0])

    if not robustness:
        return variants

    expanded: list[str] = []
    for variant in variants:
        add_deduped(expanded, variant)
        first_token = variant.split()[0]
        add_deduped(expanded, first_token)
        for alt in NICKNAME_EXPANSIONS.get(first_token.casefold(), []):
            add_deduped(expanded, alt)
        for short, expansions in NICKNAME_EXPANSIONS.items():
            if first_token.casefold() in expansions:
                add_deduped(expanded, short)
    return expanded or variants


def last_name_variants(manifest_row: dict[str, Any], *, robustness: bool = False) -> list[str]:
    raw_last = str(manifest_row.get("last_name") or "").strip()
    variants: list[str] = []
    base_last = strip_parenthetical_text(raw_last)
    add_deduped(variants, base_last)

    for chunk in extract_alt_name_bits(raw_last):
        add_deduped(variants, chunk)
        if base_last and chunk != base_last:
            add_deduped(variants, f"{chunk} {base_last}")

    if not robustness:
        return variants

    expanded: list[str] = []
    for variant in variants:
        add_deduped(expanded, variant)
        tokens = variant.split()
        if len(tokens) > 1:
            add_deduped(expanded, tokens[-1])
    return expanded or variants


def build_name_variants(manifest_row: dict[str, Any], *, robustness: bool = False) -> list[str]:
    first_name = (manifest_row.get("first_name") or "").strip()
    last_name = (manifest_row.get("last_name") or "").strip()
    variants = split_parenthetical_variants(first_name, last_name) if (first_name or last_name) else []
    full_name = (manifest_row.get("full_name") or "").strip()
    if full_name:
        variants.append(full_name)
        variants.append(strip_parenthetical_text(full_name))

    if robustness:
        first_variants = first_name_variants(manifest_row, robustness=True) or [strip_parenthetical_text(first_name)]
        last_variants = last_name_variants(manifest_row, robustness=True) or [strip_parenthetical_text(last_name)]
        for first_variant in first_variants[:4]:
            for last_variant in last_variants[:4]:
                variants.append(" ".join(part for part in (first_variant, last_variant) if part).strip())

    deduped: list[str] = []
    seen = set()
    for variant in variants:
        key = normalize_person_text(variant)
        if key and key not in seen:
            seen.add(key)
            deduped.append(variant)
    return deduped


def institution_variants(manifest_row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("current_employer", "phd_institution"):
        raw_value = str(manifest_row.get(field) or "").strip()
        if not raw_value:
            continue
        add_deduped(values, raw_value)
        add_deduped(values, strip_parenthetical_text(raw_value))
        for chunk in parenthetical_chunks(raw_value):
            add_deduped(values, normalize_name_fragment(chunk))
        if "," in raw_value:
            add_deduped(values, raw_value.split(",", 1)[0])
    return values


def profile_name_matches(profile_name: str, manifest_row: dict[str, Any]) -> bool:
    candidate_norm = normalize_person_text(profile_name)
    if not candidate_norm:
        return False

    candidate_tokens = candidate_norm.split()
    for variant in build_name_variants(manifest_row):
        variant_norm = normalize_person_text(variant)
        if not variant_norm:
            continue
        variant_tokens = variant_norm.split()
        if candidate_norm == variant_norm:
            return True
        if set(candidate_tokens) == set(variant_tokens):
            return True
        if candidate_tokens and variant_tokens and candidate_tokens[-1] == variant_tokens[-1]:
            if candidate_tokens[0] == variant_tokens[0]:
                return True
            if len(candidate_tokens[0]) == 1 and variant_tokens[0].startswith(candidate_tokens[0]):
                return True
            if len(variant_tokens[0]) == 1 and candidate_tokens[0].startswith(variant_tokens[0]):
                return True
    return False


def manifest_institution(manifest_row: dict[str, Any]) -> str:
    return (manifest_row.get("current_employer") or manifest_row.get("phd_institution") or "").strip()


def candidate_affiliation_score(candidate_affiliation: str | None, manifest_row: dict[str, Any]) -> float:
    institution = manifest_institution(manifest_row)
    if not institution or not candidate_affiliation:
        return 0.0
    return token_overlap_ratio(normalize_affiliation(institution), normalize_affiliation(candidate_affiliation))


def ideas_profile_url(handle: str) -> str:
    return IDEAS_PROFILE.format(handle=handle)


def ideas_profile_alt_url(handle: str) -> str:
    return IDEAS_PROFILE_ALT.format(handle=handle)


def authors_profile_url(handle: str) -> str:
    return AUTHORS_PROFILE.format(handle=handle)


def direct_citec_url(handle: str) -> str:
    if len(handle) < 2:
        return ""
    return f"https://citec.repec.org/p/{handle[1].lower()}/{handle}.html"


class RePEcClient:
    def __init__(self, delay: float) -> None:
        self.delay = max(0.0, delay)
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)
        self._last_request_at: float | None = None

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        now = time.monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self.delay - elapsed
            if remaining > 0:
                time.sleep(remaining)
        response = self.session.request(method=method, url=url, timeout=60, allow_redirects=True, **kwargs)
        self._last_request_at = time.monotonic()
        if not response.encoding:
            response.encoding = response.apparent_encoding or "utf-8"
        return response


def extract_candidate_handles(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    handles: list[str] = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        handle = normalize_handle(anchor["href"])
        href = anchor["href"]
        if handle and ("/e/" in href or "/f/" in href or "authors.repec.org/pro/" in href):
            if handle not in seen:
                seen.add(handle)
                handles.append(handle)

    for match in RAW_SHORT_ID_PATTERN.finditer(html):
        handle = match.group(1).lower()
        if handle not in seen:
            seen.add(handle)
            handles.append(handle)
    return handles


def dedupe_query_values(queries: list[str], *, limit: int | None = None) -> list[str]:
    deduped: list[str] = []
    seen = set()
    for query in queries:
        cleaned = collapse_whitespace(str(query).replace("(", " ").replace(")", " "))
        if not cleaned:
            continue
        lowered = cleaned.casefold()
        if any(marker in lowered for marker in ("but was ", "formerly ", "previously ", " while ", " during ", " when ")):
            continue
        tokens = normalize_person_text(cleaned, strip_parentheticals=False).split()
        if len(tokens) == 2 and len(tokens[-1]) <= 2 and len(tokens[0]) > 1:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
        if limit is not None and len(deduped) >= limit:
            break
    return deduped


def discovery_queries(manifest_row: dict[str, Any], *, robustness: bool = False) -> list[str]:
    queries: list[str] = []
    full_name = (manifest_row.get("full_name") or "").strip()
    if full_name:
        queries.append(full_name)
    queries.extend(str(item).strip() for item in (manifest_row.get("search_queries") or []) if str(item).strip())

    if robustness:
        queries.extend(build_name_variants(manifest_row, robustness=True))
        first_variants = first_name_variants(manifest_row, robustness=True)
        last_variants = last_name_variants(manifest_row, robustness=True)
        institutions = institution_variants(manifest_row)

        for first_variant in first_variants[:4]:
            for last_variant in last_variants[:4]:
                full_variant = " ".join(part for part in (first_variant, last_variant) if part).strip()
                if not full_variant:
                    continue
                queries.append(full_variant)
                if first_variant:
                    queries.append(f"{first_variant[:1]}. {last_variant}")
                for institution in institutions[:2]:
                    queries.append(f"{full_variant} {institution}")
        for query in list(queries):
            folded = strip_parenthetical_text(query)
            if folded != query:
                queries.append(folded)
        queries = dedupe_query_values(queries, limit=ROBUST_QUERY_LIMIT)
    else:
        queries = dedupe_query_values(queries)
    return queries


def extract_jel_codes(profile_soup: Any) -> list[str] | None:
    codes: list[str] = []
    seen = set()
    for tag in profile_soup.find_all(string=re.compile(r"JEL", re.IGNORECASE)):
        text = " ".join(tag.parent.get_text(" ", strip=True).split()) if tag.parent else str(tag).strip()
        for code in re.findall(r"\b[A-Z]\d{2}\b", text):
            if code not in seen:
                seen.add(code)
                codes.append(code)
    return codes or None


def extract_profile_summary(profile_html: str, handle: str) -> dict[str, Any]:
    soup = BeautifulSoup(profile_html, "html.parser")

    name = soup.find("h1")
    name_on_profile = name.get_text(" ", strip=True) if name else None

    aff_section = soup.find(id="affiliation")
    affiliation = None
    homepage = None
    citec_url = None
    if aff_section is not None:
        aff_heading = aff_section.find("h3")
        if aff_heading:
            parts = [item.strip() for item in aff_heading.stripped_strings if item.strip()]
            affiliation = ", ".join(parts) if parts else None
        homepage_link = aff_section.find("a", href=True)
        if homepage_link is not None:
            homepage = homepage_link["href"].strip() or None

    person_section = soup.find(id="person")
    if not affiliation and person_section is not None:
        postal_cell = person_section.find("td", class_="postallabel")
        if postal_cell is not None and postal_cell.find_next_sibling("td") is not None:
            affiliation = postal_cell.find_next_sibling("td").get_text(" ", strip=True) or None

    citec_link = soup.find("a", href=re.compile(r"/e/c/[A-Za-z0-9]+\.html"))
    if citec_link is not None:
        citec_url = urljoin(IDEAS_BASE, citec_link["href"])

    refs_handle = None
    refs_form = soup.find("form", action="/cgi-bin/refs.cgi")
    if refs_form is not None:
        hidden_input = refs_form.find("input", {"name": "handle"})
        if hidden_input is not None:
            refs_handle = hidden_input.get("value") or None

    return {
        "url": ideas_profile_url(handle),
        "handle": handle,
        "name_on_profile": name_on_profile,
        "affiliation_on_profile": affiliation,
        "homepage": homepage,
        "jel_codes": extract_jel_codes(soup),
        "refs_handle": refs_handle,
        "citec_link": citec_url,
    }


def fetch_ideas_profile(client: RePEcClient, handle: str, notes: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    for url in (ideas_profile_url(handle), ideas_profile_alt_url(handle)):
        try:
            response = client.request("get", url)
        except requests.RequestException as exc:
            notes.append(f"profile:{handle}:{url} error={exc}")
            continue
        notes.append(f"profile:{handle}:{url} status={response.status_code}")
        if response.status_code != 200:
            continue

        summary = extract_profile_summary(response.text, handle)
        summary["url"] = response.url
        return summary, response.text
    return None, None


def fetch_works_export(client: RePEcClient, refs_handle: str | None, notes: list[str]) -> list[dict[str, Any]]:
    if not refs_handle:
        return []
    try:
        response = client.request("post", REFS_EXPORT, data={"handle": refs_handle, "output": 6})
    except requests.RequestException as exc:
        notes.append(f"refs_export_error={exc}")
        return []
    notes.append(f"refs_export status={response.status_code}")
    if response.status_code != 200:
        return []
    payload = response.text.strip()
    if not payload:
        return []
    try:
        parsed = ast.literal_eval(payload)
    except (SyntaxError, ValueError) as exc:
        notes.append(f"refs_export_parse_error={exc}")
        return []
    if not isinstance(parsed, list):
        notes.append("refs_export_not_list")
        return []
    return [item for item in parsed if isinstance(item, dict)]


def choose_display_name(existing: str | None, candidate: str) -> str:
    if not existing:
        return candidate
    existing_tokens = normalize_person_text(existing).split()
    candidate_tokens = normalize_person_text(candidate).split()
    if len(candidate_tokens) > len(existing_tokens):
        return candidate
    if len(candidate_tokens) == len(existing_tokens) and len(candidate) > len(existing):
        return candidate
    return existing


def reorder_if_comma_name(name: str) -> str:
    if "," not in name:
        return name
    parts = [part.strip() for part in name.split(",") if part.strip()]
    if len(parts) < 2:
        return name
    return " ".join(parts[1:] + [parts[0]])


def prune_fragmented_names(names: list[str]) -> list[str]:
    tokenized = [(name, normalize_person_text(name).split()) for name in names]
    cleaned: list[str] = []
    for name, tokens in tokenized:
        if not tokens:
            continue
        is_fragment = False
        for other_name, other_tokens in tokenized:
            if other_name == name or len(other_tokens) <= len(tokens):
                continue
            if other_tokens[: len(tokens)] == tokens:
                is_fragment = True
                break
        if not is_fragment:
            cleaned.append(name)
    return cleaned


def extract_coauthors(works: list[dict[str, Any]], manifest_row: dict[str, Any]) -> list[str] | None:
    manifest_name_keys = {normalize_person_text(item) for item in build_name_variants(manifest_row)}
    best_by_key: dict[str, str] = {}

    for work in works:
        author_field = str(work.get("author") or "").strip()
        if not author_field:
            continue
        author_field = author_field.replace(" and ", " & ").replace(";", " & ")
        for raw_part in [part.strip(" ,.") for part in author_field.split("&") if part.strip(" ,.")]:
            name = reorder_if_comma_name(" ".join(raw_part.split()))
            normalized = normalize_person_text(name)
            if not normalized or normalized in manifest_name_keys:
                continue
            tokens = normalized.split()
            if len(tokens) < 2:
                continue
            key = f"{tokens[0]}::{tokens[-1]}"
            best_by_key[key] = choose_display_name(best_by_key.get(key), name)

    coauthors = prune_fragmented_names(sorted(best_by_key.values()))
    return coauthors or None


def candidate_citec_urls(profile_summary: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for candidate in (
        direct_citec_url(str(profile_summary.get("handle") or "")),
        profile_summary.get("citec_link"),
    ):
        value = str(candidate or "").strip()
        if value and value not in urls:
            urls.append(value)
    return urls


def parse_citec_metrics(citec_html: str) -> tuple[int | None, int | None]:
    text = " ".join(BeautifulSoup(citec_html, "html.parser").get_text(" ", strip=True).split())
    h_match = re.search(r"(\d+)\s+H index", text, re.IGNORECASE)
    citations_match = re.search(r"(\d+)\s+Citations", text, re.IGNORECASE)
    return (
        int(h_match.group(1)) if h_match else None,
        int(citations_match.group(1)) if citations_match else None,
    )


def parse_citec_top_papers(citec_html: str, total_citations: int | None) -> list[dict[str, Any]]:
    soup = BeautifulSoup(citec_html, "html.parser")
    works_header = soup.find("h3", id="works")
    if works_header is None:
        return []
    works_table = works_header.find_next("table")
    if works_table is None:
        return []

    best_by_title: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    for row in works_table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 4:
            continue

        year_text = cells[0].get_text(" ", strip=True)
        cited_text = cells[3].get_text(" ", strip=True)
        if not (year_text.isdigit() and cited_text.isdigit()):
            continue

        citations = int(cited_text)
        if total_citations is not None and citations > total_citations:
            continue

        title_cell = cells[1]
        title_tag = title_cell.find("b")
        title = title_tag.get_text(" ", strip=True) if title_tag else ""
        if not title:
            continue

        cell_text = " ".join(title_cell.get_text(" ", strip=True).split())
        venue_match = re.search(r"In:\s*([^.]+)\.", cell_text)
        paper = {
            "title": title,
            "year": int(year_text),
            "citations": citations,
            "venue": venue_match.group(1).strip() if venue_match else None,
        }
        key = normalize_person_text(title, strip_parentheticals=False, strip_honorifics=False)
        current = best_by_title.get(key)
        if current is None or citations > int(current.get("citations") or -1):
            best_by_title[key] = paper
            if key not in ordered_keys:
                ordered_keys.append(key)

    papers = sorted(best_by_title.values(), key=lambda item: (item["citations"], item["year"] or 0), reverse=True)
    return papers[:MAX_TOP_PAPERS]


def fetch_citec_profile(client: RePEcClient, profile_summary: dict[str, Any], notes: list[str]) -> tuple[str | None, int | None, int | None, list[dict[str, Any]]]:
    best_result: tuple[str | None, int | None, int | None, list[dict[str, Any]]] = (None, None, None, [])
    best_score = (-1, -1, -1)

    for url in candidate_citec_urls(profile_summary):
        try:
            response = client.request("get", url)
        except requests.RequestException as exc:
            notes.append(f"citec:{url} error={exc}")
            continue
        notes.append(f"citec:{url} status={response.status_code}")
        if response.status_code != 200:
            continue
        h_index, cited_by_count = parse_citec_metrics(response.text)
        top_papers = parse_citec_top_papers(response.text, cited_by_count)
        score = (
            int(h_index is not None) + int(cited_by_count is not None) + int(bool(top_papers)),
            len(top_papers),
            int("citec.repec.org" in response.url),
        )
        if score > best_score:
            best_score = score
            best_result = (response.url, h_index, cited_by_count, top_papers)
        if h_index is not None and cited_by_count is not None and top_papers:
            break
    return best_result


def allowed_first_tokens(manifest_row: dict[str, Any], *, robustness: bool = False) -> set[str]:
    tokens: set[str] = set()
    for variant in first_name_variants(manifest_row, robustness=robustness):
        normalized = normalize_person_text(variant)
        if normalized:
            tokens.add(normalized.split()[0])
    return tokens


def allowed_last_tokens(manifest_row: dict[str, Any], *, robustness: bool = False) -> set[str]:
    tokens: set[str] = set()
    for variant in last_name_variants(manifest_row, robustness=robustness):
        normalized = normalize_person_text(variant)
        if normalized:
            tokens.add(normalized.split()[-1])
    for variant in build_name_variants(manifest_row, robustness=robustness):
        normalized = normalize_person_text(variant)
        if normalized:
            tokens.add(normalized.split()[-1])
    return tokens


def review_candidate_score(
    manifest_row: dict[str, Any],
    profile_summary: dict[str, Any],
    candidate_meta: dict[str, Any],
) -> tuple[float, str]:
    profile_name = str(profile_summary.get("name_on_profile") or "").strip()
    candidate_norm = normalize_person_text(profile_name)
    if not candidate_norm:
        return 0.0, "profile_name_blank"

    candidate_tokens = candidate_norm.split()
    candidate_first = candidate_tokens[0]
    candidate_last = candidate_tokens[-1]
    allowed_lasts = allowed_last_tokens(manifest_row, robustness=True)
    if candidate_last not in allowed_lasts:
        return 0.0, "surname_mismatch"

    allowed_firsts = allowed_first_tokens(manifest_row, robustness=True)
    first_score = 0.0
    first_reason = "first_mismatch"
    if candidate_first in allowed_firsts:
        first_score = 1.0
        first_reason = "first_exact"
    elif any(len(token) == 1 and candidate_first.startswith(token) for token in allowed_firsts):
        first_score = 0.8
        first_reason = "first_initial"
    elif any(len(candidate_first) == 1 and token.startswith(candidate_first) for token in allowed_firsts):
        first_score = 0.8
        first_reason = "candidate_initial"

    if first_score == 0.0:
        return 0.0, first_reason

    aff_score = candidate_affiliation_score(profile_summary.get("affiliation_on_profile"), manifest_row)
    query_text = str(candidate_meta.get("query") or "").casefold()
    institution_bonus = 0.1 if any(variant and variant.casefold() in query_text for variant in institution_variants(manifest_row)) else 0.0
    total = 0.65 * first_score + 0.35 * min(1.0, aff_score / 0.60) + institution_bonus
    return min(total, 1.0), f"surname_exact+{first_reason}+aff_{aff_score:.2f}"


def evaluate_candidate(
    manifest_row: dict[str, Any],
    handle: str,
    profile_summary: dict[str, Any],
    override_handle: str,
) -> tuple[str, float]:
    if not profile_name_matches(str(profile_summary.get("name_on_profile") or ""), manifest_row):
        return "reject", 0.0

    if override_handle and handle == override_handle:
        return "high", 1.0

    aff_score = candidate_affiliation_score(profile_summary.get("affiliation_on_profile"), manifest_row)
    if aff_score >= 0.60:
        return "high", aff_score
    return "medium", aff_score


def build_enrichment(
    node_id: str,
    profile_summary: dict[str, Any],
    works: list[dict[str, Any]],
    citec_url: str | None,
    citec_h_index: int | None,
    citec_cited_by_count: int | None,
    top_papers: list[dict[str, Any]],
    confidence: str,
    notes: list[str],
    manifest_row: dict[str, Any],
    review_status: str = "none",
) -> dict[str, Any]:
    record = empty_enrichment_record(node_id)
    record["lookup_status"] = "found"
    record["confidence"] = confidence
    record["review_status"] = review_status
    record["repec"] = {
        "url": profile_summary.get("url"),
        "handle": profile_summary.get("handle"),
        "name_on_profile": profile_summary.get("name_on_profile"),
        "affiliation_on_profile": profile_summary.get("affiliation_on_profile"),
        "homepage": profile_summary.get("homepage"),
        "jel_codes": profile_summary.get("jel_codes"),
        "works_count": len(works) if profile_summary.get("refs_handle") else None,
        "coauthors": extract_coauthors(works, manifest_row),
        "citec_url": citec_url,
        "citec_h_index": citec_h_index,
        "citec_cited_by_count": citec_cited_by_count,
    }
    record["top_papers"] = top_papers[:MAX_TOP_PAPERS]
    record["disambiguation_notes"] = "; ".join(notes)
    return record


def build_not_found_record(node_id: str, confidence: str, notes: list[str]) -> dict[str, Any]:
    record = empty_enrichment_record(node_id)
    record["lookup_status"] = "not_found"
    record["confidence"] = confidence
    record["disambiguation_notes"] = "; ".join(notes)
    return record


def build_candidate_review_record(node_id: str, candidate: dict[str, Any], notes: list[str]) -> dict[str, Any]:
    profile_summary = candidate["profile_summary"]
    record = empty_enrichment_record(node_id)
    record["lookup_status"] = "ambiguous"
    record["confidence"] = "low"
    record["review_status"] = "candidate_review"
    record["repec"] = {
        "url": profile_summary.get("url"),
        "handle": profile_summary.get("handle"),
        "name_on_profile": profile_summary.get("name_on_profile"),
        "affiliation_on_profile": profile_summary.get("affiliation_on_profile"),
        "homepage": profile_summary.get("homepage"),
        "jel_codes": profile_summary.get("jel_codes"),
        "works_count": None,
        "coauthors": None,
        "citec_url": None,
        "citec_h_index": None,
        "citec_cited_by_count": None,
    }
    record["disambiguation_notes"] = "; ".join(notes)
    return record


def append_candidate_handle(
    discovered: list[dict[str, str]],
    seen: set[str],
    handle: str,
    *,
    source: str,
    query: str,
) -> None:
    if not handle or handle in seen:
        return
    seen.add(handle)
    discovered.append({"handle": handle, "source": source, "query": query})


def discover_candidate_handles(
    client: RePEcClient,
    manifest_row: dict[str, Any],
    notes: list[str],
    *,
    robustness: bool = False,
) -> tuple[list[dict[str, str]], str, list[str]]:
    override_handle = normalize_handle(manifest_row.get("repec_handle_override"))
    if override_handle:
        notes.append(f"override_handle={override_handle}")
        return [{"handle": override_handle, "source": "override", "query": override_handle}], override_handle, [override_handle]

    discovered: list[dict[str, str]] = []
    seen_handles: set[str] = set()
    queries = discovery_queries(manifest_row, robustness=robustness)
    for query in queries:
        direct_handle = normalize_handle(query)
        if direct_handle:
            append_candidate_handle(discovered, seen_handles, direct_handle, source="query_handle", query=query)
            notes.append(f"query_handle={direct_handle}")
            break

        try:
            author_search_response = client.request(
                "post",
                IDEAS_AUTHOR_SEARCH,
                data={
                    "q": query,
                    "wf": "000F",
                    "wm": "wrd",
                    "dt": "range",
                    "ul": "",
                },
            )
        except requests.RequestException as exc:
            notes.append(f"author_search:{query} error={exc}")
            author_search_response = None
        if author_search_response is not None:
            notes.append(f"author_search:{query} status={author_search_response.status_code}")
            if author_search_response.status_code == 200:
                handles = extract_candidate_handles(author_search_response.text)
                for handle in handles:
                    append_candidate_handle(discovered, seen_handles, handle, source="author_search", query=query)
                if discovered:
                    notes.append(f"author_search_handles={','.join(item['handle'] for item in discovered)}")
                    break

        browse_url = IDEAS_BROWSE.format(query=quote_plus(query))
        try:
            browse_response = client.request("get", browse_url)
        except requests.RequestException as exc:
            notes.append(f"browse:{query} error={exc}")
            browse_response = None
        if browse_response is None:
            continue
        notes.append(f"browse:{query} status={browse_response.status_code}")
        if browse_response.status_code == 200:
            handles = extract_candidate_handles(browse_response.text)
            for handle in handles:
                append_candidate_handle(discovered, seen_handles, handle, source="browse", query=query)
            if discovered:
                notes.append(f"browse_handles={','.join(item['handle'] for item in discovered)}")
                break

        search_url = IDEAS_SEARCH.format(query=quote_plus(query))
        try:
            search_response = client.request("get", search_url)
        except requests.RequestException as exc:
            notes.append(f"search:{query} error={exc}")
            search_response = None
        if search_response is None:
            continue
        notes.append(f"search:{query} status={search_response.status_code}")
        if search_response.status_code == 200:
            handles = extract_candidate_handles(search_response.text)
            for handle in handles:
                append_candidate_handle(discovered, seen_handles, handle, source="search", query=query)
            if discovered:
                notes.append(f"search_handles={','.join(item['handle'] for item in discovered)}")
                break
    return discovered, override_handle, queries


def build_ambiguous_record(
    node_id: str,
    candidate: dict[str, Any],
    notes: list[str],
    *,
    review_status: str = "none",
) -> dict[str, Any]:
    profile_summary = candidate["profile_summary"]
    record = empty_enrichment_record(node_id)
    record["lookup_status"] = "ambiguous"
    record["confidence"] = "low"
    record["review_status"] = review_status
    record["repec"] = {
        "url": profile_summary.get("url"),
        "handle": profile_summary.get("handle"),
        "name_on_profile": profile_summary.get("name_on_profile"),
        "affiliation_on_profile": profile_summary.get("affiliation_on_profile"),
        "homepage": profile_summary.get("homepage"),
        "jel_codes": profile_summary.get("jel_codes"),
        "works_count": None,
        "coauthors": None,
        "citec_url": None,
        "citec_h_index": None,
        "citec_cited_by_count": None,
    }
    record["disambiguation_notes"] = "; ".join(notes)
    return record


def build_review_row(
    manifest_row: dict[str, Any],
    prior_record: dict[str, Any] | None,
    enrichment: dict[str, Any],
    queries: list[str],
    candidate_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    def join_unique(values: list[str]) -> str:
        deduped = dedupe_query_values(values)
        return " | ".join(deduped)

    candidate_handles = [str(item.get("handle") or "") for item in candidate_entries if item.get("handle")]
    candidate_names = [
        str((item.get("profile_summary") or {}).get("name_on_profile") or "")
        for item in candidate_entries
        if item.get("profile_summary")
    ]
    candidate_affiliations = [
        str((item.get("profile_summary") or {}).get("affiliation_on_profile") or "")
        for item in candidate_entries
        if item.get("profile_summary")
    ]
    candidate_urls = [
        str((item.get("profile_summary") or {}).get("url") or "")
        for item in candidate_entries
        if item.get("profile_summary")
    ]
    candidate_scores = [
        f"{item.get('handle')}:{item.get('strict_level')}:{item.get('review_score', 0.0):.2f}"
        for item in candidate_entries
        if item.get("handle")
    ]

    review_status = str(enrichment.get("review_status") or "none")
    recommended_action = "true_missing"
    if review_status == "candidate_review":
        best_score = max((float(item.get("review_score") or 0.0) for item in candidate_entries), default=0.0)
        recommended_action = "safe_accept" if best_score >= 0.90 else "manual_override"

    return {
        "node_id": str(manifest_row.get("node_id") or ""),
        "full_name": str(manifest_row.get("full_name") or ""),
        "first_pass_status": str((prior_record or {}).get("lookup_status") or ""),
        "first_pass_confidence": str((prior_record or {}).get("confidence") or ""),
        "second_pass_status": str(enrichment.get("lookup_status") or ""),
        "second_pass_confidence": str(enrichment.get("confidence") or ""),
        "review_status": review_status,
        "recommended_action": recommended_action,
        "queries_tried": " | ".join(queries),
        "candidate_handles": join_unique(candidate_handles),
        "candidate_profile_names": join_unique(candidate_names),
        "candidate_affiliations": join_unique(candidate_affiliations),
        "candidate_urls": join_unique(candidate_urls),
        "candidate_scores": " | ".join(candidate_scores),
        "notes": str(enrichment.get("disambiguation_notes") or ""),
    }


def lookup_repec(
    client: RePEcClient,
    manifest_row: dict[str, Any],
    *,
    robustness: bool = False,
    prior_record: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    node_id = manifest_row["node_id"]
    notes: list[str] = []
    handle_candidates, override_handle, queries = discover_candidate_handles(client, manifest_row, notes, robustness=robustness)
    candidate_entries: list[dict[str, Any]] = []

    if not handle_candidates:
        record = build_not_found_record(node_id, "medium", notes + ["no_candidate_handles"])
        review_row = build_review_row(manifest_row, prior_record, record, queries, candidate_entries) if robustness else None
        return record, review_row

    high_matches: list[tuple[str, float, dict[str, Any], str]] = []
    medium_matches: list[tuple[str, float, dict[str, Any], str]] = []
    review_matches: list[dict[str, Any]] = []

    for candidate_meta in handle_candidates[:MAX_CANDIDATE_HANDLES]:
        handle = candidate_meta["handle"]
        profile_summary, profile_html = fetch_ideas_profile(client, handle, notes)
        if profile_summary is None or profile_html is None:
            candidate_entries.append(
                {
                    **candidate_meta,
                    "strict_level": "fetch_failed",
                    "review_score": 0.0,
                }
            )
            continue

        level, aff_score = evaluate_candidate(manifest_row, handle, profile_summary, override_handle)
        review_score = 0.0
        review_reason = "not_applicable"
        if robustness and level == "reject":
            review_score, review_reason = review_candidate_score(manifest_row, profile_summary, candidate_meta)

        entry = {
            **candidate_meta,
            "profile_summary": profile_summary,
            "profile_html": profile_html,
            "strict_level": level,
            "aff_score": aff_score,
            "review_score": review_score,
            "review_reason": review_reason,
        }
        candidate_entries.append(entry)
        notes.append(
            f"candidate:{handle} source={candidate_meta.get('source')} query={candidate_meta.get('query')} "
            f"level={level} aff_score={aff_score:.2f}"
        )
        if level == "reject":
            if robustness:
                notes.append(f"candidate_review:{handle} score={review_score:.2f} reason={review_reason}")
                if review_score >= 0.75:
                    review_matches.append(entry)
            continue
        match_entry = (handle, aff_score, profile_summary, profile_html)
        if level == "high":
            high_matches.append(match_entry)
        else:
            medium_matches.append(match_entry)

    if len(high_matches) > 1 or (not high_matches and len(medium_matches) > 1):
        matches = high_matches or medium_matches
        candidate = next(item for item in candidate_entries if item.get("handle") == matches[0][0])
        record = build_ambiguous_record(
            node_id,
            candidate,
            notes + [f"ambiguous_candidates={','.join(match[0] for match in matches)}"],
            review_status="candidate_review" if robustness else "none",
        )
        review_row = build_review_row(manifest_row, prior_record, record, queries, candidate_entries) if robustness else None
        return record, review_row

    chosen = high_matches[0] if high_matches else (medium_matches[0] if medium_matches else None)
    if chosen is None:
        if robustness and review_matches:
            review_matches.sort(key=lambda item: (float(item.get("review_score") or 0.0), float(item.get("aff_score") or 0.0)), reverse=True)
            selected_review = review_matches[0]
            notes.append(f"review_candidates={','.join(item['handle'] for item in review_matches)}")
            notes.append(
                f"selected_review_handle={selected_review['handle']} "
                f"score={float(selected_review.get('review_score') or 0.0):.2f}"
            )
            record = build_candidate_review_record(node_id, selected_review, notes)
            review_row = build_review_row(manifest_row, prior_record, record, queries, candidate_entries)
            return record, review_row

        record = build_not_found_record(node_id, "medium", notes + ["candidate_profiles_failed_matching"])
        review_row = build_review_row(manifest_row, prior_record, record, queries, candidate_entries) if robustness else None
        return record, review_row

    handle, _, profile_summary, _ = chosen
    works = fetch_works_export(client, profile_summary.get("refs_handle"), notes)
    citec_url, citec_h_index, citec_cited_by_count, top_papers = fetch_citec_profile(client, profile_summary, notes)
    confidence = "high" if high_matches else "medium"
    notes.append(f"selected_handle={handle}")
    notes.append(f"confidence={confidence}")

    record = build_enrichment(
        node_id=node_id,
        profile_summary=profile_summary,
        works=works,
        citec_url=citec_url,
        citec_h_index=citec_h_index,
        citec_cited_by_count=citec_cited_by_count,
        top_papers=top_papers,
        confidence=confidence,
        notes=notes,
        manifest_row=manifest_row,
        review_status="override_applied" if override_handle and handle == override_handle else "none",
    )
    return record, None


def load_prior_lookup(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    rows = load_jsonl(path)
    return {(row.get("node_id") or "").strip(): row for row in rows if (row.get("node_id") or "").strip()}


def should_process_manifest_row(manifest_row: dict[str, Any], prior_lookup: dict[str, dict[str, Any]]) -> bool:
    if not prior_lookup:
        return True
    node_id = str(manifest_row.get("node_id") or "").strip()
    prior = prior_lookup.get(node_id)
    if prior is None:
        return True
    status = str(prior.get("lookup_status") or "")
    notes = str(prior.get("disambiguation_notes") or "")
    review_status = str(prior.get("review_status") or "none")
    return status in {"not_found", "ambiguous"} or review_status == "candidate_review" or "candidate_profiles_failed_matching" in notes


def main() -> None:
    args = parse_args()
    if not REQUESTS_AVAILABLE:
        print("requests/beautifulsoup4 are not installed. Run: pip install requests beautifulsoup4", file=sys.stderr)
        sys.exit(1)
    manifest_path = resolve(args.manifest)
    output_path = resolve(args.output)
    prior_path = resolve(args.prior_enrichment) if args.prior_enrichment else None
    review_output_path = resolve(args.review_output) if args.review_output else None
    override_csv_path = resolve(args.override_csv) if args.override_csv else None
    manifest_rows = load_jsonl(manifest_path)
    node_id_filter = {item.strip() for item in (args.node_ids or "").split(",") if item.strip()}
    prior_lookup = load_prior_lookup(prior_path)
    override_map = load_override_map(override_csv_path) if override_csv_path else {}

    for manifest_row in manifest_rows:
        node_id = str(manifest_row.get("node_id") or "").strip()
        if node_id in override_map:
            manifest_row["repec_handle_override"] = override_map[node_id]

    client = RePEcClient(args.delay)
    results: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    processed = 0

    for manifest_row in manifest_rows:
        node_id = (manifest_row.get("node_id") or "").strip()
        if not node_id:
            continue
        if node_id_filter and node_id not in node_id_filter:
            continue
        if not should_process_manifest_row(manifest_row, prior_lookup):
            continue
        if args.limit is not None and processed >= args.limit:
            break

        print(f"[{processed + 1}] {node_id} — {manifest_row.get('full_name', '')}", file=sys.stderr)
        enrichment, review_row = lookup_repec(
            client,
            manifest_row,
            robustness=args.robustness_pass,
            prior_record=prior_lookup.get(node_id),
        )
        errors = validate_enrichment_record(enrichment)
        if errors:
            print(f"  [warn] validation: {'; '.join(errors)}", file=sys.stderr)
        results.append(enrichment)
        if review_row is not None:
            review_rows.append(review_row)
        processed += 1
        review_status = str(enrichment.get("review_status") or "none")
        if review_status != "none":
            print(f"  -> {enrichment.get('lookup_status', '')} ({review_status})", file=sys.stderr)
        else:
            print(f"  -> {enrichment.get('lookup_status', '')}", file=sys.stderr)

    write_jsonl(output_path, results)
    if review_output_path is not None:
        write_review_rows(review_output_path, review_rows)

    print(f"\nProcessed:  {processed}", file=sys.stderr)
    print(f"Output:     {output_path}", file=sys.stderr)
    if review_output_path is not None:
        print(f"Review:     {review_output_path}", file=sys.stderr)
    status_counts: dict[str, int] = {}
    for row in results:
        status = str(row.get("lookup_status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
    for status in ("found", "not_found", "ambiguous"):
        if status in status_counts:
            print(f"  {status}: {status_counts[status]}", file=sys.stderr)


if __name__ == "__main__":
    main()
