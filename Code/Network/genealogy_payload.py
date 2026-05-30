#!/usr/bin/env python3
"""Shared network payload loading for static genealogy outputs."""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

JOEL_PHOTO_URL = "../assets/images/joel-mokyr-168x210.jpg"
HEADSHOT_URL_PREFIX = "../assets/images/headshots"

_NODES_DATE_RE = re.compile(r"^Network_Nodes_(\d{6})\.csv$")
_EDGES_DATE_RE = re.compile(r"^Network_Edges_(\d{6})\.csv$")
_MANIFEST_DATE_RE = re.compile(r"^headshot_manifest_(\d{6})\.json$")

CURATED_RELATIONSHIP_NOTES = {
    "R-R_3uo0fwgoPEZw3Rv": "Co-advisor: Chris Vickers.",
}


def safe_json(obj) -> str:
    """JSON-serialize and escape script-closing tags."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _latest_matching_date(base_dir: Path, pattern: re.Pattern[str]) -> str | None:
    if not base_dir.exists():
        sys.exit(f"ERROR: Expected directory not found while inferring latest date: {base_dir}")
    matches = []
    for path in base_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            matches.append(match.group(1))
    if not matches:
        return None
    return max(matches, key=lambda token: datetime.strptime(token, "%m%d%y"))


def _extract_date_token(path_str: str | None) -> str | None:
    if not path_str:
        return None
    match = re.search(r"(\d{6})", Path(path_str).name)
    return match.group(1) if match else None


def resolve_network_date(date_arg: str | None, nodes_arg: str | None, edges_arg: str | None) -> str:
    if date_arg:
        return date_arg

    explicit_dates = {
        token for token in (
            _extract_date_token(nodes_arg),
            _extract_date_token(edges_arg),
        )
        if token
    }
    if len(explicit_dates) > 1:
        sys.exit(
            "ERROR: --nodes and --edges imply different dates. "
            "Pass --date explicitly or provide aligned inputs."
        )
    if explicit_dates:
        return explicit_dates.pop()

    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    latest_nodes = _latest_matching_date(derived_dir, _NODES_DATE_RE)
    latest_edges = _latest_matching_date(derived_dir, _EDGES_DATE_RE)
    if not latest_nodes or not latest_edges:
        sys.exit(
            "ERROR: Could not infer a default date from network inputs. "
            "Pass --date explicitly."
        )
    if latest_nodes != latest_edges:
        sys.exit(
            "ERROR: Latest node and edge files have different dates "
            f"({latest_nodes} vs {latest_edges}). Pass --date or explicit paths."
        )
    print(f"INFO: Using latest common network date: {latest_nodes}")
    return latest_nodes


def resolve_photo_manifest(date_token: str | None, manifest_arg: str | None = None) -> Path | None:
    if manifest_arg:
        path = Path(manifest_arg)
        return path if path.is_absolute() else PROJECT_ROOT / path

    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    if date_token:
        exact = derived_dir / f"headshot_manifest_{date_token}.json"
        return exact if exact.exists() else None

    latest = _latest_matching_date(derived_dir, _MANIFEST_DATE_RE)
    return derived_dir / f"headshot_manifest_{latest}.json" if latest else None


def load_photo_map(date_token: str | None = None, manifest_path: str | Path | None = None) -> dict[str, dict]:
    photo_map = {
        "JM-ROOT": {
            "photo_url": JOEL_PHOTO_URL,
            "has_photo": True,
            "photo_kind": "joel",
        }
    }

    resolved = resolve_photo_manifest(date_token, str(manifest_path) if manifest_path else None)
    if not resolved:
        print("WARNING: headshot manifest not found; using Joel portrait only.")
        return photo_map
    if not resolved.exists():
        print(f"WARNING: headshot manifest not found: {resolved}; using Joel portrait only.")
        return photo_map

    data = json.loads(resolved.read_text(encoding="utf-8"))
    for node_id, entry in (data.get("photos") or {}).items():
        photo_url = str(entry.get("photo_url") or "").strip()
        if not photo_url:
            continue
        photo_map[node_id] = {
            "photo_url": photo_url,
            "has_photo": True,
            "photo_kind": entry.get("photo_kind") or "respondent",
        }

    return photo_map


def augment_nodes_with_photos(nodes: list[dict], photo_map: dict[str, dict]) -> list[dict]:
    for node in nodes:
        fields = photo_map.get(node["id"])
        if fields:
            node["photo_url"] = fields["photo_url"]
            node["has_photo"] = True
            node["photo_kind"] = fields["photo_kind"]
        else:
            node["photo_url"] = ""
            node["has_photo"] = False
            node["photo_kind"] = ""
    return nodes


def load_nodes(
    nodes_csv: Path,
    *,
    date_token: str | None = None,
    photo_manifest_path: str | Path | None = None,
    include_photos: bool = True,
) -> list[dict]:
    """Load node rows and exclude email from browser-facing output."""
    nodes = []
    with open(nodes_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gen = row["generation"]
            try:
                gen = int(gen)
            except (ValueError, TypeError):
                gen = None
            populated_detail_fields = sum(
                1
                for value in (
                    row["email"],
                    row["phd_institution_canon"] or row["phd_institution_raw"],
                    row["phd_year"],
                    row["current_employer_canon"] or row["current_employer_raw"],
                    row["country"],
                    row["us_state"],
                )
                if str(value or "").strip()
            )
            relationship_note = (
                (row.get("relationship_note") or "").strip()
                or CURATED_RELATIONSHIP_NOTES.get(row["node_id"], "")
            )
            nodes.append({
                "id": row["node_id"],
                "label": f"{row['first_name']} {row['last_name']}".strip(),
                "generation": gen,
                "has_students": row["has_students"].lower() in ("true", "1", "yes"),
                "is_respondent": row["is_respondent"].lower() in ("true", "1", "yes"),
                "institution": row["phd_institution_canon"] or row["phd_institution_raw"],
                "employer": row["current_employer_canon"] or row["current_employer_raw"],
                "phd_year": row["phd_year"],
                "country": row["country"],
                "us_state": row["us_state"],
                "relationship_note": relationship_note,
                "nonrespondent_field_count": populated_detail_fields,
                "show_nonrespondent": populated_detail_fields >= 2,
            })

    if include_photos:
        augment_nodes_with_photos(
            nodes,
            load_photo_map(date_token=date_token, manifest_path=photo_manifest_path),
        )
    return nodes


def load_edges(edges_csv: Path) -> list[dict]:
    edges = []
    with open(edges_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            edges.append({
                "source": row["source_id"],
                "target": row["target_id"],
                "edge_type": row["edge_type"],
                "confidence": row["confidence"],
            })
    return edges


def assert_no_email_fields(nodes: list[dict]) -> None:
    for node in nodes:
        assert "email" not in node, "BUG: email field present in node output"
