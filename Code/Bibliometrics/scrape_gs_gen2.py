#!/usr/bin/env python3
"""Scrape Google Scholar bibliometrics for remaining Gen 2 scholars.

This script appends one row per completed scholar to the partial Gen 2
Google Scholar CSV. It uses Playwright's sync API and launches headed Chromium
so CAPTCHA challenges are visible to the user.
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin

try:
    from playwright_stealth import stealth_sync
except ImportError:
    from playwright_stealth import Stealth

    def stealth_sync(page: Any) -> None:
        Stealth().apply_stealth_sync(page)


OUTPUT_FIELDS = [
    "node_id",
    "name",
    "in_gs",
    "quality",
    "gs_suspicious_mismatch",
    "gs_profile_url",
    "citations_all",
    "citations_recent",
    "h_index_all",
    "h_index_recent",
    "i10_all",
    "i10_recent",
    "affiliation",
]
LEGACY_OUTPUT_FIELDS = [field for field in OUTPUT_FIELDS if field != "gs_suspicious_mismatch"]

DEFAULT_NODES_REL = Path("Data/Derived/Network_Nodes_040126.csv")
DEFAULT_CSV_REL = Path("Data/Derived/GS_Gen2_041526.csv")
DEFAULT_PROFILE_DIR = Path("/tmp/gs_gen2_playwright_profile")
GENERATION = "2"

SUSPICIOUS_MISMATCH_NODE_IDS = frozenset(
    {
        "R-R_10DVor7WawmqRrz",  # Qiyi Zhao: existing false positive.
        "R-R_1thdRkZWMU7Gk4F",  # Scott Baker: known contaminated profile risk.
        "R-R_20rCZl68g1CGwMr",  # Guillermo Martinez: likely out-of-field profile.
        "R-R_3TnIL3fecgVT4Nn",  # Yujing Huang: computing/information systems.
        "R-R_3WMhhH9M9XgmAvi",  # Geoff Clarke: geoscience.
        "R-R_3eIWqCOCYJodOU4",  # Juan Gonzalez: nuclear physics/extreme citations.
        "R-R_4Lnal0e85pYtT48",  # Joy Chen: kinesiology.
        "R-R_4mrSyKtlha4x6rT",  # Shuo Yang: computer vision.
        "R-R_4qvJlnzRuwNMop0",  # Mengru Wang: known false institution/common-name risk.
        "R-R_4tFJZgPNQmXZe8J",  # Jianguo Wang: mechanics/civil engineering.
        "R-R_4uyqsoTLUFko2rc",  # Anirban Mukherjee: biotechnology.
        "R-R_525aqafDBlUUR5b",  # Hyoungchul Kim: high h-index/common-name risk.
        "R-R_5BnQrc3zjl7F9QU",  # Alain Pineda: electronic engineering.
        "R-R_5bTQAFcivjTDjHI",  # Michael Bailey: known contaminated profile risk.
    }
)
SUSPICIOUS_AFFILIATION_TERMS = (
    "biotechnology",
    "civil engineering",
    "computer vision",
    "computing and information systems",
    "earth systems",
    "electronic engineering",
    "electrónico",
    "geoscience",
    "global change",
    "kinesiology",
    "mechanics",
    "nuclear",
)
COMMON_NAME_LAST_NAMES = frozenset(
    {
        "bailey",
        "baker",
        "chen",
        "clarke",
        "gonzalez",
        "huang",
        "kim",
        "li",
        "martinez",
        "mukherjee",
        "pineda",
        "wang",
        "yang",
        "zhang",
        "zhao",
    }
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-infobars",
]
MAX_SCHOLAR_ATTEMPTS = 3
BROWSER_RESTART_PAUSE_RANGE = (20.0, 35.0)

ARROW = "\u2192"
EM_DASH = "\u2014"


@dataclass(frozen=True)
class Scholar:
    node_id: str
    full_name: str
    last_name: str
    employer: str
    phd_institution: str


@dataclass(frozen=True)
class Candidate:
    name: str
    profile_url: str
    affiliation: str
    email_domain: str


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_project_path(path_str: str | None, default_relative: Path) -> Path:
    root = project_root()
    path = Path(path_str) if path_str else root / default_relative
    return path if path.is_absolute() else root / path


def resolve_optional_path(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    path = Path(path_str).expanduser()
    return path if path.is_absolute() else project_root() / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Google Scholar bibliometrics for remaining Gen 2 scholars."
    )
    parser.add_argument(
        "--csv",
        default=None,
        help=f"Partial/output CSV path (default: {DEFAULT_CSV_REL})",
    )
    parser.add_argument(
        "--nodes",
        default=None,
        help=f"Network nodes CSV path (default: {DEFAULT_NODES_REL})",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help=f"Persistent Playwright profile dir (default: {DEFAULT_PROFILE_DIR})",
    )
    parser.add_argument(
        "--manual-warmup",
        action="store_true",
        help="Open Google Scholar and wait for Enter before scraping.",
    )
    return parser.parse_args()


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFD", value)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower()
    alnum_spaces = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    return re.sub(r"\s+", " ", alnum_spaces).strip()


def parse_int(value: str | None) -> int:
    if not value:
        return 0
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else 0


def compact_name(name: str) -> str:
    return normalize_text(name).replace(" ", "")


def long_tokens(text: str) -> set[str]:
    return {token for token in normalize_text(text).split() if len(token) > 3}


def last_name_in_candidate(candidate_name: str, expected_last_name: str) -> bool:
    last = normalize_text(expected_last_name)
    candidate = normalize_text(candidate_name)
    if not last or not candidate:
        return False
    return f" {last} " in f" {candidate} "


def affiliation_matches_expected_employer(candidate_affiliation: str, employer: str) -> bool:
    employer_tokens = long_tokens(employer)
    if not employer_tokens:
        return False
    affiliation_tokens = set(normalize_text(candidate_affiliation).split())
    return bool(employer_tokens & affiliation_tokens)


def has_suspicious_affiliation(affiliation: str) -> bool:
    normalized = normalize_text(affiliation)
    return any(normalize_text(term) in normalized for term in SUSPICIOUS_AFFILIATION_TERMS)


def has_vague_affiliation(affiliation: str) -> bool:
    normalized = normalize_text(affiliation)
    return not normalized or "unknown affiliation" in normalized


def suspicious_mismatch_indicator(
    scholar: Scholar,
    quality: str,
    stats: dict[str, int] | None = None,
    affiliation: str = "",
) -> str:
    if scholar.node_id in SUSPICIOUS_MISMATCH_NODE_IDS:
        return "1"
    if quality == "false_positive":
        return "1"
    if quality != "match":
        return "0"
    if has_suspicious_affiliation(affiliation):
        return "1"

    stats = stats or {}
    citations_all = stats.get("citations_all", 0)
    h_index_all = stats.get("h_index_all", 0)
    common_last_name = normalize_text(scholar.last_name) in COMMON_NAME_LAST_NAMES
    high_bibliometrics = citations_all >= 10000 or h_index_all >= 40
    if high_bibliometrics and (common_last_name or has_vague_affiliation(affiliation)):
        return "1"

    return "0"


def load_gen2_scholars(nodes_path: Path) -> list[Scholar]:
    with nodes_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {
            "node_id",
            "first_name",
            "last_name",
            "generation",
            "current_employer_raw",
            "current_employer_canon",
            "phd_institution_raw",
            "phd_institution_canon",
        }
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"{nodes_path} is missing required columns: {', '.join(missing)}")

        scholars: list[Scholar] = []
        for row in reader:
            if (row.get("generation") or "").strip() != GENERATION:
                continue

            first_name = (row.get("first_name") or "").strip()
            last_name = (row.get("last_name") or "").strip()
            full_name = " ".join(part for part in (first_name, last_name) if part).strip()
            if not full_name:
                full_name = (row.get("node_id") or "").strip()

            scholars.append(
                Scholar(
                    node_id=(row.get("node_id") or "").strip(),
                    full_name=full_name,
                    last_name=last_name or (full_name.split()[-1] if full_name.split() else ""),
                    employer=(
                        (row.get("current_employer_canon") or "").strip()
                        or (row.get("current_employer_raw") or "").strip()
                    ),
                    phd_institution=(
                        (row.get("phd_institution_canon") or "").strip()
                        or (row.get("phd_institution_raw") or "").strip()
                    ),
                )
            )
    return scholars


def ensure_output_csv(path: Path) -> set[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(OUTPUT_FIELDS)
        return set()

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != OUTPUT_FIELDS:
            raise ValueError(
                f"{path} has unexpected header:\n"
                f"  found:    {reader.fieldnames}\n"
                f"  expected: {OUTPUT_FIELDS}"
            )
        completed = {row["node_id"] for row in reader if row.get("node_id")}

    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() > 0:
            f.seek(-1, os.SEEK_END)
            needs_newline = f.read(1) != b"\n"
        else:
            needs_newline = False
    if needs_newline:
        with path.open("ab") as f:
            f.write(b"\n")

    return completed


def not_found_row(scholar: Scholar) -> dict[str, Any]:
    return {
        "node_id": scholar.node_id,
        "name": scholar.full_name,
        "in_gs": False,
        "quality": "not_found",
        "gs_suspicious_mismatch": suspicious_mismatch_indicator(scholar, "not_found"),
        "gs_profile_url": "",
        "citations_all": 0,
        "citations_recent": 0,
        "h_index_all": 0,
        "h_index_recent": 0,
        "i10_all": 0,
        "i10_recent": 0,
        "affiliation": "",
    }


def match_row(
    scholar: Scholar,
    profile_url: str,
    stats: dict[str, int],
    affiliation: str,
) -> dict[str, Any]:
    return {
        "node_id": scholar.node_id,
        "name": scholar.full_name,
        "in_gs": True,
        "quality": "match",
        "gs_suspicious_mismatch": suspicious_mismatch_indicator(
            scholar, "match", stats, affiliation
        ),
        "gs_profile_url": profile_url,
        "citations_all": stats["citations_all"],
        "citations_recent": stats["citations_recent"],
        "h_index_all": stats["h_index_all"],
        "h_index_recent": stats["h_index_recent"],
        "i10_all": stats["i10_all"],
        "i10_recent": stats["i10_recent"],
        "affiliation": affiliation,
    }


def search_url(full_name: str) -> str:
    return (
        "https://scholar.google.com/citations?"
        f"view_op=search_authors&mauthors={quote_plus(full_name)}&hl=en"
    )


def has_captcha(page: Any) -> bool:
    if "google.com/sorry" in page.url.lower():
        return True
    try:
        body_text = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        body_text = ""
    return "unusual traffic" in body_text


def has_interactive_challenge(page: Any) -> bool:
    selectors = (
        "iframe[src*='recaptcha']",
        "iframe[title*='reCAPTCHA']",
        "#captcha",
        "input[name='captcha']",
        "form[action*='sorry'] input[type='submit']",
    )
    for selector in selectors:
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    return False


def exit_on_captcha(page: Any, scholar: Scholar) -> None:
    if not has_captcha(page):
        return

    if not has_interactive_challenge(page):
        print(
            f"Google Scholar hard unusual-traffic block while processing "
            f"{scholar.full_name} ({scholar.node_id}). No interactive CAPTCHA "
            "challenge was detected. Stop and rerun later; the partial CSV is "
            "intact up to the last completed scholar.",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(2)

    print(
        f"CAPTCHA/unusual traffic detected while processing {scholar.full_name} "
        f"({scholar.node_id}). Solve it in the browser, then press Enter here "
        "to retry this scholar.",
        file=sys.stderr,
        flush=True,
    )
    try:
        input()
    except EOFError:
        print("No stdin available for CAPTCHA solve; exiting.", file=sys.stderr, flush=True)
        raise SystemExit(2)

    page.goto(search_url(scholar.full_name), wait_until="domcontentloaded", timeout=60000)
    time.sleep(random.uniform(8.0, 13.0))
    if has_captcha(page):
        print(
            "CAPTCHA/unusual traffic is still present. Exiting now; the partial "
            "CSV is intact up to the last completed scholar.",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(2)


def maybe_text(locator: Any, timeout: int = 3000) -> str:
    try:
        if locator.count() == 0:
            return ""
        return locator.first.inner_text(timeout=timeout).strip()
    except Exception:
        return ""


def maybe_attribute(locator: Any, attr: str, timeout: int = 3000) -> str:
    try:
        if locator.count() == 0:
            return ""
        return (locator.first.get_attribute(attr, timeout=timeout) or "").strip()
    except Exception:
        return ""


def extract_search_candidates(page: Any) -> list[Candidate]:
    cards = page.locator(".gs_ai_t")
    candidates: list[Candidate] = []
    for index in range(min(cards.count(), 4)):
        card = cards.nth(index)
        name_link = card.locator(".gs_ai_name a")
        name = maybe_text(name_link)
        href = maybe_attribute(name_link, "href")
        profile_url = urljoin("https://scholar.google.com", href) if href else ""
        if not name or not profile_url:
            continue
        candidates.append(
            Candidate(
                name=name,
                profile_url=profile_url,
                affiliation=maybe_text(card.locator(".gs_ai_aff")),
                email_domain=maybe_text(card.locator(".gs_ai_eml")),
            )
        )
    return candidates


def find_best_candidate(scholar: Scholar, candidates: list[Candidate]) -> Candidate | None:
    short_last_name = len(compact_name(scholar.last_name)) <= 3
    for candidate in candidates:
        if not last_name_in_candidate(candidate.name, scholar.last_name):
            continue
        if short_last_name and not affiliation_matches_expected_employer(
            candidate.affiliation, scholar.employer
        ):
            continue
        return candidate
    return None


def extract_stat_cell(page: Any, row_index: int, col_index: int) -> int:
    try:
        row = page.locator("#gsc_rsb_st tr").nth(row_index)
        cell = row.locator("td").nth(col_index)
        return parse_int(cell.inner_text(timeout=3000))
    except Exception:
        return 0


def extract_profile_stats(page: Any) -> dict[str, int]:
    return {
        "citations_all": extract_stat_cell(page, 1, 1),
        "citations_recent": extract_stat_cell(page, 1, 2),
        "h_index_all": extract_stat_cell(page, 2, 1),
        "h_index_recent": extract_stat_cell(page, 2, 2),
        "i10_all": extract_stat_cell(page, 3, 1),
        "i10_recent": extract_stat_cell(page, 3, 2),
    }


def extract_profile_affiliation(page: Any) -> str:
    for selector in ("#gsc_prf_i .gsc_prf_il", ".gsc_prf_il", "#gsc_prf_in"):
        text = maybe_text(page.locator(selector))
        if text:
            return text
    return ""


def scrape_scholar(page: Any, scholar: Scholar) -> dict[str, Any]:
    page.goto(search_url(scholar.full_name), wait_until="domcontentloaded", timeout=60000)
    time.sleep(random.uniform(8.0, 13.0))
    exit_on_captcha(page, scholar)

    candidates = extract_search_candidates(page)
    best = find_best_candidate(scholar, candidates)
    if not best:
        return not_found_row(scholar)

    page.goto(best.profile_url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(random.uniform(5.0, 9.0))
    exit_on_captcha(page, scholar)

    stats = extract_profile_stats(page)
    affiliation = extract_profile_affiliation(page) or best.affiliation
    return match_row(scholar, best.profile_url, stats, affiliation)


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def log_result(index: int, total: int, row: dict[str, Any], timing_info: str = "") -> None:
    if row["quality"] == "match":
        suffix = (
            f" (citations: {row['citations_all']}, h: {row['h_index_all']}) "
            f"{EM_DASH} {row['affiliation']}"
        )
    else:
        suffix = ""
    print(f"[{index}/{total}] {row['name']} {ARROW} {row['quality']}{suffix}{timing_info}", flush=True)


def pause_every_10(page: Any, processed_this_run: int, remaining_count: int) -> None:
    if processed_this_run == 0 or processed_this_run % 10 != 0:
        return
    if processed_this_run >= remaining_count:
        return
    page.goto("https://scholar.google.com", wait_until="domcontentloaded", timeout=60000)
    time.sleep(random.uniform(20.0, 35.0))


def active_page(context: Any) -> Any:
    pages = []
    for page in context.pages:
        try:
            if not page.is_closed():
                pages.append(page)
        except Exception:
            continue
    for page in reversed(pages):
        try:
            page_url = page.url.lower()
        except Exception:
            continue
        if "scholar.google." in page_url:
            return page
    return pages[-1] if pages else context.new_page()


def open_browser_session(playwright: Any, profile_dir: Path | None) -> tuple[Any | None, Any, Any]:
    if profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            args=CHROMIUM_ARGS,
            ignore_default_args=["--enable-automation"],
            user_agent=USER_AGENT,
        )
        page = active_page(context)
        browser = None
    else:
        browser = playwright.chromium.launch(
            headless=False,
            args=CHROMIUM_ARGS,
            ignore_default_args=["--enable-automation"],
        )
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

    stealth_sync(page)
    page.goto("https://scholar.google.com", wait_until="domcontentloaded", timeout=60000)
    time.sleep(random.uniform(4.0, 7.0))
    return browser, context, page


def close_browser_session(context: Any | None, browser: Any | None) -> None:
    for resource in (context, browser):
        if resource is None:
            continue
        try:
            resource.close()
        except Exception:
            pass


def short_error(exc: BaseException) -> str:
    return str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__


def wait_for_manual_warmup() -> None:
    print(
        "Manual warmup enabled. Complete login or CAPTCHA in the browser, "
        "then press Enter here to start scraping.",
        flush=True,
    )
    try:
        input()
    except EOFError:
        print("No stdin available for manual warmup; continuing.", file=sys.stderr, flush=True)


def run_scraper(
    nodes_path: Path,
    csv_path: Path,
    profile_dir: Path | None,
    manual_warmup: bool,
) -> int:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed for this Python environment. "
            "Install it before running the scraper, for example: "
            "python3 -m pip install playwright && python3 -m playwright install chromium"
        ) from exc

    scholars = load_gen2_scholars(nodes_path)
    completed = ensure_output_csv(csv_path)
    remaining = [scholar for scholar in scholars if scholar.node_id not in completed]

    total = len(scholars)
    print(f"Loaded {total} Gen {GENERATION} scholars.")
    print(f"Already completed: {len(completed)}")
    print(f"Remaining to process: {len(remaining)}")
    if profile_dir is not None:
        print(f"Using persistent browser profile: {profile_dir}")
    if not remaining:
        return 0

    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None

        try:
            browser, context, page = open_browser_session(playwright, profile_dir)
            if manual_warmup:
                wait_for_manual_warmup()
                if profile_dir is not None:
                    close_browser_session(context, browser)
                    browser = None
                    context = None
                    page = None
                    time.sleep(2.0)
                    browser, context, page = open_browser_session(playwright, profile_dir)
                else:
                    page = active_page(context)
            with csv_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
                processed_this_run = 0
                start_time = time.time()
                for scholar in remaining:
                    row = None
                    for attempt in range(1, MAX_SCHOLAR_ATTEMPTS + 1):
                        try:
                            row = scrape_scholar(page, scholar)
                            break
                        except PlaywrightError as exc:
                            close_browser_session(context, browser)
                            if attempt >= MAX_SCHOLAR_ATTEMPTS:
                                raise
                            pause_seconds = random.uniform(*BROWSER_RESTART_PAUSE_RANGE)
                            print(
                                f"Browser/navigation error for {scholar.full_name}; "
                                f"retrying attempt {attempt + 1}/{MAX_SCHOLAR_ATTEMPTS} "
                                f"after {pause_seconds:.1f}s: {short_error(exc)}",
                                file=sys.stderr,
                                flush=True,
                            )
                            time.sleep(pause_seconds)
                            browser, context, page = open_browser_session(playwright, profile_dir)

                    if row is None:
                        raise RuntimeError(f"No row produced for {scholar.full_name}")

                    writer.writerow(row)
                    f.flush()
                    os.fsync(f.fileno())

                    processed_this_run += 1
                    progress_index = len(completed) + processed_this_run
                    elapsed_seconds = time.time() - start_time
                    avg_seconds_per_scholar = elapsed_seconds / processed_this_run
                    scholars_remaining = len(remaining) - processed_this_run
                    estimated_remaining = avg_seconds_per_scholar * scholars_remaining
                    timing_info = (
                        f"  (elapsed: {format_duration(elapsed_seconds)}, "
                        f"~est. remaining: {format_duration(estimated_remaining)})"
                    )
                    log_result(progress_index, total, row, timing_info)
                    try:
                        pause_every_10(page, processed_this_run, len(remaining))
                    except PlaywrightError as exc:
                        close_browser_session(context, browser)
                        pause_seconds = random.uniform(*BROWSER_RESTART_PAUSE_RANGE)
                        print(
                            f"Browser/navigation error during homepage reset; "
                            f"restarting after {pause_seconds:.1f}s: {short_error(exc)}",
                            file=sys.stderr,
                            flush=True,
                        )
                        time.sleep(pause_seconds)
                        browser, context, page = open_browser_session(playwright, profile_dir)
        finally:
            close_browser_session(context, browser)

    return 0


def main() -> int:
    args = parse_args()
    nodes_path = resolve_project_path(args.nodes, DEFAULT_NODES_REL)
    csv_path = resolve_project_path(args.csv, DEFAULT_CSV_REL)
    profile_dir = resolve_optional_path(args.profile_dir)
    return run_scraper(nodes_path, csv_path, profile_dir, args.manual_warmup)


if __name__ == "__main__":
    raise SystemExit(main())
