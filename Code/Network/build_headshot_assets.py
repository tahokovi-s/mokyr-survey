#!/usr/bin/env python3
"""Normalize private headshot uploads into static-site image assets."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from genealogy_payload import JOEL_PHOTO_URL, PROJECT_ROOT, resolve_network_date
from photo_assets import (
    HEIC_EXTS,
    PDF_EXTS,
    SUPPORTED_RASTER_EXTS,
    parse_headshot_node_id,
    read_node_ids,
    relative_to_project,
    site_headshot_url,
    write_square_jpeg,
)


EXCLUDED_HEADSHOT_NODE_IDS = {
    "R-R_7AQMF8MYsyfXCtc": "submitted HEIC converted to a black image",
}


def _project_path(raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _scan_sources(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        sys.exit(f"ERROR: headshot input directory not found: {input_dir}")
    return sorted(path for path in input_dir.iterdir() if path.is_file())


def _fail_on_duplicate_live_mappings(sources: list[Path], live_node_ids: set[str]) -> None:
    by_node_id = defaultdict(list)
    for source in sources:
        node_id = parse_headshot_node_id(source.name)
        if node_id and node_id in live_node_ids:
            by_node_id[node_id].append(source.name)

    duplicates = {node_id: names for node_id, names in by_node_id.items() if len(names) > 1}
    if not duplicates:
        return

    lines = ["ERROR: duplicate headshot files map to the same live node:"]
    for node_id, names in sorted(duplicates.items()):
        lines.append(f"  {node_id}: {', '.join(names)}")
    sys.exit("\n".join(lines))


def build_assets(
    *,
    date_token: str,
    nodes_csv: Path,
    input_dir: Path,
    output_dir: Path,
    manifest_path: Path,
    size: int,
    clean: bool,
) -> dict:
    live_node_ids = read_node_ids(nodes_csv)
    sources = _scan_sources(input_dir)
    _fail_on_duplicate_live_mappings(sources, live_node_ids)

    output_dir.mkdir(parents=True, exist_ok=True)
    if clean:
        for old_file in output_dir.glob("*.jpg"):
            old_file.unlink()

    photos = {}
    skipped = []
    converted = 0

    for source in sources:
        node_id = parse_headshot_node_id(source.name)
        ext = source.suffix.lower()

        if not node_id:
            skipped.append({"source_name": source.name, "reason": "unparseable_filename"})
            continue
        if node_id not in live_node_ids:
            skipped.append({"source_name": source.name, "node_id": node_id, "reason": "unmatched_node"})
            continue
        if node_id in EXCLUDED_HEADSHOT_NODE_IDS:
            skipped.append({
                "source_name": source.name,
                "node_id": node_id,
                "reason": "excluded_bad_source",
                "detail": EXCLUDED_HEADSHOT_NODE_IDS[node_id],
            })
            continue
        if ext in PDF_EXTS:
            skipped.append({"source_name": source.name, "node_id": node_id, "reason": "unsupported_pdf"})
            continue
        if ext not in SUPPORTED_RASTER_EXTS and ext not in HEIC_EXTS:
            skipped.append({"source_name": source.name, "node_id": node_id, "reason": "unsupported_extension"})
            continue

        output = output_dir / f"{node_id}.jpg"
        try:
            write_square_jpeg(source, output, size=size)
        except Exception as exc:  # noqa: BLE001 - keep the batch moving and audit failures.
            skipped.append({
                "source_name": source.name,
                "node_id": node_id,
                "reason": "conversion_failed",
                "detail": str(exc),
            })
            continue

        photos[node_id] = {
            "node_id": node_id,
            "photo_url": site_headshot_url(node_id),
            "photo_kind": "respondent",
            "source_name": source.name,
            "output_path": relative_to_project(output),
        }
        converted += 1

    manifest = {
        "date": date_token,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_dir": relative_to_project(input_dir),
        "output_dir": relative_to_project(output_dir),
        "image_size_px": size,
        "joel": {
            "node_id": "JM-ROOT",
            "photo_url": JOEL_PHOTO_URL,
            "photo_kind": "joel",
        },
        "photos": dict(sorted(photos.items())),
        "skipped": skipped,
        "counts": {
            "source_files": len(sources),
            "live_nodes": len(live_node_ids),
            "converted": converted,
            "skipped": len(skipped),
        },
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static headshot assets for the Mokyr site")
    parser.add_argument("--date", default=None, help="Network snapshot date (MMDDYY; defaults to latest common date)")
    parser.add_argument("--nodes", default=None, help="Override Network_Nodes CSV path")
    parser.add_argument("--input-dir", default="Data/Photos/Headshots", help="Raw private headshot directory")
    parser.add_argument("--output-dir", default="mokyr-legacy-site/assets/images/headshots",
                        help="Static-site output directory for normalized JPEGs")
    parser.add_argument("--manifest", default=None, help="Manifest output path")
    parser.add_argument("--size", type=int, default=256, help="Square JPEG size in pixels")
    parser.add_argument("--no-clean", action="store_true", help="Do not remove stale generated .jpg files first")
    args = parser.parse_args()

    date_token = resolve_network_date(args.date, args.nodes, None)
    nodes_csv = _project_path(args.nodes, PROJECT_ROOT / "Data" / "Derived" / f"Network_Nodes_{date_token}.csv")
    input_dir = _project_path(args.input_dir, PROJECT_ROOT / "Data" / "Photos" / "Headshots")
    output_dir = _project_path(args.output_dir, PROJECT_ROOT / "mokyr-legacy-site" / "assets" / "images" / "headshots")
    manifest_path = _project_path(
        args.manifest,
        PROJECT_ROOT / "Data" / "Derived" / f"headshot_manifest_{date_token}.json",
    )

    if not nodes_csv.exists():
        sys.exit(f"ERROR: node CSV not found: {nodes_csv}")

    manifest = build_assets(
        date_token=date_token,
        nodes_csv=nodes_csv,
        input_dir=input_dir,
        output_dir=output_dir,
        manifest_path=manifest_path,
        size=args.size,
        clean=not args.no_clean,
    )

    counts = manifest["counts"]
    print(f"Converted {counts['converted']} headshots into {relative_to_project(output_dir)}")
    print(f"Skipped {counts['skipped']} source files; audit written to {relative_to_project(manifest_path)}")


if __name__ == "__main__":
    main()
