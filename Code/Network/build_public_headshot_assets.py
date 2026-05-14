#!/usr/bin/env python3
"""Import public headshot candidate URLs into the static-site photo manifest."""

from __future__ import annotations

import argparse
import csv
import glob
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from genealogy_payload import JOEL_PHOTO_URL, PROJECT_ROOT, resolve_network_date
from photo_assets import read_node_ids, relative_to_project, site_headshot_url, write_square_jpeg


DEFAULT_SOURCE_GLOB = "tmp/headshot_candidate_sources*.csv"
DEFAULT_CONFIDENCES = {"high", "medium"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
CONTENT_TYPE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}
SOURCE_OVERRIDES = {
    "R-R_3ZQuPNPNkATw1Yq": {
        "source_page": "https://publicchoice.gmu.edu/people/jnye",
        "image_url": "https://d101vc9winf8ln.cloudfront.net/person_images/420/cropped/Nye_headshot.jpg?1573583927",
        "image_alt": "John V.C. Nye",
        "image_size": "150x196",
        "source_override_note": "Original Mercatus image URL blocks scripted downloads; recovered from GMU Public Choice profile.",
    },
    "R-R_8tszxcMbwpusLHJ": {
        "image_url": "https://lh3.googleusercontent.com/sitesv/AA5AbUDpMeV3Twy4MjOWxg2cGHY3k3vJg0en_KtpYVjCBTixFO60Tg1bqUGEn_m76yqKfnE5slaIy7QseI-JxAmX0tu0ZRd0dliPmSsl1lHjPEfchmoVtA4keJaxZ-_A37jjnK1Ww7zMJEhYzpMrDM5auP2DIk7__g0VOyjjx8OOffNF1_VDh6fgr_u4ZfDOWRW7-c1nN6EsohGZvUFW6TwMXyi2AMFD1_el4IOGf4w=w1280",
        "image_size": "914x1080",
        "source_override_note": "Recovered current image URL from the public Google Sites page metadata.",
    },
    "S-R_9fffypos5QJL0th-0001": {
        "local_source_path": "Code/Network/public_headshot_source_assets/S-R_9fffypos5QJL0th-0001.png",
        "source_override_note": "Official Matrix CMS image blocks non-browser downloads; local source captured from the rendered official page.",
    },
    "S-R_6MMXY4gX2jvIJUe-0001": {
        "source_page": "https://economics.rutgers.edu/people/faculty/people/192-graduate-student-directory/204-graduate-student-directory-2016/649-garib-andrew",
        "image_url": "https://economics.rutgers.edu/images/stories/Graduate/2016Grad/AndrewGarib.JPG",
        "image_alt": "Andrew S. Garib",
        "image_size": "1000x667",
        "source_override_note": "Original Google Sites image URL was stale; recovered from Rutgers Economics profile.",
    },
    "S-R_3uvEz6kA5E8QDAt-0002": {
        "source_page": "https://sites.google.com/view/benjonomics",
        "image_url": "https://lh3.googleusercontent.com/sitesv/AA5AbUDrH63O0Ub2r2-kpxxy31z_kiSWz4KhJ9jqlkKP_q0q_gQDLNF7c9EXbOIBT5qOYhERQZIANZw4K8htFXhNkytfsNo9HM6Al2kWV62uOUpmAPgeAPpj2zrjH9L3BKqMKtXy3lnFqaRVpt7zij5lTz3ERTq4ZLaf2rL-qaEoHrUdx1esTdGyXnER5fA-rdpfZtbhxcSYW8I4v7IXp5bsJQ2qisN_iFuX6nUpB7Q=w1280",
        "image_size": "1000x997",
        "source_override_note": "Original Google Sites image URL was stale; recovered from the current public site.",
    },
    "S-R_7vrtdVnraeOr681-0013": {
        "image_url": "https://economics.ucdavis.edu/sites/g/files/dgvnsk13091/files/styles/sf_profile/public/media/images/gilberto%20jose-nogueira.png?h=55541bb6&itok=EEPbVn6D",
        "image_alt": "Gilberto Jose Nogueira Portrait",
        "image_size": "520x580",
        "source_override_note": "Original UC Davis image URL was stale; recovered current profile image URL.",
    },
    "S-R_3J1KEWYwi7MlWAr-0001": {
        "source_page": "https://www.aetc.af.mil/News/Article-Display/Article/3112985/introducing-maj-justin-moore-17th-cpts-17th-wsa-commander/",
        "image_url": "https://media.defense.gov/2022/Aug/01/2003047788/2000/2000/0/220624-F-DX569-1005.JPG",
        "image_alt": "U.S. Air Force Maj. Justin Moore, 17th Comptroller Squadron and 17th Wing Staff Agencies commander, poses for a photo in the finance office at Goodfellow Air Force Base, Texas, June 24, 2022.",
        "image_size": "2000x1600",
        "local_source_path": "Code/Network/public_headshot_source_assets/S-R_3J1KEWYwi7MlWAr-0001.jpg",
        "source_override_note": "Defense Media image blocks scripted downloads; local source captured from the rendered official AETC page.",
    },
    "S-R_5HlkntYyP2MGbpD-0004": {
        "image_url": "https://www.ifpri.org/wp-content/uploads/2025/03/kosec_katrina.jpg",
        "image_alt": "Katrina Kosec",
        "image_size": "unknown",
        "source_override_note": "Original IFPRI image URL was stale; recovered current IFPRI profile image URL.",
    },
}


def _project_path(raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _source_paths(patterns: list[str]) -> list[Path]:
    paths: set[Path] = set()
    for pattern in patterns:
        raw_path = Path(pattern)
        search = str(raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path)
        for match in glob.glob(search):
            path = Path(match)
            if path.is_file():
                paths.add(path.resolve())
    return sorted(paths)


def _read_candidates(source_paths: list[Path], confidences: set[str]) -> tuple[list[dict], list[dict]]:
    selected: list[dict] = []
    held_out: list[dict] = []
    for path in source_paths:
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                normalized = {key: (value or "").strip() for key, value in row.items()}
                normalized["source_csv"] = relative_to_project(path)
                status = normalized.get("status", "").lower()
                confidence = normalized.get("confidence", "").lower()
                if status == "candidate_image" and confidence in confidences:
                    selected.append(normalized)
                else:
                    held_out.append(normalized)
    return selected, held_out


def _fail_on_duplicate_selected_rows(rows: list[dict]) -> None:
    by_node_id: dict[str, list[dict]] = {}
    for row in rows:
        by_node_id.setdefault(row.get("node_id", ""), []).append(row)
    duplicates = {node_id: node_rows for node_id, node_rows in by_node_id.items() if len(node_rows) > 1}
    if not duplicates:
        return
    lines = ["ERROR: duplicate selected public headshot rows map to the same node_id:"]
    for node_id, node_rows in sorted(duplicates.items()):
        sources = ", ".join(f"{row.get('source_csv')}:{row.get('name')}" for row in node_rows)
        lines.append(f"  {node_id}: {sources}")
    sys.exit("\n".join(lines))


def _quote_url(url: str) -> str:
    return urllib.parse.quote(url, safe=":/?&=%#~+!$,;'@()*[]")


def _apply_source_overrides(row: dict) -> dict:
    override = SOURCE_OVERRIDES.get(row.get("node_id", ""))
    if not override:
        return row

    updated = dict(row)
    for key, value in override.items():
        if key in {"image_url", "source_page"} and updated.get(key) and updated.get(key) != value:
            updated[f"original_{key}"] = updated[key]
        updated[key] = value
    return updated


def _suffix_for_response(url: str, content_type: str | None) -> str:
    media_type = (content_type or "").split(";", 1)[0].lower().strip()
    if media_type in CONTENT_TYPE_SUFFIXES:
        return CONTENT_TYPE_SUFFIXES[media_type]
    suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    return suffix if suffix else ".img"


def _curl_download_image(url: str, destination: Path, referer: str | None = None) -> None:
    command = [
        "curl",
        "-L",
        "-f",
        "-sS",
        "--retry",
        "2",
        "--connect-timeout",
        "20",
        "--max-time",
        "90",
        "-A",
        USER_AGENT,
        "-H",
        "Accept: image/webp,image/apng,image/*,*/*;q=0.8",
    ]
    if referer:
        command.extend(["-e", referer])
    command.extend(["-o", str(destination), url])
    subprocess.run(command, check=True, capture_output=True, text=True)


def _download_image(url: str, destination: Path, referer: str | None = None) -> None:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(
        _quote_url(url),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read()
        destination.write_bytes(data)
    except Exception as urllib_exc:  # noqa: BLE001 - curl is the pragmatic fallback for uneven hosts.
        try:
            _curl_download_image(url, destination, referer=referer)
        except subprocess.CalledProcessError as curl_exc:
            stderr = (curl_exc.stderr or "").strip()
            detail = stderr or f"curl exited {curl_exc.returncode}"
            raise RuntimeError(f"urllib failed ({urllib_exc}); curl failed ({detail})") from curl_exc


def _resolve_local_source_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _load_manifest(manifest_path: Path, date_token: str) -> dict:
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "date": date_token,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "joel": {
            "node_id": "JM-ROOT",
            "photo_url": JOEL_PHOTO_URL,
            "photo_kind": "joel",
        },
        "photos": {},
        "skipped": [],
        "counts": {},
    }


def build_public_assets(
    *,
    date_token: str,
    nodes_csv: Path,
    source_patterns: list[str],
    output_dir: Path,
    manifest_path: Path,
    size: int,
    confidences: set[str],
    expect_selected: int | None,
    expect_total_photos: int | None,
) -> dict:
    live_node_ids = read_node_ids(nodes_csv)
    source_paths = _source_paths(source_patterns)
    if not source_paths:
        sys.exit(f"ERROR: no public headshot source CSVs matched: {', '.join(source_patterns)}")

    selected, held_out = _read_candidates(source_paths, confidences)
    selected = [_apply_source_overrides(row) for row in selected]
    _fail_on_duplicate_selected_rows(selected)

    missing_ids = [row for row in selected if row.get("node_id") not in live_node_ids]
    missing_urls = [row for row in selected if not row.get("image_url")]
    if missing_ids or missing_urls:
        lines = []
        if missing_ids:
            lines.append("ERROR: selected public headshots include node_ids absent from the network:")
            lines.extend(f"  {row.get('node_id')}: {row.get('name')}" for row in missing_ids)
        if missing_urls:
            lines.append("ERROR: selected public headshots are missing image_url:")
            lines.extend(f"  {row.get('node_id')}: {row.get('name')}" for row in missing_urls)
        sys.exit("\n".join(lines))

    if expect_selected is not None and len(selected) != expect_selected:
        sys.exit(f"ERROR: expected {expect_selected} selected rows, found {len(selected)}")

    manifest = _load_manifest(manifest_path, date_token)
    photos = dict(manifest.get("photos") or {})
    output_dir.mkdir(parents=True, exist_ok=True)

    imported = []
    preserved_existing = []
    failures = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for row in selected:
            node_id = row["node_id"]
            existing = photos.get(node_id)
            if existing and existing.get("photo_kind") != "public_candidate":
                preserved_existing.append({
                    "node_id": node_id,
                    "name": row.get("name", ""),
                    "reason": "preserved_existing_manifest_photo",
                })
                continue

            image_url = row["image_url"]
            try:
                head_request = urllib.request.Request(
                    _quote_url(image_url),
                    headers={"User-Agent": USER_AGENT, "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"},
                    method="HEAD",
                )
                with urllib.request.urlopen(head_request, timeout=20) as response:
                    suffix = _suffix_for_response(image_url, response.headers.get("Content-Type"))
            except Exception:  # noqa: BLE001 - HEAD often fails; the GET path below is authoritative.
                suffix = _suffix_for_response(image_url, None)

            source_file = tmp_path / f"{node_id}{suffix}"
            output_file = output_dir / f"{node_id}.jpg"
            try:
                local_source_path = row.get("local_source_path", "")
                if local_source_path:
                    source_path = _resolve_local_source_path(local_source_path)
                    if not source_path.exists():
                        raise FileNotFoundError(f"local source asset not found: {source_path}")
                    write_square_jpeg(source_path, output_file, size=size)
                else:
                    _download_image(image_url, source_file, referer=row.get("source_page") or None)
                    write_square_jpeg(source_file, output_file, size=size)
            except (OSError, RuntimeError, urllib.error.URLError, TimeoutError) as exc:
                failures.append({
                    "node_id": node_id,
                    "name": row.get("name", ""),
                    "image_url": image_url,
                    "reason": "download_or_conversion_failed",
                    "detail": str(exc),
                })
                continue

            photo_entry = {
                "node_id": node_id,
                "photo_url": site_headshot_url(node_id),
                "photo_kind": "public_candidate",
                "source_csv": row.get("source_csv", ""),
                "source_page": row.get("source_page", ""),
                "image_url": image_url,
                "image_alt": row.get("image_alt", ""),
                "image_size": row.get("image_size", ""),
                "confidence": row.get("confidence", ""),
                "name": row.get("name", ""),
                "output_path": relative_to_project(output_file),
            }
            for metadata_key in (
                "original_image_url",
                "original_source_page",
                "source_override_note",
                "local_source_path",
            ):
                if row.get(metadata_key):
                    photo_entry[metadata_key] = row[metadata_key]
            photos[node_id] = photo_entry
            imported.append(node_id)

    if failures:
        lines = [f"ERROR: failed to import {len(failures)} selected public headshot(s):"]
        lines.extend(f"  {item['node_id']} {item['name']}: {item['detail']}" for item in failures[:30])
        if len(failures) > 30:
            lines.append(f"  ... {len(failures) - 30} more")
        sys.exit("\n".join(lines))

    manifest["date"] = date_token
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["output_dir"] = relative_to_project(output_dir)
    manifest["image_size_px"] = size
    manifest["photos"] = dict(sorted(photos.items()))
    manifest.setdefault("counts", {})
    manifest["counts"].update({
        "public_candidate_selected": len(selected),
        "public_candidate_imported": len(imported),
        "public_candidate_preserved_existing": len(preserved_existing),
        "public_candidate_held_out": len(held_out),
        "total_photos": len(manifest["photos"]),
    })
    manifest["public_headshots"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csvs": [relative_to_project(path) for path in source_paths],
        "confidence_threshold": sorted(confidences),
        "selected": len(selected),
        "imported": len(imported),
        "preserved_existing": preserved_existing,
        "held_out": len(held_out),
    }

    if expect_total_photos is not None and len(manifest["photos"]) != expect_total_photos:
        sys.exit(f"ERROR: expected {expect_total_photos} manifest photos, found {len(manifest['photos'])}")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Import public headshot candidates into static assets")
    parser.add_argument("--date", default=None, help="Network snapshot date (MMDDYY; defaults to latest common date)")
    parser.add_argument("--nodes", default=None, help="Override Network_Nodes CSV path")
    parser.add_argument("--source-glob", action="append", default=None,
                        help=f"Candidate source CSV glob (default: {DEFAULT_SOURCE_GLOB})")
    parser.add_argument("--output-dir", default="mokyr-legacy-site/assets/images/headshots",
                        help="Static-site output directory for normalized JPEGs")
    parser.add_argument("--manifest", default=None, help="Headshot manifest path to merge into")
    parser.add_argument("--size", type=int, default=256, help="Square JPEG size in pixels")
    parser.add_argument("--confidence", action="append", choices=("high", "medium", "low"), default=None,
                        help="Candidate confidence to include; repeatable (default: high and medium)")
    parser.add_argument("--expect-selected", type=int, default=None, help="Fail unless this many rows are selected")
    parser.add_argument("--expect-total-photos", type=int, default=None,
                        help="Fail unless the merged manifest has this many photos")
    args = parser.parse_args()

    date_token = resolve_network_date(args.date, args.nodes, None)
    nodes_csv = _project_path(args.nodes, PROJECT_ROOT / "Data" / "Derived" / f"Network_Nodes_{date_token}.csv")
    output_dir = _project_path(args.output_dir, PROJECT_ROOT / "mokyr-legacy-site" / "assets" / "images" / "headshots")
    manifest_path = _project_path(
        args.manifest,
        PROJECT_ROOT / "Data" / "Derived" / f"headshot_manifest_{date_token}.json",
    )
    source_patterns = args.source_glob or [DEFAULT_SOURCE_GLOB]
    confidences = {value.lower() for value in (args.confidence or sorted(DEFAULT_CONFIDENCES))}

    if not nodes_csv.exists():
        sys.exit(f"ERROR: node CSV not found: {nodes_csv}")

    manifest = build_public_assets(
        date_token=date_token,
        nodes_csv=nodes_csv,
        source_patterns=source_patterns,
        output_dir=output_dir,
        manifest_path=manifest_path,
        size=args.size,
        confidences=confidences,
        expect_selected=args.expect_selected,
        expect_total_photos=args.expect_total_photos,
    )

    public_counts = manifest["counts"]
    print(
        "Imported "
        f"{public_counts['public_candidate_imported']} public headshots "
        f"({public_counts['public_candidate_selected']} selected, "
        f"{public_counts['public_candidate_preserved_existing']} preserved existing)."
    )
    print(f"Manifest photos: {public_counts['total_photos']}")
    print(f"Manifest: {relative_to_project(manifest_path)}")


if __name__ == "__main__":
    main()
