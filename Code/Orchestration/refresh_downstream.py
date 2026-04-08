#!/usr/bin/env python3
"""
Refresh downstream Mokyr genealogy artifacts for a given dated snapshot.

This driver rebuilds the network-derived outputs in a deterministic order and
optionally refreshes outreach-response tracking when raw exports are provided.
"""

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

FILE_SPECS = {
    "cleaned": (
        PROJECT_ROOT / "Data" / "Cleaned",
        "Mokyr_Survey_Responses_{date}_Cleaned.csv",
        re.compile(r"^Mokyr_Survey_Responses_(\d{6})_Cleaned\.csv$"),
    ),
    "q12a": (
        PROJECT_ROOT / "Data" / "Derived",
        "Advisors_and_Reported_Students_{date}.csv",
        re.compile(r"^Advisors_and_Reported_Students_(\d{6})\.csv$"),
    ),
    "email_recovery": (
        PROJECT_ROOT / "Data" / "Derived",
        "Email_Recovery_{date}.csv",
        re.compile(r"^Email_Recovery_(\d{6})\.csv$"),
    ),
    "manual_nodes": (
        PROJECT_ROOT / "Data" / "Derived",
        "Manual_Nodes_{date}.csv",
        re.compile(r"^Manual_Nodes_(\d{6})\.csv$"),
    ),
    "manual_edges": (
        PROJECT_ROOT / "Data" / "Derived",
        "Manual_Edges_{date}.csv",
        re.compile(r"^Manual_Edges_(\d{6})\.csv$"),
    ),
    "manual_provenance": (
        PROJECT_ROOT / "Data" / "Derived",
        "Manual_Node_Provenance_{date}.csv",
        re.compile(r"^Manual_Node_Provenance_(\d{6})\.csv$"),
    ),
    "audit": (
        PROJECT_ROOT / "Data" / "Derived",
        "Gen1_Student_Verification_Audit_{date}.csv",
        re.compile(r"^Gen1_Student_Verification_Audit_(\d{6})\.csv$"),
    ),
    "gen2_audit": (
        PROJECT_ROOT / "Data" / "Derived",
        "Gen2_Student_Capture_Audit_{date}.csv",
        re.compile(r"^Gen2_Student_Capture_Audit_(\d{6})\.csv$"),
    ),
    "gen2_recovery_findings": (
        PROJECT_ROOT / "Data" / "Derived",
        "Gen2_EmptyQ12a_Public_Recovery_Findings_{date}.csv",
        re.compile(r"^Gen2_EmptyQ12a_Public_Recovery_Findings_(\d{6})\.csv$"),
    ),
    "gen3_verification_findings": (
        PROJECT_ROOT / "Data" / "Derived",
        "Gen3_Public_Student_Verification_Findings_{date}.csv",
        re.compile(r"^Gen3_Public_Student_Verification_Findings_(\d{6})\.csv$"),
    ),
    "gen2_backfill": (
        PROJECT_ROOT / "Data" / "Derived",
        "Gen2_Nonrespondent_Backfill_Approved_{date}.csv",
        re.compile(r"^Gen2_Nonrespondent_Backfill_Approved_(\d{6})\.csv$"),
    ),
    "gen3_backfill": (
        PROJECT_ROOT / "Data" / "Derived",
        "Gen3_Nonrespondent_Backfill_Approved_{date}.csv",
        re.compile(r"^Gen3_Nonrespondent_Backfill_Approved_(\d{6})\.csv$"),
    ),
    "gen4_backfill": (
        PROJECT_ROOT / "Data" / "Derived",
        "Gen4_Nonrespondent_Backfill_Approved_{date}.csv",
        re.compile(r"^Gen4_Nonrespondent_Backfill_Approved_(\d{6})\.csv$"),
    ),
}


def parse_mmddyy(token: str) -> datetime:
    return datetime.strptime(token, "%m%d%y")


def resolve_project_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def resolve_compatible_input(
    label: str,
    date_token: str,
    explicit: str | None = None,
    required: bool = False,
    allow_fallback: bool = True,
) -> Path | None:
    if explicit:
        return resolve_project_path(explicit)

    base_dir, template, pattern = FILE_SPECS[label]
    exact = base_dir / template.format(date=date_token)
    if exact.exists():
        return exact
    if not allow_fallback:
        if required:
            raise FileNotFoundError(f"Missing required exact {label} input for {date_token}: {exact}")
        return None
    if not base_dir.exists():
        if required:
            raise FileNotFoundError(f"Missing base directory for {label}: {base_dir}")
        return None

    target_dt = parse_mmddyy(date_token)
    matches = []
    for path in base_dir.iterdir():
        match = pattern.match(path.name)
        if not match:
            continue
        token = match.group(1)
        if parse_mmddyy(token) <= target_dt:
            matches.append((parse_mmddyy(token), path))
    if matches:
        matches.sort()
        return matches[-1][1]
    if required:
        raise FileNotFoundError(f"No compatible {label} input found at or before {date_token}")
    return None


def append_path_arg(cmd: list[str], flag: str, path: Path | None) -> None:
    if path:
        cmd.extend([flag, str(path.relative_to(PROJECT_ROOT))])


def run_step(label: str, cmd: list[str]) -> None:
    print(f"\n=== {label} ===")
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)


def require_existing_paths(paths: list[Path]) -> None:
    missing = [path for path in paths if not path.exists()]
    if missing:
        missing_text = "\n".join(str(path.relative_to(PROJECT_ROOT)) for path in missing)
        raise FileNotFoundError(f"Required refresh helper files are missing:\n{missing_text}")


def extract_d3_from_existing_html(date_token: str) -> Path | None:
    html_path = PROJECT_ROOT / "Output" / f"mokyr-genealogy-{date_token}.html"
    if not html_path.exists():
        return None
    text = html_path.read_text(encoding="utf-8")
    start_marker = "// https://d3js.org v7.9.0"
    end_marker = "// ── data "
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start == -1 or end == -1 or end <= start:
        return None
    d3_text = text[start:end].rstrip() + "\n"
    cache_path = PROJECT_ROOT / "tmp" / "d3.v7.9.0.min.js"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(d3_text, encoding="utf-8")
    return cache_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh downstream Mokyr genealogy outputs for a dated snapshot"
    )
    parser.add_argument("--date", required=True, help="Snapshot date tag (MMDDYY)")
    parser.add_argument("--cleaned", help="Override cleaned survey input path")
    parser.add_argument("--q12a", help="Override Q12a input path")
    parser.add_argument("--email-recovery", help="Override email recovery input path")
    parser.add_argument("--manual-nodes", help="Override manual nodes input path")
    parser.add_argument("--manual-edges", help="Override manual edges input path")
    parser.add_argument("--manual-provenance", help="Override manual provenance input path")
    parser.add_argument("--audit", help="Override Gen1 audit CSV path")
    parser.add_argument("--gen2-audit", help="Override Gen2 capture audit CSV path")
    parser.add_argument("--gen2-recovery-findings", help="Override Gen2 empty-Q12a public recovery findings CSV path")
    parser.add_argument("--gen3-verification-findings", help="Override Gen3 public student verification findings CSV path")
    parser.add_argument("--backfill", action="append", default=None,
                        help="Override approved backfill CSV path(s) (repeatable; enriches existing nodes)")
    parser.add_argument("--d3-path", help="Local d3.min.js path for viz rebuild")
    parser.add_argument("--current-raw", help="Optional current raw Qualtrics export for outreach refresh")
    parser.add_argument("--baseline-raw", help="Optional baseline raw Qualtrics export for outreach refresh")
    parser.add_argument("--non-respondent", help="Optional non-respondent tracking CSV override")
    parser.add_argument("--avner", help="Optional Avner outreach CSV override")
    args = parser.parse_args()

    date_token = args.date
    cleaned = resolve_compatible_input("cleaned", date_token, args.cleaned, required=True, allow_fallback=True)
    q12a = resolve_compatible_input("q12a", date_token, args.q12a, required=True, allow_fallback=True)
    email_recovery = resolve_compatible_input("email_recovery", date_token, args.email_recovery, required=False, allow_fallback=False)
    manual_nodes = resolve_compatible_input("manual_nodes", date_token, args.manual_nodes, required=False, allow_fallback=False)
    manual_edges = resolve_compatible_input("manual_edges", date_token, args.manual_edges, required=False, allow_fallback=False)
    manual_provenance = resolve_compatible_input("manual_provenance", date_token, args.manual_provenance, required=False, allow_fallback=False)
    audit = resolve_compatible_input("audit", date_token, args.audit, required=False, allow_fallback=False)
    gen2_audit = resolve_compatible_input("gen2_audit", date_token, args.gen2_audit, required=False, allow_fallback=False)
    gen2_recovery_findings = resolve_compatible_input("gen2_recovery_findings", date_token, args.gen2_recovery_findings, required=False, allow_fallback=False)
    gen3_verification_findings = resolve_compatible_input("gen3_verification_findings", date_token, args.gen3_verification_findings, required=False, allow_fallback=False)
    # Resolve approved backfill files: explicit overrides take precedence over auto-discovery
    if args.backfill:
        backfill_paths = [resolve_project_path(p) for p in args.backfill]
    else:
        backfill_paths = []
        for bf_label in ("gen2_backfill", "gen3_backfill", "gen4_backfill"):
            bf = resolve_compatible_input(bf_label, date_token, None, required=False, allow_fallback=False)
            if bf:
                backfill_paths.append(bf)

    nodes = PROJECT_ROOT / "Data" / "Derived" / f"Network_Nodes_{date_token}.csv"
    edges = PROJECT_ROOT / "Data" / "Derived" / f"Network_Edges_{date_token}.csv"
    unresolved = PROJECT_ROOT / "Data" / "Derived" / f"Unresolved_Edges_{date_token}.csv"
    discrepancies = PROJECT_ROOT / "Data" / "Derived" / f"Network_Discrepancies_{date_token}.csv"
    coverage = PROJECT_ROOT / "Data" / "Derived" / f"Descriptive_Validation_Coverage_{date_token}.csv"
    generation = PROJECT_ROOT / "Data" / "Derived" / f"Descriptive_Validation_Generation_{date_token}.csv"
    canon = PROJECT_ROOT / "Data" / "Derived" / f"Descriptive_Validation_Canon_{date_token}.csv"
    master = PROJECT_ROOT / "Data" / "Derived" / f"Master_Contact_List_{date_token}.csv"
    first_generation = PROJECT_ROOT / "Data" / "Derived" / f"First_Generation_Subtree_Sizes_{date_token}.csv"
    second_generation = PROJECT_ROOT / "Data" / "Derived" / f"Second_Generation_Subtree_Sizes_{date_token}.csv"
    third_generation = PROJECT_ROOT / "Data" / "Derived" / f"Third_Generation_Subtree_Sizes_{date_token}.csv"
    fourth_generation = PROJECT_ROOT / "Data" / "Derived" / f"Fourth_Generation_Subtree_Sizes_{date_token}.csv"
    html = PROJECT_ROOT / "Output" / f"mokyr-genealogy-{date_token}.html"

    required_scripts = [
        PROJECT_ROOT / "Code" / "Network" / "build_network.py",
        PROJECT_ROOT / "Code" / "Validation" / "validate_descriptive_inputs.py",
        PROJECT_ROOT / "Code" / "Network" / "describe_first_generation.py",
        PROJECT_ROOT / "Code" / "Network" / "describe_second_generation.py",
        PROJECT_ROOT / "Code" / "Network" / "describe_third_generation.py",
        PROJECT_ROOT / "Code" / "Network" / "describe_fourth_generation.py",
        PROJECT_ROOT / "Code" / "Network" / "build_master_list.py",
        PROJECT_ROOT / "Code" / "Network" / "build_outstanding_lists.py",
        PROJECT_ROOT / "Code" / "Network" / "viz_network.py",
    ]
    if audit and manual_provenance:
        required_scripts.append(PROJECT_ROOT / "Code" / "Validation" / "validate_gen1_audit.py")
    if gen2_audit:
        required_scripts.append(PROJECT_ROOT / "Code" / "Validation" / "validate_gen2_capture_audit.py")
    if gen2_recovery_findings:
        required_scripts.append(PROJECT_ROOT / "Code" / "Validation" / "render_gen2_empty_q12a_public_recovery.py")
    if gen3_verification_findings:
        required_scripts.append(PROJECT_ROOT / "Code" / "Validation" / "validate_gen3_public_student_verification.py")
    if args.current_raw and args.baseline_raw:
        required_scripts.append(PROJECT_ROOT / "Code" / "Outreach" / "check_outreach_responses.py")
    require_existing_paths(required_scripts)

    build_network_cmd = [sys.executable, "Code/Network/build_network.py", "--date", date_token]
    append_path_arg(build_network_cmd, "--cleaned", cleaned)
    append_path_arg(build_network_cmd, "--q12a", q12a)
    append_path_arg(build_network_cmd, "--email-recovery", email_recovery)
    append_path_arg(build_network_cmd, "--manual-nodes", manual_nodes)
    append_path_arg(build_network_cmd, "--manual-edges", manual_edges)
    for bf in backfill_paths:
        append_path_arg(build_network_cmd, "--backfill", bf)
    run_step("build_network", build_network_cmd)

    validate_inputs_cmd = [
        sys.executable,
        "Code/Validation/validate_descriptive_inputs.py",
        "--cleaned", str(cleaned.relative_to(PROJECT_ROOT)),
        "--q12a", str(q12a.relative_to(PROJECT_ROOT)),
        "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
        "--edges", str(edges.relative_to(PROJECT_ROOT)),
        "--unresolved", str(unresolved.relative_to(PROJECT_ROOT)),
        "--output-date", date_token,
    ]
    append_path_arg(validate_inputs_cmd, "--manual-nodes", manual_nodes)
    append_path_arg(validate_inputs_cmd, "--manual-edges", manual_edges)
    append_path_arg(validate_inputs_cmd, "--email-recovery", email_recovery)
    run_step("validate_descriptive_inputs", validate_inputs_cmd)

    describe_cmd = [
        sys.executable,
        "Code/Network/describe_first_generation.py",
        "--date", date_token,
        "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
        "--edges", str(edges.relative_to(PROJECT_ROOT)),
        "--coverage", str(coverage.relative_to(PROJECT_ROOT)),
        "--generation", str(generation.relative_to(PROJECT_ROOT)),
        "--canon", str(canon.relative_to(PROJECT_ROOT)),
        "--discrepancies", str(discrepancies.relative_to(PROJECT_ROOT)),
    ]
    run_step("describe_first_generation", describe_cmd)

    describe_gen2_cmd = [
        sys.executable,
        "Code/Network/describe_second_generation.py",
        "--date", date_token,
        "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
        "--edges", str(edges.relative_to(PROJECT_ROOT)),
        "--coverage", str(coverage.relative_to(PROJECT_ROOT)),
        "--generation", str(generation.relative_to(PROJECT_ROOT)),
        "--canon", str(canon.relative_to(PROJECT_ROOT)),
    ]
    run_step("describe_second_generation", describe_gen2_cmd)

    describe_gen3_cmd = [
        sys.executable,
        "Code/Network/describe_third_generation.py",
        "--date", date_token,
        "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
        "--edges", str(edges.relative_to(PROJECT_ROOT)),
        "--coverage", str(coverage.relative_to(PROJECT_ROOT)),
        "--generation", str(generation.relative_to(PROJECT_ROOT)),
        "--canon", str(canon.relative_to(PROJECT_ROOT)),
    ]
    run_step("describe_third_generation", describe_gen3_cmd)

    describe_gen4_cmd = [
        sys.executable,
        "Code/Network/describe_fourth_generation.py",
        "--date", date_token,
        "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
        "--edges", str(edges.relative_to(PROJECT_ROOT)),
        "--coverage", str(coverage.relative_to(PROJECT_ROOT)),
        "--generation", str(generation.relative_to(PROJECT_ROOT)),
        "--canon", str(canon.relative_to(PROJECT_ROOT)),
    ]
    run_step("describe_fourth_generation", describe_gen4_cmd)

    master_cmd = [
        sys.executable,
        "Code/Network/build_master_list.py",
        "--date", date_token,
        "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
        "--edges", str(edges.relative_to(PROJECT_ROOT)),
        "--cleaned", str(cleaned.relative_to(PROJECT_ROOT)),
        "--q12a", str(q12a.relative_to(PROJECT_ROOT)),
    ]
    run_step("build_master_list", master_cmd)

    if gen2_recovery_findings:
        render_gen2_recovery_cmd = [
            sys.executable,
            "Code/Validation/render_gen2_empty_q12a_public_recovery.py",
            "--date", date_token,
            "--findings", str(gen2_recovery_findings.relative_to(PROJECT_ROOT)),
            "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
        ]
        run_step("render_gen2_empty_q12a_public_recovery", render_gen2_recovery_cmd)
    else:
        print("\n=== render_gen2_empty_q12a_public_recovery ===")
        print("Skipping: Gen2 empty-Q12a public recovery findings input not available for this date.")

    if gen3_verification_findings:
        validate_gen3_cmd = [
            sys.executable,
            "Code/Validation/validate_gen3_public_student_verification.py",
            "--date", date_token,
            "--findings", str(gen3_verification_findings.relative_to(PROJECT_ROOT)),
            "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
            "--edges", str(edges.relative_to(PROJECT_ROOT)),
        ]
        run_step("validate_gen3_public_student_verification", validate_gen3_cmd)
    else:
        print("\n=== validate_gen3_public_student_verification ===")
        print("Skipping: Gen3 public student verification findings input not available for this date.")

    outstanding_cmd = [
        sys.executable,
        "Code/Network/build_outstanding_lists.py",
        "--date", date_token,
        "--master", str(master.relative_to(PROJECT_ROOT)),
    ]
    run_step("build_outstanding_lists", outstanding_cmd)

    d3_path = resolve_project_path(args.d3_path) if args.d3_path else extract_d3_from_existing_html(date_token)
    viz_cmd = [
        sys.executable,
        "Code/Network/viz_network.py",
        "--date", date_token,
        "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
        "--edges", str(edges.relative_to(PROJECT_ROOT)),
    ]
    append_path_arg(viz_cmd, "--d3-path", d3_path)
    run_step("viz_network", viz_cmd)

    if audit and manual_provenance:
        validate_audit_cmd = [
            sys.executable,
            "Code/Validation/validate_gen1_audit.py",
            "--date", date_token,
            "--first-generation", str(first_generation.relative_to(PROJECT_ROOT)),
            "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
            "--edges", str(edges.relative_to(PROJECT_ROOT)),
            "--audit", str(audit.relative_to(PROJECT_ROOT)),
            "--manual-provenance", str(manual_provenance.relative_to(PROJECT_ROOT)),
        ]
        append_path_arg(validate_audit_cmd, "--manual-nodes", manual_nodes)
        append_path_arg(validate_audit_cmd, "--manual-edges", manual_edges)
        run_step("validate_gen1_audit", validate_audit_cmd)
    else:
        print("\n=== validate_gen1_audit ===")
        print("Skipping: audit CSV or manual provenance input not available for this date.")

    if gen2_audit:
        validate_gen2_cmd = [
            sys.executable,
            "Code/Validation/validate_gen2_capture_audit.py",
            "--date", date_token,
            "--cleaned", str(cleaned.relative_to(PROJECT_ROOT)),
            "--q12a", str(q12a.relative_to(PROJECT_ROOT)),
            "--nodes", str(nodes.relative_to(PROJECT_ROOT)),
            "--edges", str(edges.relative_to(PROJECT_ROOT)),
            "--audit", str(gen2_audit.relative_to(PROJECT_ROOT)),
        ]
        append_path_arg(validate_gen2_cmd, "--recovery-findings", gen2_recovery_findings)
        run_step("validate_gen2_capture_audit", validate_gen2_cmd)
    else:
        print("\n=== validate_gen2_capture_audit ===")
        print("Skipping: Gen2 capture audit input not available for this date.")

    if args.current_raw and args.baseline_raw:
        outreach_cmd = [
            sys.executable,
            "Code/Outreach/check_outreach_responses.py",
            "--current-raw", str(resolve_project_path(args.current_raw).relative_to(PROJECT_ROOT)),
            "--baseline-raw", str(resolve_project_path(args.baseline_raw).relative_to(PROJECT_ROOT)),
        ]
        append_path_arg(outreach_cmd, "--non-respondent", resolve_project_path(args.non_respondent))
        append_path_arg(outreach_cmd, "--avner", resolve_project_path(args.avner))
        run_step("check_outreach_responses", outreach_cmd)
    else:
        print("\n=== check_outreach_responses ===")
        print("Skipping: no raw export pair supplied. Outreach outputs remain tied to the latest raw snapshot.")

    print("\n=== outputs ===")
    for output in [
        nodes,
        edges,
        coverage,
        generation,
        canon,
        first_generation,
        master,
        PROJECT_ROOT / "Data" / "Derived" / f"Outstanding_People_{date_token}_Validated.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Outstanding_Advisor_Summary_{date_token}_Validated.csv",
        html,
        PROJECT_ROOT / "Output" / f"First_Generation_Descriptives_{date_token}.md",
        PROJECT_ROOT / "Output" / f"Second_Generation_Descriptives_{date_token}.md",
        PROJECT_ROOT / "Output" / f"Descriptive_Input_Validation_{date_token}.md",
        PROJECT_ROOT / "Data" / "Derived" / f"First_Generation_Profile_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Second_Generation_Profile_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Third_Generation_Headlines_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Third_Generation_Subtree_Sizes_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Third_Generation_Profile_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Third_Generation_Metadata_Coverage_{date_token}.csv",
        PROJECT_ROOT / "Output" / f"Third_Generation_Descriptives_{date_token}.md",
        PROJECT_ROOT / "Data" / "Derived" / f"Fourth_Generation_Headlines_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Fourth_Generation_Subtree_Sizes_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Fourth_Generation_Profile_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Fourth_Generation_Metadata_Coverage_{date_token}.csv",
        PROJECT_ROOT / "Output" / f"Fourth_Generation_Descriptives_{date_token}.md",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen1_Student_Verification_Validation_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen1_Student_Verification_Summary_{date_token}.txt",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen2_Student_Capture_Audit_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen2_Student_Capture_Validation_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen2_Advisor_Q12_Gaps_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen2_Q12a_Recovery_Audit_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen2_Student_Capture_Summary_{date_token}.md",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen2_EmptyQ12a_Public_Recovery_Findings_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen2_EmptyQ12a_Public_Recovery_Report_{date_token}.md",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen3_Student_Verification_Audit_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen3_Student_Verification_Validation_{date_token}.csv",
        PROJECT_ROOT / "Data" / "Derived" / f"Gen3_Public_Student_Verification_Report_{date_token}.md",
    ]:
        print(output.relative_to(PROJECT_ROOT))


if __name__ == "__main__":
    main()
