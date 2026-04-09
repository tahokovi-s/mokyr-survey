#!/usr/bin/env python3
"""
Minimal OpenAlex CLI for bibliometric enrichment.

Read the API key from OPENALEX_API_KEY by default, or pass it explicitly with
--api-key for one-off runs.

Examples:
    export OPENALEX_API_KEY="your_key"

    python3 Code/Bibliometrics/fetch_openalex.py \
        author-search --query "Joel Mokyr"

    python3 Code/Bibliometrics/fetch_openalex.py \
        author --author-id A5103336489

    python3 Code/Bibliometrics/fetch_openalex.py \
        works-by-author --author-id A5103336489 --all-pages \
        --select id,display_name,publication_year,cited_by_count,doi
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OPENALEX_BASE_URL = "https://api.openalex.org"
DEFAULT_PER_PAGE = 25
MAX_PER_PAGE = 200


def normalize_openalex_id(raw_id: str, expected_prefix: str) -> str:
    raw_id = (raw_id or "").strip()
    if not raw_id:
        return raw_id
    if raw_id.startswith("https://openalex.org/"):
        return raw_id.rsplit("/", 1)[-1]
    if raw_id.startswith(expected_prefix):
        return raw_id
    return raw_id


def encode_params(params: dict[str, Any]) -> str:
    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        cleaned[key] = value
    return urlencode(cleaned, doseq=True, safe=":,|/")


class OpenAlexClient:
    def __init__(self, api_key: str, mailto: str | None = None) -> None:
        if not api_key:
            raise ValueError(
                "OpenAlex API key is required. Set OPENALEX_API_KEY or pass --api-key."
            )
        self.api_key = api_key
        self.mailto = (mailto or "").strip() or None

    def _build_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        base = f"{OPENALEX_BASE_URL}/{path.lstrip('/')}"
        merged = dict(params or {})
        merged["api_key"] = self.api_key
        if self.mailto:
            merged["mailto"] = self.mailto
        query = encode_params(merged)
        return f"{base}?{query}" if query else base

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
        url = self._build_url(path, params)
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "mokyr-bibliometrics-openalex/0.1",
            },
        )
        try:
            with urlopen(request) as response:
                body = response.read().decode("utf-8")
                headers = dict(response.headers.items())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            sys.exit(f"OpenAlex HTTP error {exc.code}: {detail}")
        except URLError as exc:
            sys.exit(f"OpenAlex request failed: {exc}")

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            sys.exit(f"Failed to parse OpenAlex JSON response: {exc}")
        return data, headers


def clamp_per_page(per_page: int) -> int:
    return max(1, min(per_page, MAX_PER_PAGE))


def fetch_author_search(client: OpenAlexClient, args: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {
        "search": args.query,
        "per-page": clamp_per_page(args.per_page),
        "page": args.page,
        "select": args.select,
    }
    if args.filter:
        params["filter"] = args.filter
    data, headers = client.get_json("/authors", params)
    return wrap_with_headers(data, headers)


def fetch_author(client: OpenAlexClient, args: argparse.Namespace) -> dict[str, Any]:
    author_id = normalize_openalex_id(args.author_id, "A")
    data, headers = client.get_json(f"/authors/{author_id}")
    return wrap_with_headers(data, headers)


def fetch_works_by_author(client: OpenAlexClient, args: argparse.Namespace) -> dict[str, Any]:
    author_id = normalize_openalex_id(args.author_id, "A")
    params: dict[str, Any] = {
        "filter": f"authorships.author.id:https://openalex.org/{author_id}",
        "per-page": clamp_per_page(args.per_page),
        "sort": args.sort,
        "select": args.select,
    }
    if not args.all_pages:
        params["page"] = args.page
        data, headers = client.get_json("/works", params)
        return wrap_with_headers(data, headers)

    all_results: list[dict[str, Any]] = []
    next_cursor = "*"
    pages_fetched = 0
    last_headers: dict[str, str] = {}
    while next_cursor:
        page_params = dict(params)
        page_params["cursor"] = next_cursor
        data, headers = client.get_json("/works", page_params)
        last_headers = headers
        all_results.extend(data.get("results", []))
        pages_fetched += 1
        if args.max_pages and pages_fetched >= args.max_pages:
            break
        next_cursor = data.get("meta", {}).get("next_cursor")

    return {
        "meta": {
            "pages_fetched": pages_fetched,
            "results_returned": len(all_results),
            "author_id": author_id,
            "sort": args.sort,
        },
        "results": all_results,
        "_headers": rate_limit_headers(last_headers),
    }


def rate_limit_headers(headers: dict[str, str]) -> dict[str, str]:
    wanted = [
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Credits-Used",
        "X-RateLimit-Reset",
    ]
    return {key: headers[key] for key in wanted if key in headers}


def wrap_with_headers(data: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    payload = dict(data)
    payload["_headers"] = rate_limit_headers(headers)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query the OpenAlex API")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENALEX_API_KEY", ""),
        help="OpenAlex API key (default: OPENALEX_API_KEY)",
    )
    parser.add_argument(
        "--mailto",
        default=os.environ.get("OPENALEX_MAILTO", ""),
        help="Polite pool contact email (default: OPENALEX_MAILTO)",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write JSON output",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON instead of pretty-printed JSON",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    author_search = subparsers.add_parser(
        "author-search",
        help="Search OpenAlex authors by name",
    )
    author_search.add_argument("--query", required=True, help="Author name to search")
    author_search.add_argument("--filter", help="Optional OpenAlex filter string")
    author_search.add_argument("--select", help="Optional select fields")
    author_search.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE)
    author_search.add_argument("--page", type=int, default=1)
    author_search.set_defaults(func=fetch_author_search)

    author = subparsers.add_parser(
        "author",
        help="Fetch a single OpenAlex author by ID",
    )
    author.add_argument("--author-id", required=True, help="OpenAlex author ID, e.g. A5103336489")
    author.set_defaults(func=fetch_author)

    works = subparsers.add_parser(
        "works-by-author",
        help="Fetch works for a single OpenAlex author",
    )
    works.add_argument("--author-id", required=True, help="OpenAlex author ID, e.g. A5103336489")
    works.add_argument(
        "--sort",
        default="cited_by_count:desc",
        help="OpenAlex sort string (default: cited_by_count:desc)",
    )
    works.add_argument("--select", help="Optional select fields")
    works.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE)
    works.add_argument("--page", type=int, default=1)
    works.add_argument(
        "--all-pages",
        action="store_true",
        help="Fetch all pages with cursor pagination",
    )
    works.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Optional cap when using --all-pages (0 means no cap)",
    )
    works.set_defaults(func=fetch_works_by_author)

    return parser


def write_output(payload: dict[str, Any], output_path: str | None, compact: bool) -> None:
    text = json.dumps(payload, indent=None if compact else 2, ensure_ascii=False)
    if output_path:
        path = Path(output_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + ("\n" if not compact else ""), encoding="utf-8")
        print(f"Wrote OpenAlex response to {path}", file=sys.stderr)
        return
    print(text)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    client = OpenAlexClient(api_key=args.api_key, mailto=args.mailto)
    payload = args.func(client, args)
    write_output(payload, args.output, args.compact)


if __name__ == "__main__":
    main()
