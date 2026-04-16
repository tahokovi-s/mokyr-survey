#!/usr/bin/env python3
"""Audit exported OpenAlex reviewer decisions against the dated snapshot."""

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
    DECISION_FIELDNAMES,
    decision_selected_openalex_id,
    extract_date_token,
    load_review_snapshot,
    normalize_openalex_id,
    read_decisions_csv,
    safe_float,
    safe_int,
    split_flags,
    summarize_top_papers,
    top_papers_for_node_author,
    write_csv,
)


AUDITED_FIELDS = DECISION_FIELDNAMES + [
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
    "top_papers_preview",
    "audit_verdict",
    "audit_confidence",
    "audit_note",
]
AUDIT_VERDICTS = {"ok", "flag"}
AUDIT_CONFIDENCE = {"high", "medium", "low"}
SYSTEM_PROMPT = """You audit human OpenAlex author-match decisions for a research genealogy dataset.
Be conservative: flag only if there is a meaningful risk the human decision is wrong, mismatched, or contaminated.
Focus on the supplied evidence only.
Return exactly one JSON object with keys verdict, confidence, and note.
Allowed verdict values: ok, flag.
Allowed confidence values: high, medium, low.
The note must be one sentence."""


class AuditClient:
    def audit(self, evidence: dict[str, Any]) -> dict[str, str]:
        raise NotImplementedError


class MockAuditClient(AuditClient):
    def audit(self, evidence: dict[str, Any]) -> dict[str, str]:
        decision = evidence["decision"]["decision"]
        flags = set(evidence["scholar"]["suspicious_flags"])
        selected = evidence.get("selected_candidate") or {}
        selected_works = safe_int(selected.get("works_count", ""))
        candidate_preview = evidence.get("candidate_preview", [])

        if decision in {"keep_match", "approve_match", "replace_match"}:
            if "name_mismatch_warning" in flags:
                return audit_result("flag", "high", "Name compatibility looks risky for an approved match.")
            if "temporal_implausibility" in flags:
                return audit_result("flag", "high", "Publication timing looks implausible for the approved profile.")
            if selected_works > 300:
                return audit_result("flag", "medium", "The approved profile is unusually large and could be contaminated.")
            if "field_mismatch" in flags and selected_works:
                return audit_result("flag", "medium", "The approved profile still carries a field-mismatch warning and needs a quick re-check.")
            return audit_result("ok", "medium", "No clear contradiction appears in the supplied approval evidence.")

        if decision == "reject_match":
            for candidate in candidate_preview[:2]:
                if safe_float(candidate.get("candidate_score", 0)) >= 0.95 and candidate.get("institution_matches", ""):
                    return audit_result("flag", "medium", "A high-scoring candidate also has institution support, so the rejection should be re-checked.")
            return audit_result("ok", "medium", "The rejection does not show an obviously stronger candidate in the provided evidence.")

        return audit_result("ok", "low", "This row was not audited because it remains deferred.")


class AnthropicAuditClient(AuditClient):
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        if not api_key:
            raise ValueError("Anthropic API key is required for provider=anthropic.")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def audit(self, evidence: dict[str, Any]) -> dict[str, str]:
        body = {
            "model": self.model,
            "max_tokens": 180,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
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

        text_blocks = []
        for block in response_payload.get("content", []):
            if block.get("type") == "text":
                text_blocks.append(block.get("text", ""))
        if not text_blocks:
            raise RuntimeError("Anthropic response did not include any text blocks.")
        return parse_audit_response("\n".join(text_blocks))


def audit_result(verdict: str, confidence: str, note: str) -> dict[str, str]:
    clean_verdict = verdict if verdict in AUDIT_VERDICTS else "flag"
    clean_confidence = confidence if confidence in AUDIT_CONFIDENCE else "low"
    clean_note = " ".join((note or "").strip().split()) or "Audit response was empty."
    return {
        "audit_verdict": clean_verdict,
        "audit_confidence": clean_confidence,
        "audit_note": clean_note,
    }


def build_user_prompt(evidence: dict[str, Any]) -> str:
    return (
        "Audit this human OpenAlex decision. Flag only meaningful mismatch or contamination risk.\n"
        "Specific checks:\n"
        "1. Approved row with name mismatch warning.\n"
        "2. Approved row with field mismatch.\n"
        "3. Approved row with temporal implausibility.\n"
        "4. Rejected row where a strong name+institution candidate exists.\n"
        "5. Approved row that looks like a mega-profile or contaminated profile.\n\n"
        "Evidence JSON:\n"
        f"{json.dumps(evidence, ensure_ascii=False, indent=2)}"
    )


def parse_audit_response(text: str) -> dict[str, str]:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", stripped)
        stripped = re.sub(r"\n```$", "", stripped)

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    candidate = match.group(0) if match else stripped
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse audit JSON from response: {text}") from exc

    verdict = str(payload.get("verdict", "") or "").strip().lower()
    confidence = str(payload.get("confidence", "") or "").strip().lower()
    note = str(payload.get("note", "") or "").strip()
    return audit_result(verdict, confidence, note)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit exported OpenAlex review decisions")
    parser.add_argument("--decisions", required=True, help="Path to exported reviewer decisions CSV")
    parser.add_argument("--date", default=None, help="Date suffix for snapshot files (MMDDYY)")
    parser.add_argument("--matches", default=None, help="Optional path to OpenAlex_Scholar_Matches CSV")
    parser.add_argument("--review", default=None, help="Optional path to OpenAlex_Match_Review CSV")
    parser.add_argument("--top-papers", default=None, help="Optional path to OpenAlex_Top_Papers CSV")
    parser.add_argument(
        "--provider",
        default="anthropic",
        choices=("anthropic", "mock"),
        help="Audit provider (default: anthropic)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Anthropic API key (default: ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Anthropic model name",
    )
    parser.add_argument("--batch-size", type=int, default=20, help="Rows per audit batch")
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.5,
        help="Sleep interval between audit batches",
    )
    parser.add_argument(
        "--skip-needs-more-review",
        dest="skip_needs_more_review",
        action="store_true",
        default=True,
        help="Skip deferred decisions when auditing (default)",
    )
    parser.add_argument(
        "--include-needs-more-review",
        dest="skip_needs_more_review",
        action="store_false",
        help="Audit deferred decisions too",
    )
    parser.add_argument("--output", default=None, help="Optional audited CSV path")
    parser.add_argument("--flagged-output", default=None, help="Optional flagged CSV path")
    return parser


def preview_candidates(snapshot: Any, node_id: str) -> list[dict[str, str]]:
    preview = []
    for candidate in snapshot.review_by_node.get(node_id, [])[:3]:
        preview.append(
            {
                "openalex_id": normalize_openalex_id(candidate.get("candidate_openalex_id", "")),
                "display_name": (candidate.get("candidate_display_name", "") or "").strip(),
                "candidate_score": (candidate.get("candidate_score", "") or "").strip(),
                "institution_matches": (candidate.get("institution_matches", "") or "").strip(),
                "current_institution": (candidate.get("candidate_current_institution", "") or "").strip(),
                "institutions": (candidate.get("candidate_institutions", "") or "").strip(),
                "works_count": (candidate.get("candidate_works_count", "") or "").strip(),
                "cited_by_count": (candidate.get("candidate_cited_by_count", "") or "").strip(),
                "h_index": (candidate.get("candidate_h_index", "") or "").strip(),
            }
        )
    return preview


def selected_candidate_context(
    snapshot: Any,
    match_row: dict[str, str],
    decision_row: dict[str, str],
) -> dict[str, str]:
    node_id = (decision_row.get("node_id", "") or "").strip()
    selected_id = decision_selected_openalex_id(decision_row)

    if selected_id:
        review_candidate = snapshot.review_by_node_candidate.get((node_id, selected_id))
        if review_candidate:
            return {
                "openalex_id": selected_id,
                "display_name": (review_candidate.get("candidate_display_name", "") or "").strip(),
                "candidate_score": (review_candidate.get("candidate_score", "") or "").strip(),
                "current_institution": (review_candidate.get("candidate_current_institution", "") or "").strip(),
                "institutions": (review_candidate.get("candidate_institutions", "") or "").strip(),
                "works_count": (review_candidate.get("candidate_works_count", "") or "").strip(),
                "cited_by_count": (review_candidate.get("candidate_cited_by_count", "") or "").strip(),
                "h_index": (review_candidate.get("candidate_h_index", "") or "").strip(),
            }

    match_openalex_id = normalize_openalex_id(match_row.get("openalex_id", ""))
    if selected_id and selected_id == match_openalex_id:
        return {
            "openalex_id": selected_id,
            "display_name": (match_row.get("openalex_display_name", "") or "").strip(),
            "candidate_score": (match_row.get("match_confidence", "") or "").strip(),
            "current_institution": "",
            "institutions": (match_row.get("matched_institutions", "") or "").strip(),
            "works_count": (match_row.get("works_count", "") or "").strip(),
            "cited_by_count": (match_row.get("cited_by_count", "") or "").strip(),
            "h_index": (match_row.get("h_index", "") or "").strip(),
        }

    current_id = normalize_openalex_id(decision_row.get("current_openalex_id", ""))
    if current_id and current_id == match_openalex_id:
        return {
            "openalex_id": current_id,
            "display_name": (match_row.get("openalex_display_name", "") or "").strip(),
            "candidate_score": (match_row.get("match_confidence", "") or "").strip(),
            "current_institution": "",
            "institutions": (match_row.get("matched_institutions", "") or "").strip(),
            "works_count": (match_row.get("works_count", "") or "").strip(),
            "cited_by_count": (match_row.get("cited_by_count", "") or "").strip(),
            "h_index": (match_row.get("h_index", "") or "").strip(),
        }

    return {
        "openalex_id": selected_id or current_id,
        "display_name": "",
        "candidate_score": "",
        "current_institution": "",
        "institutions": "",
        "works_count": "",
        "cited_by_count": "",
        "h_index": "",
    }


def build_evidence(
    snapshot: Any,
    decision_row: dict[str, str],
) -> tuple[dict[str, Any], dict[str, str], dict[str, str], list[dict[str, str]]]:
    node_id = (decision_row.get("node_id", "") or "").strip()
    if node_id not in snapshot.matches_by_node:
        raise ValueError(f"Decision references node_id not present in snapshot: {node_id}")

    match_row = snapshot.matches_by_node[node_id]
    selected_candidate = selected_candidate_context(snapshot, match_row, decision_row)
    selected_id = normalize_openalex_id(selected_candidate.get("openalex_id", ""))
    top_papers = top_papers_for_node_author(snapshot, node_id=node_id, openalex_id=selected_id)
    candidate_preview = preview_candidates(snapshot, node_id)
    evidence = {
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
        },
        "decision": {
            "decision": (decision_row.get("decision", "") or "").strip(),
            "current_openalex_id": normalize_openalex_id(decision_row.get("current_openalex_id", "")),
            "proposed_openalex_id": normalize_openalex_id(decision_row.get("proposed_openalex_id", "")),
            "reason": (decision_row.get("reason", "") or "").strip(),
            "reviewer": (decision_row.get("reviewer", "") or "").strip(),
        },
        "selected_candidate": selected_candidate,
        "current_match": {
            "openalex_id": normalize_openalex_id(match_row.get("openalex_id", "")),
            "display_name": (match_row.get("openalex_display_name", "") or "").strip(),
            "works_count": (match_row.get("works_count", "") or "").strip(),
            "cited_by_count": (match_row.get("cited_by_count", "") or "").strip(),
            "h_index": (match_row.get("h_index", "") or "").strip(),
        },
        "candidate_preview": candidate_preview,
        "top_papers_preview": [
            {
                "title": (paper.get("title", "") or "").strip(),
                "publication_year": (paper.get("publication_year", "") or "").strip(),
                "cited_by_count": (paper.get("cited_by_count", "") or "").strip(),
                "venue": (paper.get("venue", "") or "").strip(),
            }
            for paper in top_papers[:3]
        ],
    }
    return evidence, match_row, selected_candidate, candidate_preview


def select_client(args: argparse.Namespace) -> AuditClient:
    if args.provider == "mock":
        return MockAuditClient()
    try:
        return AnthropicAuditClient(api_key=args.api_key, model=args.model)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    decisions_path = Path(args.decisions)
    if not decisions_path.is_absolute():
        decisions_path = PROJECT_ROOT / decisions_path
    date_token = args.date or extract_date_token(decisions_path.name)
    snapshot = load_review_snapshot(
        date_token=date_token,
        matches_path=args.matches,
        review_path=args.review,
        top_papers_path=args.top_papers,
    )
    decisions = read_decisions_csv(decisions_path)

    output_path = (
        Path(args.output)
        if args.output
        else PROJECT_ROOT / "Data" / "Derived" / f"OpenAlex_Audited_Decisions_{snapshot.paths.date_token}.csv"
    )
    flagged_output_path = (
        Path(args.flagged_output)
        if args.flagged_output
        else PROJECT_ROOT / "Data" / "Derived" / f"OpenAlex_Flagged_For_Review_{snapshot.paths.date_token}.csv"
    )
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    if not flagged_output_path.is_absolute():
        flagged_output_path = PROJECT_ROOT / flagged_output_path

    client = select_client(args)
    audited_rows: list[dict[str, str]] = []
    flagged_rows: list[dict[str, str]] = []
    processed = 0
    audited_count = 0

    for index, decision_row in enumerate(decisions, start=1):
        decision = (decision_row.get("decision", "") or "").strip()
        evidence, match_row, selected_candidate, candidate_preview = build_evidence(snapshot, decision_row)

        if decision == "needs_more_review" and args.skip_needs_more_review:
            audit = {
                "audit_verdict": "",
                "audit_confidence": "",
                "audit_note": "Skipped because the decision remains deferred.",
            }
        else:
            try:
                audit = client.audit(evidence)
            except Exception as exc:  # noqa: BLE001
                audit = audit_result("flag", "low", f"Audit failed: {exc}")
            audited_count += 1
            if audited_count % max(args.batch_size, 1) == 0 and index < len(decisions):
                time.sleep(max(args.sleep_seconds, 0.0))

        row = {
            **{field: (decision_row.get(field, "") or "").strip() for field in DECISION_FIELDNAMES},
            "source_date": snapshot.paths.date_token,
            "match_status": (match_row.get("match_status", "") or "").strip(),
            "review_notes": (match_row.get("review_notes", "") or "").strip(),
            "suspicious_flags": (match_row.get("suspicious_flags", "") or "").strip(),
            "selected_openalex_id": normalize_openalex_id(selected_candidate.get("openalex_id", "")),
            "selected_display_name": (selected_candidate.get("display_name", "") or "").strip(),
            "selected_candidate_score": (selected_candidate.get("candidate_score", "") or "").strip(),
            "selected_candidate_current_institution": (selected_candidate.get("current_institution", "") or "").strip(),
            "selected_candidate_institutions": (selected_candidate.get("institutions", "") or "").strip(),
            "selected_candidate_works_count": (selected_candidate.get("works_count", "") or "").strip(),
            "selected_candidate_cited_by_count": (selected_candidate.get("cited_by_count", "") or "").strip(),
            "selected_candidate_h_index": (selected_candidate.get("h_index", "") or "").strip(),
            "candidate_preview": json.dumps(candidate_preview, ensure_ascii=False),
            "top_papers_preview": summarize_top_papers(
                top_papers_for_node_author(
                    snapshot,
                    node_id=(decision_row.get("node_id", "") or "").strip(),
                    openalex_id=selected_candidate.get("openalex_id", ""),
                ),
                limit=3,
            ),
            **audit,
        }
        audited_rows.append(row)
        if row["audit_verdict"] == "flag":
            flagged_rows.append(row)
        processed += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    flagged_output_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(output_path, AUDITED_FIELDS, audited_rows)
    write_csv(flagged_output_path, AUDITED_FIELDS, flagged_rows)

    print(f"Loaded decisions:      {len(decisions)} from {decisions_path}")
    print(f"Snapshot date:         {snapshot.paths.date_token}")
    print(f"Audited rows:          {audited_count}")
    print(f"Flagged rows:          {len(flagged_rows)}")
    print(f"Audited CSV:           {output_path}")
    print(f"Flagged CSV:           {flagged_output_path}")


if __name__ == "__main__":
    main()
