#!/usr/bin/env python3
"""Shared helpers for the OpenAlex manual-review pipeline."""

from __future__ import annotations

import getpass
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Bibliometrics.build_openalex_panel import (
    PROJECT_ROOT,
    VALID_MANUAL_DECISIONS,
    latest_path,
    load_csv,
    load_manual_decisions,
    manual_selected_openalex_id,
    parse_mmddyy,
    resolve_path,
    write_csv,
)


MATCHES_PATTERN = re.compile(r"^OpenAlex_Scholar_Matches_(\d{6})\.csv$")
REVIEW_PATTERN = re.compile(r"^OpenAlex_Match_Review_(\d{6})\.csv$")
TOP_PAPERS_PATTERN = re.compile(r"^OpenAlex_Top_Papers_(\d{6})\.csv$")
ALL_DECISIONS_PATTERN = re.compile(r"^OpenAlex_All_Decisions_(\d{6})\.csv$")
DATE_TOKEN_PATTERN = re.compile(r"(?:^|_)(\d{6})(?:_|\.|$)")
DECISION_FIELDNAMES = [
    "node_id",
    "full_name",
    "current_openalex_id",
    "proposed_openalex_id",
    "decision",
    "reason",
    "reviewer",
]
APPROVE_ACTION = "approve_selected"
REJECT_ACTION = "no_match"
DEFER_ACTION = "defer"


@dataclass(frozen=True)
class SnapshotPaths:
    date_token: str
    matches_path: Path
    review_path: Path
    top_papers_path: Path | None
    all_decisions_path: Path | None


@dataclass
class ReviewSnapshot:
    paths: SnapshotPaths
    matches_rows: list[dict[str, str]]
    review_rows: list[dict[str, str]]
    top_papers_rows: list[dict[str, str]]

    def __post_init__(self) -> None:
        self.matches_by_node = {
            (row.get("node_id", "") or "").strip(): row for row in self.matches_rows
        }

        review_by_node: dict[str, list[dict[str, str]]] = defaultdict(list)
        review_by_node_candidate: dict[tuple[str, str], dict[str, str]] = {}
        for row in self.review_rows:
            node_id = (row.get("node_id", "") or "").strip()
            candidate_id = normalize_openalex_id(row.get("candidate_openalex_id", ""))
            review_by_node[node_id].append(row)
            if node_id and candidate_id:
                review_by_node_candidate[(node_id, candidate_id)] = row
        for rows in review_by_node.values():
            rows.sort(key=lambda row: safe_int(row.get("candidate_rank", "")) or 999)
        self.review_by_node = review_by_node
        self.review_by_node_candidate = review_by_node_candidate

        top_papers_by_node: dict[str, list[dict[str, str]]] = defaultdict(list)
        top_papers_by_node_author: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in self.top_papers_rows:
            node_id = (row.get("node_id", "") or "").strip()
            author_id = normalize_openalex_id(row.get("openalex_author_id", ""))
            top_papers_by_node[node_id].append(row)
            if node_id and author_id:
                top_papers_by_node_author[(node_id, author_id)].append(row)
        for rows in top_papers_by_node.values():
            rows.sort(key=lambda row: safe_int(row.get("paper_rank", "")) or 999)
        for rows in top_papers_by_node_author.values():
            rows.sort(key=lambda row: safe_int(row.get("paper_rank", "")) or 999)
        self.top_papers_by_node = top_papers_by_node
        self.top_papers_by_node_author = top_papers_by_node_author


def ensure_date_token(token: str) -> str:
    parse_mmddyy(token)
    return token


def extract_date_token(name: str) -> str | None:
    match = DATE_TOKEN_PATTERN.search(name)
    if not match:
        return None
    return ensure_date_token(match.group(1))


def lock_date_token(
    explicit_date: str | None = None,
    *raw_paths: str | Path | None,
    fallback_pattern: re.Pattern[str] = MATCHES_PATTERN,
) -> str:
    if explicit_date:
        return ensure_date_token(explicit_date)

    inferred: str | None = None
    for raw_path in raw_paths:
        if not raw_path:
            continue
        token = extract_date_token(Path(raw_path).name)
        if not token:
            continue
        if inferred and inferred != token:
            raise ValueError(
                f"Conflicting date tokens inferred from inputs: {inferred} vs {token}."
            )
        inferred = token

    if inferred:
        return inferred

    fallback_path = latest_path(fallback_pattern)
    fallback_token = extract_date_token(fallback_path.name)
    if not fallback_token:
        raise ValueError(f"Could not infer date token from {fallback_path.name}.")
    return fallback_token


def validate_path_date(path: Path, date_token: str) -> None:
    token = extract_date_token(path.name)
    if token and token != date_token:
        raise ValueError(
            f"Path {path} is for date {token}, but the locked review snapshot date is {date_token}."
        )


def resolve_required_snapshot_path(
    raw_path: str | None,
    default_name: str,
    date_token: str,
) -> Path:
    default_path = PROJECT_ROOT / "Data" / "Derived" / default_name
    path = resolve_path(raw_path, default_path)
    validate_path_date(path, date_token)
    if not path.exists():
        raise FileNotFoundError(f"Required snapshot file not found: {path}")
    return path


def resolve_optional_snapshot_path(
    raw_path: str | None,
    default_name: str,
    date_token: str,
) -> Path | None:
    if raw_path:
        path = resolve_path(raw_path)
        validate_path_date(path, date_token)
        if not path.exists():
            raise FileNotFoundError(f"Optional snapshot file was requested but not found: {path}")
        return path

    default_path = PROJECT_ROOT / "Data" / "Derived" / default_name
    if default_path.exists():
        return default_path
    return None


def resolve_snapshot_paths(
    *,
    date_token: str | None = None,
    matches_path: str | None = None,
    review_path: str | None = None,
    top_papers_path: str | None = None,
    all_decisions_path: str | None = None,
) -> SnapshotPaths:
    locked_date = lock_date_token(
        date_token,
        matches_path,
        review_path,
        top_papers_path,
        all_decisions_path,
    )

    matches = resolve_required_snapshot_path(
        matches_path,
        f"OpenAlex_Scholar_Matches_{locked_date}.csv",
        locked_date,
    )
    review = resolve_required_snapshot_path(
        review_path,
        f"OpenAlex_Match_Review_{locked_date}.csv",
        locked_date,
    )
    top_papers = resolve_optional_snapshot_path(
        top_papers_path,
        f"OpenAlex_Top_Papers_{locked_date}.csv",
        locked_date,
    )
    all_decisions = resolve_optional_snapshot_path(
        all_decisions_path,
        f"OpenAlex_All_Decisions_{locked_date}.csv",
        locked_date,
    )

    return SnapshotPaths(
        date_token=locked_date,
        matches_path=matches,
        review_path=review,
        top_papers_path=top_papers,
        all_decisions_path=all_decisions,
    )


def load_review_snapshot(
    *,
    date_token: str | None = None,
    matches_path: str | None = None,
    review_path: str | None = None,
    top_papers_path: str | None = None,
    all_decisions_path: str | None = None,
) -> ReviewSnapshot:
    paths = resolve_snapshot_paths(
        date_token=date_token,
        matches_path=matches_path,
        review_path=review_path,
        top_papers_path=top_papers_path,
        all_decisions_path=all_decisions_path,
    )
    top_papers_rows = load_csv(paths.top_papers_path) if paths.top_papers_path else []
    return ReviewSnapshot(
        paths=paths,
        matches_rows=load_csv(paths.matches_path),
        review_rows=load_csv(paths.review_path),
        top_papers_rows=top_papers_rows,
    )


def resolve_existing_all_decisions(
    *,
    date_token: str | None = None,
    decisions_path: str | None = None,
) -> Path:
    locked_date = lock_date_token(date_token, decisions_path, fallback_pattern=ALL_DECISIONS_PATTERN)
    default_path = PROJECT_ROOT / "Data" / "Derived" / f"OpenAlex_All_Decisions_{locked_date}.csv"
    path = resolve_path(decisions_path, default_path)
    validate_path_date(path, locked_date)
    if not path.exists():
        raise FileNotFoundError(f"OpenAlex decisions file not found: {path}")
    return path


def parse_status_list(raw_statuses: str) -> list[str]:
    statuses = [value.strip() for value in (raw_statuses or "").split(",") if value.strip()]
    if not statuses:
        raise ValueError("At least one match status must be provided.")
    return statuses


def filter_matches_by_status(
    snapshot: ReviewSnapshot,
    statuses: list[str],
) -> list[dict[str, str]]:
    return [
        row for row in snapshot.matches_rows if (row.get("match_status", "") or "").strip() in statuses
    ]


def normalize_openalex_id(raw_id: str) -> str:
    value = (raw_id or "").strip()
    if not value:
        return ""
    if value.startswith("https://openalex.org/"):
        return value.rstrip("/")
    return f"https://openalex.org/{value.lstrip('/')}"


def safe_int(raw_value: Any) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def safe_float(raw_value: Any) -> float:
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return 0.0


def split_flags(raw_flags: str) -> list[str]:
    text = (raw_flags or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def default_reviewer() -> str:
    env_user = (Path.home().name or "").strip()
    if env_user:
        return env_user
    try:
        return getpass.getuser() or "manual_reviewer"
    except (OSError, KeyError):
        return "manual_reviewer"


def canonical_decision_for_action(
    *,
    action: str,
    current_openalex_id: str,
    selected_openalex_id: str,
) -> str:
    current_id = normalize_openalex_id(current_openalex_id)
    selected_id = normalize_openalex_id(selected_openalex_id)

    if action == APPROVE_ACTION:
        if not selected_id:
            raise ValueError("Approve Selected requires a selected OpenAlex candidate.")
        if current_id and selected_id == current_id:
            return "keep_match"
        if current_id:
            return "replace_match"
        return "approve_match"
    if action == REJECT_ACTION:
        return "reject_match"
    if action == DEFER_ACTION:
        return "needs_more_review"
    raise ValueError(f"Unsupported reviewer action: {action}")


def proposed_openalex_id_for_action(
    *,
    action: str,
    current_openalex_id: str,
    selected_openalex_id: str,
) -> str:
    current_id = normalize_openalex_id(current_openalex_id)
    selected_id = normalize_openalex_id(selected_openalex_id)

    if action == APPROVE_ACTION:
        return selected_id
    if action == DEFER_ACTION:
        return selected_id or current_id
    return ""


def build_decision_row(
    match_row: dict[str, str],
    *,
    action: str,
    selected_openalex_id: str = "",
    notes: str = "",
    reviewer: str,
) -> dict[str, str]:
    current_id = normalize_openalex_id(match_row.get("openalex_id", ""))
    decision = canonical_decision_for_action(
        action=action,
        current_openalex_id=current_id,
        selected_openalex_id=selected_openalex_id,
    )
    if decision not in VALID_MANUAL_DECISIONS:
        raise ValueError(f"Invalid canonical decision generated: {decision}")

    reason = (notes or "").strip() or (match_row.get("review_notes", "") or "").strip()
    return {
        "node_id": (match_row.get("node_id", "") or "").strip(),
        "full_name": (match_row.get("full_name", "") or "").strip(),
        "current_openalex_id": current_id,
        "proposed_openalex_id": proposed_openalex_id_for_action(
            action=action,
            current_openalex_id=current_id,
            selected_openalex_id=selected_openalex_id,
        ),
        "decision": decision,
        "reason": reason,
        "reviewer": (reviewer or "").strip() or default_reviewer(),
    }


def decision_selected_openalex_id(decision_row: dict[str, str]) -> str:
    return normalize_openalex_id(manual_selected_openalex_id(decision_row))


def validate_decision_rows(rows: list[dict[str, str]]) -> None:
    by_node: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows, start=2):
        node_id = (row.get("node_id", "") or "").strip()
        if not node_id:
            raise ValueError(f"Decision row {index} is missing node_id.")
        if node_id in by_node:
            raise ValueError(f"Decision rows contain duplicate node_id {node_id}.")
        by_node[node_id] = row

        decision = (row.get("decision", "") or "").strip().lower()
        if decision not in VALID_MANUAL_DECISIONS:
            raise ValueError(
                f"Decision row {index} has unsupported decision {row.get('decision', '')!r}."
            )

        current_id = normalize_openalex_id(row.get("current_openalex_id", ""))
        proposed_id = normalize_openalex_id(row.get("proposed_openalex_id", ""))
        row["current_openalex_id"] = current_id
        row["proposed_openalex_id"] = proposed_id
        row["decision"] = decision

        if decision in {"approve_match", "replace_match"} and not proposed_id:
            raise ValueError(
                f"Decision row {index} for {node_id} needs proposed_openalex_id for {decision}."
            )
        if decision == "keep_match" and not (current_id or proposed_id):
            raise ValueError(
                f"Decision row {index} for {node_id} needs current_openalex_id or proposed_openalex_id."
            )


def write_decisions_csv(path: Path, rows: list[dict[str, str]]) -> None:
    validate_decision_rows(rows)
    write_csv(path, DECISION_FIELDNAMES, rows)


def top_papers_for_node_author(
    snapshot: ReviewSnapshot,
    *,
    node_id: str,
    openalex_id: str,
) -> list[dict[str, str]]:
    normalized_id = normalize_openalex_id(openalex_id)
    if not normalized_id:
        return []
    return list(snapshot.top_papers_by_node_author.get((node_id, normalized_id), []))


def summarize_top_papers(rows: list[dict[str, str]], *, limit: int = 3) -> str:
    parts: list[str] = []
    for row in rows[:limit]:
        title = (row.get("title", "") or "").strip()
        year = (row.get("publication_year", "") or "").strip()
        cites = (row.get("cited_by_count", "") or "").strip()
        if not title:
            continue
        bit = title
        if year:
            bit += f" ({year})"
        if cites:
            bit += f", cites={cites}"
        parts.append(bit)
    return "; ".join(parts)


def read_decisions_csv(path: Path) -> list[dict[str, str]]:
    rows = load_csv(path)
    validate_decision_rows(rows)
    return rows


__all__ = [
    "ALL_DECISIONS_PATTERN",
    "APPROVE_ACTION",
    "DECISION_FIELDNAMES",
    "DEFER_ACTION",
    "MATCHES_PATTERN",
    "PROJECT_ROOT",
    "REJECT_ACTION",
    "REVIEW_PATTERN",
    "ReviewSnapshot",
    "SnapshotPaths",
    "TOP_PAPERS_PATTERN",
    "build_decision_row",
    "decision_selected_openalex_id",
    "default_reviewer",
    "extract_date_token",
    "filter_matches_by_status",
    "load_manual_decisions",
    "load_review_snapshot",
    "lock_date_token",
    "normalize_openalex_id",
    "parse_status_list",
    "resolve_existing_all_decisions",
    "safe_float",
    "safe_int",
    "split_flags",
    "summarize_top_papers",
    "top_papers_for_node_author",
    "validate_decision_rows",
    "write_csv",
    "write_decisions_csv",
]
