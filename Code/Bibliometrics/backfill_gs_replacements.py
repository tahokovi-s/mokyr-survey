#!/usr/bin/env python3
"""Backfill Google Scholar data for confirmed replacement profiles and apply all mismatch corrections.

Phase 1 — Playwright direct-URL scrape:
  Visits 4 confirmed replacement GS profiles + Hyoungchul Kim's current profile to extract
  affiliation, research interests, and bibliometrics (citations, h-index, i10).
  For Hyoungchul Kim (review case), also collects the first 5 publication titles.

Phase 2 — Patch CSV:
  Produces Data/Derived/GS_Gen2_Patched_041526.csv by applying:
    • replace rows  — updated URL + backfilled metrics, quality=match
    • reject rows   — quality=false_positive, cleared URL + zeroed metrics
    • review row    — user decides keep/reject after seeing scraped interests/titles

Usage:
  python Code/Bibliometrics/backfill_gs_replacements.py
"""
from __future__ import annotations

import csv
import random
import sys
import time
from pathlib import Path
from typing import Any

# ── shared utilities from the sibling scraper ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_gs_gen2 import (  # noqa: E402
    OUTPUT_FIELDS,
    close_browser_session,
    extract_profile_affiliation,
    extract_profile_stats,
    has_captcha,
    has_interactive_challenge,
    open_browser_session,
)

# ── project paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GS_CSV_IN    = PROJECT_ROOT / "Data/Derived/GS_Gen2_041526.csv"
BACKFILL_OUT = PROJECT_ROOT / "Data/Derived/GS_Gen2_Backfill_041526.csv"
PATCHED_OUT  = PROJECT_ROOT / "Data/Derived/GS_Gen2_Patched_041526.csv"
PROFILE_DIR  = Path("/tmp/gs_gen2_playwright_profile")

BACKFILL_FIELDS = [
    "node_id",
    "name",
    "gs_profile_url",
    "gs_affiliation",
    "gs_interests",
    "citations_all",
    "citations_recent",
    "h_index_all",
    "h_index_recent",
    "i10_all",
    "i10_recent",
    "scrape_status",
    "pub_sample",
]

# ── targets ────────────────────────────────────────────────────────────────────
BACKFILL_TARGETS: list[dict[str, str]] = [
    {
        "node_id": "R-R_3WMhhH9M9XgmAvi",
        "name": "Geoff Clarke",
        "gs_url": "https://scholar.google.com/citations?user=424eT7QAAAAJ&hl=en",
        "action": "replace",
    },
    {
        "node_id": "R-R_4Lnal0e85pYtT48",
        "name": "Joy Chen",
        "gs_url": "https://scholar.google.com/citations?user=GeQS-BAAAAAJ&hl=en",
        "action": "replace",
    },
    {
        "node_id": "R-R_4uyqsoTLUFko2rc",
        "name": "Anirban Mukherjee",
        "gs_url": "https://scholar.google.com/citations?hl=en&user=eIDenGEAAAAJ",
        "action": "replace",
    },
    {
        "node_id": "R-R_5BnQrc3zjl7F9QU",
        "name": "Alain Pineda",
        "gs_url": "https://scholar.google.com/citations?user=wSY8lKgAAAAJ&hl=en",
        "action": "replace",
    },
    {
        "node_id": "R-R_525aqafDBlUUR5b",
        "name": "Hyoungchul Kim",
        "gs_url": "https://scholar.google.com/citations?hl=en&user=rnQriZkAAAAJ",
        "action": "review",
    },
]

REJECT_NODE_IDS: frozenset[str] = frozenset({
    "R-R_10DVor7WawmqRrz",  # Qiyi Zhao
    "R-R_1thdRkZWMU7Gk4F",  # Scott Baker
    "R-R_20rCZl68g1CGwMr",  # Guillermo Martinez
    "R-R_3TnIL3fecgVT4Nn",  # Yujing Huang
    "R-R_3eIWqCOCYJodOU4",  # Juan González
    "R-R_4mrSyKtlha4x6rT",  # Shuo Yang
    "R-R_4qvJlnzRuwNMop0",  # Mengru Wang
    "R-R_4tFJZgPNQmXZe8J",  # Jianguo Wang
    "R-R_5bTQAFcivjTDjHI",  # Michael Bailey
})
REPLACE_NODE_IDS: frozenset[str] = frozenset(
    t["node_id"] for t in BACKFILL_TARGETS if t["action"] == "replace"
)
REVIEW_NODE_ID = "R-R_525aqafDBlUUR5b"


# ── low-level scraping helpers ─────────────────────────────────────────────────

def extract_interests(page: Any) -> str:
    try:
        texts = page.locator("a.gsc_prf_inta").all_inner_texts()
        return ", ".join(t.strip() for t in texts if t.strip())
    except Exception:
        return ""


def extract_pub_titles(page: Any, limit: int = 5) -> str:
    try:
        titles = page.locator("td.gsc_a_at").all_inner_texts()
        return " | ".join(t.strip() for t in titles[:limit] if t.strip())
    except Exception:
        return ""


def handle_captcha_direct(page: Any, profile_url: str, name: str) -> bool:
    """Prompt the user to solve a CAPTCHA and re-navigate to the profile URL.
    Returns True if the page is unblocked after solving, False otherwise."""
    if not has_captcha(page):
        return True

    if not has_interactive_challenge(page):
        print(
            f"\nGoogle Scholar hard block while processing {name}. "
            "No interactive CAPTCHA was detected. "
            "Wait a few minutes, then press Enter to retry.",
            file=sys.stderr,
            flush=True,
        )
    else:
        print(
            f"\nCAPTCHA detected while processing {name}. "
            "Solve it in the browser window, then press Enter here.",
            file=sys.stderr,
            flush=True,
        )

    try:
        input()
    except EOFError:
        print("No stdin available for CAPTCHA prompt; aborting.", file=sys.stderr, flush=True)
        return False

    page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(random.uniform(5.0, 9.0))
    return not has_captcha(page)


def _empty_backfill_row(node_id: str, name: str, url: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "name": name,
        "gs_profile_url": url,
        "gs_affiliation": "",
        "gs_interests": "",
        "citations_all": 0,
        "citations_recent": 0,
        "h_index_all": 0,
        "h_index_recent": 0,
        "i10_all": 0,
        "i10_recent": 0,
        "scrape_status": "",
        "pub_sample": "",
    }


def scrape_profile_direct(page: Any, target: dict[str, str]) -> dict[str, Any]:
    """Navigate directly to a known GS profile URL and extract bibliometrics."""
    url     = target["gs_url"]
    name    = target["name"]
    node_id = target["node_id"]
    is_review = target["action"] == "review"

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(random.uniform(5.0, 9.0))

    if has_captcha(page):
        if not handle_captcha_direct(page, url, name):
            return {**_empty_backfill_row(node_id, name, url), "scrape_status": "captcha"}

    try:
        page.wait_for_selector("#gsc_prf_i", timeout=15000)
    except Exception:
        return {**_empty_backfill_row(node_id, name, url), "scrape_status": "missing"}

    affiliation = extract_profile_affiliation(page)
    interests   = extract_interests(page)
    stats       = extract_profile_stats(page)
    pub_sample  = extract_pub_titles(page) if is_review else ""

    return {
        "node_id":          node_id,
        "name":             name,
        "gs_profile_url":   url,
        "gs_affiliation":   affiliation,
        "gs_interests":     interests,
        "citations_all":    stats["citations_all"],
        "citations_recent": stats["citations_recent"],
        "h_index_all":      stats["h_index_all"],
        "h_index_recent":   stats["h_index_recent"],
        "i10_all":          stats["i10_all"],
        "i10_recent":       stats["i10_recent"],
        "scrape_status":    "ok",
        "pub_sample":       pub_sample,
    }


# ── Phase 1: scrape 5 profiles ─────────────────────────────────────────────────

def run_scrape_phase() -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed. Run:\n"
            "  python3 -m pip install playwright\n"
            "  python3 -m playwright install chromium"
        ) from exc

    results: list[dict[str, Any]] = []

    with sync_playwright() as pw:
        browser, context, page = open_browser_session(pw, PROFILE_DIR)
        try:
            total = len(BACKFILL_TARGETS)
            for i, target in enumerate(BACKFILL_TARGETS):
                print(
                    f"[{i + 1}/{total}] Scraping {target['name']} ({target['action']}) ...",
                    flush=True,
                )
                row = scrape_profile_direct(page, target)
                results.append(row)
                print(
                    f"  status={row['scrape_status']}  "
                    f"affiliation={row['gs_affiliation']!r}  "
                    f"citations={row['citations_all']}  h={row['h_index_all']}",
                    flush=True,
                )
                if target["action"] == "review":
                    print(f"  interests:    {row['gs_interests']!r}", flush=True)
                    print(f"  publications: {row['pub_sample']!r}", flush=True)
                if i < total - 1:
                    time.sleep(random.uniform(6.0, 10.0))
        finally:
            close_browser_session(context, browser)

    return results


def write_backfill_csv(rows: list[dict[str, Any]]) -> None:
    if BACKFILL_OUT.exists():
        print(f"Backfill CSV already exists ({BACKFILL_OUT}); not overwriting.", flush=True)
        return
    with BACKFILL_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BACKFILL_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows → {BACKFILL_OUT}", flush=True)


def load_backfill_csv() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with BACKFILL_OUT.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for field in (
                "citations_all", "citations_recent",
                "h_index_all", "h_index_recent",
                "i10_all", "i10_recent",
            ):
                row[field] = int(row.get(field) or 0)
            rows.append(row)
    return rows


# ── Hyoungchul Kim review prompt ───────────────────────────────────────────────

def ask_kim_decision(kim_row: dict[str, Any]) -> str:
    """Print Kim's scraped data and ask the user whether to keep or reject."""
    print("\n" + "=" * 60, flush=True)
    print("HYOUNGCHUL KIM — field verification", flush=True)
    print(f"  GS URL:          {kim_row.get('gs_profile_url', '')}", flush=True)
    print(f"  GS affiliation:  {kim_row.get('gs_affiliation', '')!r}", flush=True)
    print(f"  GS interests:    {kim_row.get('gs_interests', '')!r}", flush=True)
    print(f"  Citations (all): {kim_row.get('citations_all', 'N/A')}", flush=True)
    print(f"  h-index (all):   {kim_row.get('h_index_all', 'N/A')}", flush=True)
    if kim_row.get("pub_sample"):
        print(f"  Recent pubs:     {kim_row['pub_sample']!r}", flush=True)
    print("=" * 60, flush=True)
    print(
        "Is this the correct Hyoungchul Kim (an economist in Mokyr's lineage)?",
        flush=True,
    )
    while True:
        try:
            answer = input("  keep / reject [k/r]: ").strip().lower()
        except EOFError:
            print(
                "No stdin available; leaving Kim's row unchanged (review).",
                file=sys.stderr,
                flush=True,
            )
            return "review"
        if answer in ("k", "keep"):
            return "keep"
        if answer in ("r", "reject"):
            return "reject"
        print("  Please enter k (keep) or r (reject).", flush=True)


# ── Phase 2: build patched CSV ─────────────────────────────────────────────────

def build_patched_csv(
    backfill_rows: list[dict[str, Any]],
    kim_decision: str,
) -> None:
    if PATCHED_OUT.exists():
        print(
            f"Patched CSV already exists: {PATCHED_OUT} — not overwriting.",
            flush=True,
        )
        return

    backfill_by_id = {r["node_id"]: r for r in backfill_rows}

    with GS_CSV_IN.open(newline="", encoding="utf-8-sig") as f:
        original_rows = list(csv.DictReader(f))

    reject_count = replace_count = 0
    patched: list[dict[str, Any]] = []

    for row in original_rows:
        nid = row["node_id"]

        if nid in REJECT_NODE_IDS:
            row["quality"]                = "false_positive"
            row["gs_suspicious_mismatch"] = "1"
            row["gs_profile_url"]         = ""
            row["in_gs"]                  = "False"
            row["affiliation"]            = ""
            row["citations_all"]          = "0"
            row["citations_recent"]       = "0"
            row["h_index_all"]            = "0"
            row["h_index_recent"]         = "0"
            row["i10_all"]                = "0"
            row["i10_recent"]             = "0"
            reject_count += 1

        elif nid in REPLACE_NODE_IDS:
            bf = backfill_by_id.get(nid)
            if bf and bf.get("scrape_status") == "ok":
                row["gs_profile_url"]         = bf["gs_profile_url"]
                row["quality"]                = "match"
                row["gs_suspicious_mismatch"] = "0"
                row["in_gs"]                  = "True"
                row["affiliation"]            = bf["gs_affiliation"]
                row["citations_all"]          = str(bf["citations_all"])
                row["citations_recent"]       = str(bf["citations_recent"])
                row["h_index_all"]            = str(bf["h_index_all"])
                row["h_index_recent"]         = str(bf["h_index_recent"])
                row["i10_all"]                = str(bf["i10_all"])
                row["i10_recent"]             = str(bf["i10_recent"])
                replace_count += 1
            else:
                print(
                    f"  WARNING: backfill missing or failed for {nid} ({row.get('name', '')}); "
                    "row left unchanged.",
                    file=sys.stderr,
                    flush=True,
                )

        elif nid == REVIEW_NODE_ID:
            if kim_decision == "keep":
                bf = backfill_by_id.get(nid)
                if bf and bf.get("scrape_status") == "ok":
                    row["quality"]                = "match"
                    row["gs_suspicious_mismatch"] = "0"
                    row["affiliation"]            = bf["gs_affiliation"]
                    row["citations_all"]          = str(bf["citations_all"])
                    row["citations_recent"]       = str(bf["citations_recent"])
                    row["h_index_all"]            = str(bf["h_index_all"])
                    row["h_index_recent"]         = str(bf["h_index_recent"])
                    row["i10_all"]                = str(bf["i10_all"])
                    row["i10_recent"]             = str(bf["i10_recent"])
                    print(f"  Hyoungchul Kim: kept as valid (quality=match).", flush=True)
            elif kim_decision == "reject":
                row["quality"]                = "false_positive"
                row["gs_suspicious_mismatch"] = "1"
                row["gs_profile_url"]         = ""
                row["in_gs"]                  = "False"
                row["affiliation"]            = ""
                row["citations_all"]          = "0"
                row["citations_recent"]       = "0"
                row["h_index_all"]            = "0"
                row["h_index_recent"]         = "0"
                row["i10_all"]                = "0"
                row["i10_recent"]             = "0"
                print(f"  Hyoungchul Kim: rejected (quality=false_positive).", flush=True)
            else:
                print(
                    f"  Hyoungchul Kim: no decision made; row left unchanged.",
                    flush=True,
                )

        patched.append(row)

    with PATCHED_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(patched)

    print(
        f"\nPatched CSV written: {PATCHED_OUT}\n"
        f"  {len(patched)} total rows  |  {replace_count} replaced  |  {reject_count} rejected",
        flush=True,
    )


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    if PATCHED_OUT.exists():
        print(
            f"Patched CSV already exists: {PATCHED_OUT}\n"
            "Delete it first if you want to regenerate.",
            flush=True,
        )
        return 1

    # Phase 1: scrape (or load existing backfill CSV)
    if BACKFILL_OUT.exists():
        print(
            f"Backfill CSV exists; loading from {BACKFILL_OUT} (skipping browser scrape).",
            flush=True,
        )
        backfill_rows = load_backfill_csv()
    else:
        backfill_rows = run_scrape_phase()
        write_backfill_csv(backfill_rows)

    # Hyoungchul Kim: inspect scrape result and ask user
    kim_row = next(
        (r for r in backfill_rows if r["node_id"] == REVIEW_NODE_ID), {}
    )
    kim_decision = ask_kim_decision(kim_row)

    # Phase 2: patch
    build_patched_csv(backfill_rows, kim_decision)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
