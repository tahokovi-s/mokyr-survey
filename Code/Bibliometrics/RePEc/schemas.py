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
REVIEW_STATUS_VALUES = {"none", "candidate_review", "override_applied"}
MAX_TOP_PAPERS = 5

REPEC_PANEL_FIELDS = [
    "repec_lookup_status",
    "repec_confidence",
    "repec_url",
    "repec_handle",
    "repec_name_on_profile",
    "repec_affiliation",
    "repec_homepage",
    "repec_jel_codes",
    "repec_works_count",
    "repec_citec_url",
    "repec_citec_h_index",
    "repec_citec_cited_by_count",
    "repec_most_cited_title",
    "repec_most_cited_year",
    "repec_most_cited_citations",
    "repec_most_cited_venue",
    "repec_enrichment_status",
]

_REPEC_NUMERIC_FIELDS = [
    "works_count",
    "citec_h_index",
    "citec_cited_by_count",
]

_TOP_PAPER_NUMERIC_FIELDS = [
    "year",
    "citations",
]


def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_optional_string(value: Any) -> str | None:
    text = _normalize_string(value)
    return text or None


def _ensure_optional_string_list(value: Any, field_name: str, errors: list[str]) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        errors.append(f"{field_name} must be a list of strings or null")
        return None

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
        return {"title": None, "year": None, "citations": None, "venue": None}

    normalized = {
        "title": _normalize_optional_string(paper.get("title")),
        "year": paper.get("year"),
        "citations": paper.get("citations"),
        "venue": _normalize_optional_string(paper.get("venue")),
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

    for field in (
        "first_name",
        "last_name",
        "generation",
        "advisor",
        "phd_institution",
        "phd_year",
        "current_employer",
        "repec_handle_override",
    ):
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
        "review_status": "none",
        "repec": None,
        "top_papers": [],
        "disambiguation_notes": "",
    }


def example_enrichment_record() -> dict[str, Any]:
    return {
        "node_id": "R-R_xxx",
        "lookup_status": "found",
        "confidence": "high",
        "review_status": "none",
        "repec": {
            "url": "https://ideas.repec.org/e/pgr24.html",
            "handle": "pgr24",
            "name_on_profile": "Avner Greif",
            "affiliation_on_profile": "Department of Economics, Stanford University",
            "homepage": "https://economics.stanford.edu/",
            "jel_codes": None,
            "works_count": 75,
            "coauthors": ["Joel Mokyr", "Guido Tabellini"],
            "citec_url": "https://citec.repec.org/p/g/pgr24.html",
            "citec_h_index": 22,
            "citec_cited_by_count": 4997,
        },
        "top_papers": [
            {
                "title": "Contract Enforceability and Economic Institutions in Early Trade: the Maghribi Traders Coalition.",
                "year": 1993,
                "citations": 1149,
                "venue": "American Economic Review",
            }
        ],
        "disambiguation_notes": "Matched direct IDEAS profile pgr24 by name + Stanford affiliation.",
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

    review_status = _normalize_string(record.get("review_status") or "none").lower()
    if review_status not in REVIEW_STATUS_VALUES:
        errors.append(f"review_status must be one of: {', '.join(sorted(REVIEW_STATUS_VALUES))}")
    else:
        record["review_status"] = review_status

    disambiguation_notes = _normalize_string(record.get("disambiguation_notes"))
    if not disambiguation_notes:
        errors.append("disambiguation_notes is required")
    else:
        record["disambiguation_notes"] = disambiguation_notes

    repec = record.get("repec")
    if repec is not None and not isinstance(repec, dict):
        errors.append("repec must be an object or null")
        repec = None
    if repec is not None:
        normalized_repec = {
            "url": _normalize_optional_string(repec.get("url")),
            "handle": _normalize_optional_string(repec.get("handle")),
            "name_on_profile": _normalize_optional_string(repec.get("name_on_profile")),
            "affiliation_on_profile": _normalize_optional_string(repec.get("affiliation_on_profile")),
            "homepage": _normalize_optional_string(repec.get("homepage")),
            "jel_codes": _ensure_optional_string_list(repec.get("jel_codes"), "repec.jel_codes", errors),
            "works_count": repec.get("works_count"),
            "coauthors": _ensure_optional_string_list(repec.get("coauthors"), "repec.coauthors", errors),
            "citec_url": _normalize_optional_string(repec.get("citec_url")),
            "citec_h_index": repec.get("citec_h_index"),
            "citec_cited_by_count": repec.get("citec_cited_by_count"),
        }
        for key in _REPEC_NUMERIC_FIELDS:
            _coerce_optional_int(normalized_repec, key, f"repec.{key}", errors)
        record["repec"] = normalized_repec
        repec = normalized_repec
    else:
        record["repec"] = None

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
        if repec is None:
            errors.append("repec is required when lookup_status is found")
        else:
            if not repec.get("url"):
                errors.append("repec.url is required when lookup_status is found")
            if not repec.get("handle"):
                errors.append("repec.handle is required when lookup_status is found")
        if record.get("review_status") == "candidate_review":
            errors.append("review_status candidate_review is not allowed when lookup_status is found")
    elif lookup_status == "not_found":
        if repec is not None:
            errors.append("repec must be null or omitted when lookup_status is not_found")
        if normalized_top_papers:
            errors.append("top_papers must be empty or omitted when lookup_status is not_found")
    elif lookup_status == "ambiguous":
        if repec is not None and not repec.get("url"):
            errors.append("repec.url is required when repec is provided for ambiguous matches")
        if normalized_top_papers:
            errors.append("top_papers must be empty or omitted when lookup_status is ambiguous")

    return errors


def canonical_example_enrichment_record() -> dict[str, Any]:
    return deepcopy(example_enrichment_record())
