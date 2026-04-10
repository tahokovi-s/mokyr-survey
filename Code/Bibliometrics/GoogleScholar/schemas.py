from __future__ import annotations

from copy import deepcopy
from typing import Any


MANIFEST_REQUIRED_FIELDS = [
    "node_id",
    "first_name",
    "last_name",
    "full_name",
    "generation",
    "advisor",
    "phd_institution",
    "phd_year",
    "current_employer",
    "search_queries",
]

ENRICHMENT_REQUIRED_FIELDS = [
    "node_id",
    "lookup_status",
    "confidence",
    "disambiguation_notes",
]

LOOKUP_STATUS_VALUES = {"found", "not_found", "ambiguous"}
CONFIDENCE_VALUES = {"high", "medium", "low"}
MAX_TOP_PAPERS = 5

GS_PANEL_FIELDS = [
    "gs_lookup_status",
    "gs_confidence",
    "gs_url",
    "gs_name_on_profile",
    "gs_affiliation",
    "gs_interests",
    "gs_works_count",
    "gs_cited_by_count",
    "gs_h_index",
    "gs_i10_index",
    "gs_most_cited_title",
    "gs_most_cited_year",
    "gs_most_cited_citations",
    "gs_most_cited_venue",
    "gs_personal_website",
    "gs_self_described_field",
    "gs_enrichment_status",
]

BEST_PANEL_FIELDS = [
    "best_field",
    "best_h_index",
    "best_citations",
]

_GOOGLE_SCHOLAR_NUMERIC_FIELDS = [
    "works_count",
    "cited_by_count",
    "h_index",
    "i10_index",
]

_TOP_PAPER_NUMERIC_FIELDS = [
    "year",
    "citations",
]


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _ensure_string_list(value: Any, field_name: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{field_name} must be a list of strings")
        return []

    cleaned: list[str] = []
    for index, item in enumerate(value):
        if item is None:
            continue
        text = _normalize_string(item)
        if not text:
            continue
        if not isinstance(item, str):
            errors.append(f"{field_name}[{index}] must be a string")
            continue
        cleaned.append(text)
    return cleaned


def _coerce_optional_int(container: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = container.get(key)
    if value is None or value == "":
        container[key] = None
        return
    if isinstance(value, bool):
        errors.append(f"{path} must be an integer or null")
        return
    if isinstance(value, int):
        return
    if isinstance(value, str):
        text = value.strip()
        if not text:
            container[key] = None
            return
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            container[key] = int(text)
            return
    errors.append(f"{path} must be an integer or null")


def _validate_top_paper(paper: Any, index: int, errors: list[str]) -> dict[str, Any]:
    if not isinstance(paper, dict):
        errors.append(f"top_papers[{index}] must be an object")
        return {"title": "", "year": None, "citations": None, "venue": ""}

    normalized = {
        "title": _normalize_string(paper.get("title")),
        "year": paper.get("year"),
        "citations": paper.get("citations"),
        "venue": _normalize_string(paper.get("venue")),
    }

    if not normalized["title"]:
        errors.append(f"top_papers[{index}].title is required")

    for key in _TOP_PAPER_NUMERIC_FIELDS:
        _coerce_optional_int(normalized, key, f"top_papers[{index}].{key}", errors)
    return normalized


def validate_manifest_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in MANIFEST_REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"missing required field: {field}")

    node_id = _normalize_string(record.get("node_id"))
    full_name = _normalize_string(record.get("full_name"))
    if not node_id:
        errors.append("node_id must be non-empty")
    if not full_name:
        errors.append("full_name must be non-empty")

    search_queries = record.get("search_queries")
    if not isinstance(search_queries, list):
        errors.append("search_queries must be a list of strings")
    else:
        cleaned_queries: list[str] = []
        for index, item in enumerate(search_queries):
            if not isinstance(item, str):
                errors.append(f"search_queries[{index}] must be a string")
                continue
            text = item.strip()
            if text:
                cleaned_queries.append(text)
        if not cleaned_queries:
            errors.append("search_queries must contain at least one non-empty query")
        else:
            record["search_queries"] = cleaned_queries

    for field in ("first_name", "last_name", "generation", "advisor", "phd_institution", "phd_year", "current_employer"):
        if field in record and record[field] is not None and not isinstance(record[field], str):
            record[field] = _normalize_string(record[field])
    if "node_id" in record:
        record["node_id"] = node_id
    if "full_name" in record:
        record["full_name"] = full_name
    return errors


def empty_enrichment_record(node_id: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "lookup_status": "",
        "confidence": "",
        "google_scholar": None,
        "personal_website": None,
        "top_papers": [],
        "disambiguation_notes": "",
    }


def example_enrichment_record() -> dict[str, Any]:
    return {
        "node_id": "R-R_xxx",
        "lookup_status": "found",
        "confidence": "high",
        "google_scholar": {
            "url": "https://scholar.google.com/citations?user=xxx",
            "name_on_profile": "Ariell Zimran",
            "affiliation_on_profile": "Vanderbilt University",
            "interests": ["Economic History", "Labor Economics", "Immigration"],
            "works_count": 36,
            "cited_by_count": 1200,
            "h_index": 9,
            "i10_index": 7,
            "coauthors": ["Ran Abramitzky", "Leah Boustan"],
        },
        "personal_website": {
            "url": "https://ariellzimran.com",
            "self_described_field": "Economic History",
        },
        "top_papers": [
            {"title": "Immigration and the...", "year": 2020, "citations": 150, "venue": "AER"},
            {"title": "Another paper...", "year": 2018, "citations": 90, "venue": "JEH"},
        ],
        "disambiguation_notes": "Matched by institution (Vanderbilt) + research interests (Economic History)",
    }


def validate_enrichment_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ENRICHMENT_REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"missing required field: {field}")

    node_id = _normalize_string(record.get("node_id"))
    if not node_id:
        errors.append("node_id must be non-empty")
    else:
        record["node_id"] = node_id

    lookup_status = _normalize_string(record.get("lookup_status"))
    if lookup_status not in LOOKUP_STATUS_VALUES:
        errors.append(f"lookup_status must be one of: {', '.join(sorted(LOOKUP_STATUS_VALUES))}")
    else:
        record["lookup_status"] = lookup_status

    confidence = _normalize_string(record.get("confidence")).lower()
    if confidence not in CONFIDENCE_VALUES:
        errors.append(f"confidence must be one of: {', '.join(sorted(CONFIDENCE_VALUES))}")
    else:
        record["confidence"] = confidence

    disambiguation_notes = _normalize_string(record.get("disambiguation_notes"))
    if not disambiguation_notes:
        errors.append("disambiguation_notes is required")
    else:
        record["disambiguation_notes"] = disambiguation_notes

    google_scholar = record.get("google_scholar")
    if google_scholar is not None and not isinstance(google_scholar, dict):
        errors.append("google_scholar must be an object or null")
        google_scholar = None
    if google_scholar is not None:
        normalized_google_scholar = {
            "url": _normalize_string(google_scholar.get("url")),
            "name_on_profile": _normalize_string(google_scholar.get("name_on_profile")),
            "affiliation_on_profile": _normalize_string(google_scholar.get("affiliation_on_profile")),
            "interests": google_scholar.get("interests"),
            "works_count": google_scholar.get("works_count"),
            "cited_by_count": google_scholar.get("cited_by_count"),
            "h_index": google_scholar.get("h_index"),
            "i10_index": google_scholar.get("i10_index"),
        }
        interests = _ensure_string_list(normalized_google_scholar.get("interests"), "google_scholar.interests", errors)
        normalized_google_scholar["interests"] = interests
        for key in _GOOGLE_SCHOLAR_NUMERIC_FIELDS:
            _coerce_optional_int(normalized_google_scholar, key, f"google_scholar.{key}", errors)
        if "coauthors" in google_scholar:
            normalized_google_scholar["coauthors"] = _ensure_string_list(
                google_scholar.get("coauthors"),
                "google_scholar.coauthors",
                errors,
            )
        record["google_scholar"] = normalized_google_scholar
        google_scholar = normalized_google_scholar
    else:
        record["google_scholar"] = None

    personal_website = record.get("personal_website")
    if personal_website is None:
        record["personal_website"] = None
    elif not isinstance(personal_website, dict):
        errors.append("personal_website must be an object or null")
        record["personal_website"] = None
    else:
        record["personal_website"] = {
            "url": _normalize_string(personal_website.get("url")),
            "self_described_field": _normalize_string(personal_website.get("self_described_field")),
        }

    top_papers = record.get("top_papers", [])
    if top_papers is None:
        top_papers = []
    if not isinstance(top_papers, list):
        errors.append("top_papers must be a list")
        normalized_top_papers: list[dict[str, Any]] = []
    else:
        normalized_top_papers = [_validate_top_paper(paper, index, errors) for index, paper in enumerate(top_papers)]
        if len(normalized_top_papers) > MAX_TOP_PAPERS:
            errors.append(f"top_papers cannot contain more than {MAX_TOP_PAPERS} entries")
            normalized_top_papers = normalized_top_papers[:MAX_TOP_PAPERS]
    record["top_papers"] = normalized_top_papers

    if lookup_status == "found":
        if google_scholar is None:
            errors.append("google_scholar is required when lookup_status is found")
        elif not google_scholar.get("url"):
            errors.append("google_scholar.url is required when lookup_status is found")
    elif lookup_status == "not_found":
        if google_scholar is not None:
            errors.append("google_scholar must be null or omitted when lookup_status is not_found")
        if normalized_top_papers:
            errors.append("top_papers must be empty or omitted when lookup_status is not_found")
    elif lookup_status == "ambiguous":
        if google_scholar is not None and not google_scholar.get("url"):
            errors.append("google_scholar.url is required when google_scholar is provided for ambiguous matches")

    return errors


def canonical_example_enrichment_record() -> dict[str, Any]:
    return deepcopy(example_enrichment_record())
