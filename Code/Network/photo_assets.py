#!/usr/bin/env python3
"""Headshot asset helpers for static genealogy outputs."""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from genealogy_payload import HEADSHOT_URL_PREFIX, PROJECT_ROOT

RESPONDENT_FILENAME_RE = re.compile(r"^(R_[^_]+)_")
SUPPORTED_RASTER_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
HEIC_EXTS = {".heic", ".heif"}
PDF_EXTS = {".pdf"}


def parse_headshot_node_id(filename: str) -> str | None:
    match = RESPONDENT_FILENAME_RE.match(filename)
    if not match:
        return None
    return "R-" + match.group(1)


def read_node_ids(nodes_csv: Path) -> set[str]:
    with open(nodes_csv, newline="", encoding="utf-8") as f:
        return {row["node_id"] for row in csv.DictReader(f)}


def site_headshot_url(node_id: str) -> str:
    return f"{HEADSHOT_URL_PREFIX}/{node_id}.jpg"


def _open_image_copy(source: Path):
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise RuntimeError("Pillow is required to build headshot assets") from exc

    try:
        with Image.open(source) as image:
            return ImageOps.exif_transpose(image).copy()
    except UnidentifiedImageError:
        if source.suffix.lower() not in HEIC_EXTS:
            raise
        if not shutil.which("sips"):
            raise RuntimeError("HEIC input requires Pillow HEIF support or macOS sips")
        with tempfile.TemporaryDirectory() as tmpdir:
            converted = Path(tmpdir) / "converted.jpg"
            subprocess.run(
                ["sips", "-s", "format", "jpeg", str(source), "--out", str(converted)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            with Image.open(converted) as image:
                return ImageOps.exif_transpose(image).copy()


def _to_rgb(image):
    from PIL import Image

    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def write_square_jpeg(source: Path, output: Path, size: int = 256, quality: int = 88) -> None:
    from PIL import Image

    image = _to_rgb(_open_image_copy(source))
    width, height = image.size
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid image dimensions for {source}")

    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = image.crop((left, top, left + side, top + side))
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    resized = cropped.resize((size, size), resampling)

    output.parent.mkdir(parents=True, exist_ok=True)
    resized.save(output, "JPEG", quality=quality, optimize=True, progressive=True)


def relative_to_project(path: Path) -> str:
    return str(path.resolve().relative_to(PROJECT_ROOT))

