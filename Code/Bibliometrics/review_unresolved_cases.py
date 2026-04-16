#!/usr/bin/env python3
"""Use Claude to recommend decisions for unresolved OpenAlex cases."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CODE_ROOT = PROJECT_ROOT / "Code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from Bibliometrics.openalex_review_pipeline import (  # noqa: E402
    APPROVE_ACTION,
    DECISION_FIELDNAMES,
    DEFER_ACTION,
    REJECT_ACTION,
    canonical_decision_for_action,
    filter_matches_by_status,
    load_review_snapshot,
    normalize_openalex_id,
    parse_status_list,
    proposed_openalex_id_for_action,
    safe_float,
    safe_int,
    split_flags,
    top_papers_for_node_author,
    write_csv,
)


RECOMMENDATION_FIELDS = DECISION_FIELDNAMES + [
    "source_date",
    "match_status",
    "review_notes",
    "suspicious_flags",
    "selected_openalex_id",
    "selected_display_name",
    "selected_candidate_score",
    "selected_candidate_current_institution",
    "selected_candidate_institutions",
    "selected_candidate_works_count",
    "selected_candidate_cited_by_count",
    "selected_candidate_h_index",
    "candidate_preview",
    "current_top_papers_preview",
    "claude_action",
    "claude_confidence",
    "claude_note",
    "claude_model",
]
ALLOWED_ACTIONS = {APPROVE_ACTION, REJECT_ACTION, DEFER_ACTION}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}

SYSTEM_PROMPT = """You recommend OpenAlex author-match decisions for a research genealogy dataset.
Use only the supplied evidence.
Be conservative. If the evidence is materially ambiguous, defer instead of forcing a match.
Allowed action values:
- approve_selected: choose one candidate from the supplied candidate list
- no_match: reject all supplied candidates
- defer: leave the row for further manual review
If action is approve_selected, selected_openalex_id must be one of the candidate openalex_id values.
If action is no_match or defer, selected_openalex_id must be an empty string.
Allowed confidence values: high, medium, low.
The note must be one sentence.
Use the provided client tool to submit your recommendation."""
RECOMMENDATION_TOOL = {
    "name": "submit_recommendation",
    "description": (
        "Submit the final recommendation for one unresolved OpenAlex scholar-match case. "
        "Use approve_selected only when one candidate from the supplied list is clearly defensible. "
        "Use no_match when the supplied candidates do not match the scholar. "
        "Use defer when uncertainty remains material. "
        "selected_openalex_id must be one of the supplied candidate IDs only when action is approve_selected."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [APPROVE_ACTION, REJECT_ACTION, DEFER_ACTION],
            },
            "selected_openalex_id": {
                "type": "string",
                "description": "Selected candidate OpenAlex ID, or empty string for no_match/defer.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "note": {
                "type": "string",
                "description": "One-sentence explanation for the recommendation.",
            },
        },
        "required": ["action", "selected_openalex_id", "confidence", "note"],
        "additionalProperties": False,
    },
}


class ReviewClient:
    def review(self, evidence: dict[str, Any]) -> dict[str, str]:
        raise NotImplementedError


class MockReviewClient(ReviewClient):
    def review(self, evidence: dict[str, Any]) -> dict[str, str]:
        candidates = evidence.get("candidate_preview", [])
        current_id = normalize_openalex_id(evidence.get("current_match", {}).get("openalex_id", ""))
        if not candidates:
            return recommendation_result(DEFER_ACTION, "", "low", "No candidate evidence was available, so this row remains deferred.")

        first = candidates[0]
        first_id = normalize_openalex_id(first.get("openalex_id", ""))
        first_score = safe_float(first.get("candidate_score", ""))
        second_score = safe_float(candidates[1].get("candidate_score", "")) if len(candidates) > 1 else 0.0
        if first_score >= 0.95 or (first_score >= 0.9 and first_score - second_score >= 0.08):
            return recommendation_result(
                APPROVE_ACTION,
                first_id,
                "medium",
                "The top candidate has the clearest evidence among the supplied options.",
            )
        if first_score <= 0.35:
            return recommendation_result(
                REJECT_ACTION,
                "",
                "medium",
                "None of the supplied candidates looks strong enough to approve.",
            )
        if current_id and first_id == current_id and first_score >= 0.85:
            return recommendation_result(
                APPROVE_ACTION,
                first_id,
                "medium",
                "The current provisional match still appears to be the strongest available option.",
            )
        return recommendation_result(
            DEFER_ACTION,
            "",
            "low",
            "The supplied evidence is ambiguous enough that this row should stay in manual review.",
        )


class AnthropicReviewClient(ReviewClient):
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 90.0) -> None:
        if not api_key:
            raise ValueError("Anthropic API key is required for provider=anthropic.")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def review(self, evidence: dict[str, Any]) -> dict[str, str]:
        body = {
            "model": self.model,
            "max_tokens": 220,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "tools": [RECOMMENDATION_TOOL],
            "tool_choice": {"type": "tool", "name": RECOMMENDATION_TOOL["name"]},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": build_user_prompt(evidence),
                        }
                    ],
                }
            ],
        }
        request = Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Anthropic request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Anthropic returned invalid JSON: {exc}") from exc

        for block in response_payload.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == RECOMMENDATION_TOOL["name"]:
                tool_input = block.get("input", {})
                if not isinstance(tool_input, dict):
                    raise RuntimeError("Anthropic tool_use block did not contain an input object.")
                return recommendation_result(
                    str(tool_input.get("action", "") or "").strip(),
                    str(tool_input.get("selected_openalex_id", "") or "").strip(),
                    str(tool_input.get("confidence", "") or "").strip().lower(),
                    str(tool_input.get("note", "") or "").strip(),
                )

        text_blocks = []
        for block in response_payload.get("content", []):
            if block.get("type") == "text":
                text_blocks.append(block.get("text", ""))
        if not text_blocks:
            raise RuntimeError("Anthropic response did not include any text blocks.")
        return parse_recommendation_response("\n".join(text_blocks))


def recommendation_result(
    action: str,
    selected_openalex_id: str,
    confidence: str,
    note: str,
) -> dict[str, str]:
    clean_action = action if action in ALLOWED_ACTIONS else DEFER_ACTION
    clean_selected_id = normalize_openalex_id(selected_openalex_id)
    clean_confidence = confidence if confidence in ALLOWED_CONFIDENCE else "low"
    clean_note = " ".join((note or "").strip().split()) or "Claude returned an empty note."
    return {
        "claude_action": clean_action,
        "selected_openalex_id": clean_selected_id,
        "claude_confidence": clean_confidence,
        "claude_note": clean_note,
    }


def build_user_prompt(evidence: dict[str, Any]) -> str:
    return (
        "Review this unresolved OpenAlex author-match case and recommend the next action.\n"
        "Choose approve_selected only when one candidate is clearly defensible from the evidence.\n"
        "Prefer defer when multiple candidates remain plausible.\n\n"
        "Evidence JSON:\n"
        f"{json.dumps(evidence, ensure_ascii=False, indent=2)}"
    )


def parse_recommendation_response(text: str) -> dict[str, str]:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", stripped)
        stripped = re.sub(r"\n```$", "", stripped)

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    candidate = match.group(0) if match else stripped
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse recommendation JSON from response: {text}") from exc

    action = str(payload.get("action", "") or "").strip()
    selected_id = str(payload.get("selected_openalex_id", "") or "").strip()
    confidence = str(payload.get("confidence", "") or "").strip().lower()
    note = str(payload.get("note", "") or "").strip()
    return recommendation_result(action, selected_id, confidence, note)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Use Claude to recommend decisions for unresolved OpenAlex rows")
    parser.add_argument("--date", default=None, help="Date suffix for snapshot files (MMDDYY)")
    parser.add_argument("--matches", default=None, help="Optional path to OpenAlex_Scholar_Matches CSV")
    parser.add_argument("--review", default=None, help="Optional path to OpenAlex_Match_Review CSV")
    parser.add_argument("--top-papers", default=None, help="Optional path to OpenAlex_Top_Papers CSV")
    parser.add_argument(
        "--status",
        default="needs_manual_review,ambiguous_manual_review",
        help="Comma-separated unresolved statuses to include",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional row limit for smoke tests")
    parser.add_argument(
        "--provider",
        default="anthropic",
        choices=("anthropic", "mock"),
        help="Recommendation provider (default: anthropic)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Anthropic API key (default: ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--model",
        default="claude-opus-4-6",
        help="Anthropic model name",
    )
    parser.add_argument("--batch-size", type=int, default=20, help="Rows per batch before sleeping")
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.5,
        help="Sleep interval between batches",
    )
    parser.add_argument("--output", default=None, help="Optional recommendations CSV path")
    parser.add_argument("--followup-output", default=None, help="Optional low-confidence/deferred CSV path")
    return parser


def preview_candidates(snapshot: Any, node_id: str) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for candidate in snapshot.review_by_node.get(node_id, []):
        candidate_id = normalize_openalex_id(candidate.get("candidate_openalex_id", ""))
        candidate_top_papers = top_papers_for_node_author(snapshot, node_id=node_id, openalex_id=candidate_id)
        preview.append(
            {
                "rank": (candidate.get("candidate_rank", "") or "").strip(),
                "openalex_id": candidate_id,
                "display_name": (candidate.get("candidate_display_name", "") or "").strip(),
                "candidate_score": (candidate.get("candidate_score", "") or "").strip(),
                "name_match_type": (candidate.get("name_match_type", "") or "").strip(),
                "name_score": (candidate.get("name_score", "") or "").strip(),
                "institution_score": (candidate.get("institution_score", "") or "").strip(),
                "timing_score": (candidate.get("timing_score", "") or "").strip(),
                "timing_note": (candidate.get("timing_note", "") or "").strip(),
                "institution_matches": (candidate.get("institution_matches", "") or "").strip(),
                "current_institution": (candidate.get("candidate_current_institution", "") or "").strip(),
                "institutions": (candidate.get("candidate_institutions", "") or "").strip(),
                "works_count": (candidate.get("candidate_works_count", "") or "").strip(),
                "cited_by_count": (candidate.get("candidate_cited_by_count", "") or "").strip(),
                "h_index": (candidate.get("candidate_h_index", "") or "").strip(),
                "top_papers_preview": [
                    {
                        "title": (paper.get("title", "") or "").strip(),
                        "publication_year": (paper.get("publication_year", "") or "").strip(),
                        "cited_by_count": (paper.get("cited_by_count", "") or "").strip(),
                    }
                    for paper in candidate_top_papers[:3]
                ],
            }
        )
    return preview


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


def current_match_context(snapshot: Any, match_row: dict[str, str]) -> dict[str, Any]:
    node_id = (match_row.get("node_id", "") or "").strip()
    current_id = normalize_openalex_id(match_row.get("openalex_id", ""))
    top_papers = top_papers_for_node_author(snapshot, node_id=node_id, openalex_id=current_id)
    return {
        "openalex_id": current_id,
        "display_name": (match_row.get("openalex_display_name", "") or "").strip(),
        "works_count": (match_row.get("works_count", "") or "").strip(),
        "cited_by_count": (match_row.get("cited_by_count", "") or "").strip(),
        "h_index": (match_row.get("h_index", "") or "").strip(),
        "institutions": (match_row.get("matched_institutions", "") or "").strip(),
        "top_papers_preview": [
            {
                "title": (paper.get("title", "") or "").strip(),
                "publication_year": (paper.get("publication_year", "") or "").strip(),
                "cited_by_count": (paper.get("cited_by_count", "") or "").strip(),
            }
            for paper in top_papers[:3]
        ],
    }


def build_evidence(snapshot: Any, match_row: dict[str, str]) -> dict[str, Any]:
    node_id = (match_row.get("node_id", "") or "").strip()
    return {
        "source_date": snapshot.paths.date_token,
        "scholar": {
            "node_id": node_id,
            "full_name": (match_row.get("full_name", "") or "").strip(),
            "generation": (match_row.get("generation", "") or "").strip(),
            "advisor": (match_row.get("advisor", "") or "").strip(),
            "phd_institution": (match_row.get("phd_institution", "") or "").strip(),
            "phd_year": (match_row.get("phd_year", "") or "").strip(),
            "current_employer": (match_row.get("current_employer", "") or "").strip(),
            "match_status": (match_row.get("match_status", "") or "").strip(),
            "review_notes": (match_row.get("review_notes", "") or "").strip(),
            "suspicious_flags": split_flags(match_row.get("suspicious_flags", "")),
            "candidate_count": (match_row.get("candidate_count", "") or "").strip(),
        },
        "current_match": current_match_context(snapshot, match_row),
        "candidate_preview": preview_candidates(snapshot, node_id),
    }


def select_client(args: argparse.Namespace) -> ReviewClient:
    if args.provider == "mock":
        return MockReviewClient()
    try:
        return AnthropicReviewClient(api_key=args.api_key, model=args.model)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def candidate_lookup(snapshot: Any, node_id: str, selected_openalex_id: str) -> dict[str, str]:
    selected_id = normalize_openalex_id(selected_openalex_id)
    if not selected_id:
        return {
            "selected_openalex_id": "",
            "selected_display_name": "",
            "selected_candidate_score": "",
            "selected_candidate_current_institution": "",
            "selected_candidate_institutions": "",
            "selected_candidate_works_count": "",
            "selected_candidate_cited_by_count": "",
            "selected_candidate_h_index": "",
        }

    candidate = snapshot.review_by_node_candidate.get((node_id, selected_id))
    if not candidate:
        return {
            "selected_openalex_id": selected_id,
            "selected_display_name": "",
            "selected_candidate_score": "",
            "selected_candidate_current_institution": "",
            "selected_candidate_institutions": "",
            "selected_candidate_works_count": "",
            "selected_candidate_cited_by_count": "",
            "selected_candidate_h_index": "",
        }

    return {
        "selected_openalex_id": selected_id,
        "selected_display_name": (candidate.get("candidate_display_name", "") or "").strip(),
        "selected_candidate_score": (candidate.get("candidate_score", "") or "").strip(),
        "selected_candidate_current_institution": (
            candidate.get("candidate_current_institution", "") or ""
        ).strip(),
        "selected_candidate_institutions": (candidate.get("candidate_institutions", "") or "").strip(),
        "selected_candidate_works_count": (candidate.get("candidate_works_count", "") or "").strip(),
        "selected_candidate_cited_by_count": (candidate.get("candidate_cited_by_count", "") or "").strip(),
        "selected_candidate_h_index": (candidate.get("candidate_h_index", "") or "").strip(),
    }


def validate_recommendation(
    *,
    recommendation: dict[str, str],
    evidence: dict[str, Any],
) -> dict[str, str]:
    action = recommendation["claude_action"]
    selected_id = recommendation["selected_openalex_id"]
    candidate_ids = {
        normalize_openalex_id(candidate.get("openalex_id", ""))
        for candidate in evidence.get("candidate_preview", [])
        if normalize_openalex_id(candidate.get("openalex_id", ""))
    }

    if action == APPROVE_ACTION:
        if not selected_id or selected_id not in candidate_ids:
            return recommendation_result(
                DEFER_ACTION,
                "",
                "low",
                "Claude did not return a valid candidate choice, so this row remains deferred.",
            )
        return recommendation

    return recommendation_result(
        action,
        "",
        recommendation["claude_confidence"],
        recommendation["claude_note"],
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    statuses = parse_status_list(args.status)
    snapshot = load_review_snapshot(
        date_token=args.date,
        matches_path=args.matches,
        review_path=args.review,
        top_papers_path=args.top_papers,
    )
    unresolved_rows = filter_matches_by_status(snapshot, statuses)
    if args.limit > 0:
        unresolved_rows = unresolved_rows[: args.limit]

    client = select_client(args)
    output_path = (
        Path(args.output)
        if args.output
        else PROJECT_ROOT / "Data" / "Derived" / f"OpenAlex_Claude_Review_Recommendations_{snapshot.paths.date_token}.csv"
    )
    followup_output_path = (
        Path(args.followup_output)
        if args.followup_output
        else PROJECT_ROOT / "Data" / "Derived" / f"OpenAlex_Claude_Review_Followup_{snapshot.paths.date_token}.csv"
    )
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    if not followup_output_path.is_absolute():
        followup_output_path = PROJECT_ROOT / followup_output_path

    recommendation_rows: list[dict[str, str]] = []
    followup_rows: list[dict[str, str]] = []
    for index, match_row in enumerate(unresolved_rows, start=1):
        evidence = build_evidence(snapshot, match_row)
        try:
            recommendation = client.review(evidence)
        except Exception as exc:  # noqa: BLE001
            recommendation = recommendation_result(
                DEFER_ACTION,
                "",
                "low",
                f"Claude review failed: {exc}",
            )

        recommendation = validate_recommendation(recommendation=recommendation, evidence=evidence)
        current_id = normalize_openalex_id(match_row.get("openalex_id", ""))
        selected_id = recommendation["selected_openalex_id"]
        decision = canonical_decision_for_action(
            action=recommendation["claude_action"],
            current_openalex_id=current_id,
            selected_openalex_id=selected_id,
        )
        selected_context = candidate_lookup(
            snapshot,
            (match_row.get("node_id", "") or "").strip(),
            selected_id,
        )
        current_top_papers = summarize_top_papers(
            top_papers_for_node_author(
                snapshot,
                node_id=(match_row.get("node_id", "") or "").strip(),
                openalex_id=current_id,
            ),
            limit=3,
        )

        row = {
            "node_id": (match_row.get("node_id", "") or "").strip(),
            "full_name": (match_row.get("full_name", "") or "").strip(),
            "current_openalex_id": current_id,
            "proposed_openalex_id": proposed_openalex_id_for_action(
                action=recommendation["claude_action"],
                current_openalex_id=current_id,
                selected_openalex_id=selected_id,
            ),
            "decision": decision,
            "reason": recommendation["claude_note"],
            "reviewer": args.model,
            "source_date": snapshot.paths.date_token,
            "match_status": (match_row.get("match_status", "") or "").strip(),
            "review_notes": (match_row.get("review_notes", "") or "").strip(),
            "suspicious_flags": (match_row.get("suspicious_flags", "") or "").strip(),
            **selected_context,
            "candidate_preview": json.dumps(evidence["candidate_preview"], ensure_ascii=False),
            "current_top_papers_preview": current_top_papers,
            "claude_action": recommendation["claude_action"],
            "claude_confidence": recommendation["claude_confidence"],
            "claude_note": recommendation["claude_note"],
            "claude_model": args.model,
        }
        recommendation_rows.append(row)

        if row["decision"] == "needs_more_review" or row["claude_confidence"] != "high":
            followup_rows.append(row)

        if index % max(args.batch_size, 1) == 0 and index < len(unresolved_rows):
            print(
                f"Completed {index}/{len(unresolved_rows)} unresolved Claude reviews...",
                flush=True,
            )
            time.sleep(max(args.sleep_seconds, 0.0))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    followup_output_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(output_path, RECOMMENDATION_FIELDS, recommendation_rows)
    write_csv(followup_output_path, RECOMMENDATION_FIELDS, followup_rows)

    print(f"Snapshot date:         {snapshot.paths.date_token}")
    print(f"Statuses:              {', '.join(statuses)}")
    print(f"Rows reviewed:         {len(unresolved_rows)}")
    print(f"Recommendations CSV:   {output_path}")
    print(f"Follow-up CSV:         {followup_output_path}")
    print(
        "Decision counts:       "
        + ", ".join(
            f"{decision}={sum(1 for row in recommendation_rows if row['decision'] == decision)}"
            for decision in ("keep_match", "replace_match", "approve_match", "reject_match", "needs_more_review")
        )
    )
    print(f"Follow-up rows:        {len(followup_rows)}")


if __name__ == "__main__":
    main()
