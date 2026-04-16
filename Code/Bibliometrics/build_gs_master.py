#!/usr/bin/env python3
"""Build a row-stacked master GS CSV from per-generation inputs.

Unions Gens 1–4 per-gen CSVs into GS_AllGens_<date>.csv with an aligned 14-column schema:

    generation, node_id, name, in_gs, quality, gs_suspicious_mismatch,
    gs_profile_url, citations_all, citations_recent, h_index_all,
    h_index_recent, i10_all, i10_recent, affiliation

- Gen 1 rows (source lacks gs_suspicious_mismatch) are backfilled with "0".
- Gens 2/3/4 have already been through the mismatch-review workflow.
- Duplicate node_ids across inputs are a hard error.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_GEN1 = PROJECT_ROOT / "Data" / "Derived" / "GS_Gen1_041426.csv"
DEFAULT_GEN2 = PROJECT_ROOT / "Data" / "Derived" / "GS_Gen2_Patched_041626.csv"
DEFAULT_GEN3 = PROJECT_ROOT / "Data" / "Derived" / "GS_Gen3_Patched_041626.csv"
DEFAULT_GEN4 = PROJECT_ROOT / "Data" / "Derived" / "GS_Gen4_Patched_041626.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "Data" / "Derived" / "GS_AllGens_041626.csv"

MASTER_COLS = [
    "generation", "node_id", "name", "in_gs", "quality",
    "gs_suspicious_mismatch", "gs_profile_url",
    "citations_all", "citations_recent",
    "h_index_all", "h_index_recent",
    "i10_all", "i10_recent",
    "affiliation",
]


def load_and_tag(path: Path, generation: str, fill_suspicious_zero: bool) -> list[dict]:
    if not path.exists():
        sys.exit(f"ERROR: input not found: {path}")
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out = {"generation": generation}
            for col in MASTER_COLS[1:]:
                if col == "gs_suspicious_mismatch" and fill_suspicious_zero:
                    out[col] = row.get(col, "0") or "0"
                else:
                    out[col] = row.get(col, "")
            rows.append(out)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Build master GS file from per-gen inputs")
    ap.add_argument("--gen1", default=str(DEFAULT_GEN1))
    ap.add_argument("--gen2", default=str(DEFAULT_GEN2))
    ap.add_argument("--gen3", default=str(DEFAULT_GEN3))
    ap.add_argument("--gen4", default=str(DEFAULT_GEN4))
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = ap.parse_args()

    gen1 = load_and_tag(Path(args.gen1), "1", fill_suspicious_zero=True)
    gen2 = load_and_tag(Path(args.gen2), "2", fill_suspicious_zero=False)
    gen3 = load_and_tag(Path(args.gen3), "3", fill_suspicious_zero=False)
    gen4 = load_and_tag(Path(args.gen4), "4", fill_suspicious_zero=False)

    merged = gen1 + gen2 + gen3 + gen4

    ids = Counter(r["node_id"] for r in merged)
    dups = [nid for nid, n in ids.items() if n > 1]
    if dups:
        sys.exit(f"ERROR: duplicate node_ids across inputs: {dups[:5]} (total {len(dups)})")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MASTER_COLS)
        w.writeheader()
        for row in merged:
            w.writerow(row)

    by_gen = Counter(r["generation"] for r in merged)
    q_g1 = Counter(r["quality"] for r in gen1)
    q_g2 = Counter(r["quality"] for r in gen2)
    q_g3 = Counter(r["quality"] for r in gen3)
    q_g4 = Counter(r["quality"] for r in gen4)
    susp = sum(1 for r in merged if r["gs_suspicious_mismatch"] == "1")
    print(f"Wrote {out_path} ({len(merged)} rows)")
    print(f"By generation: {dict(sorted(by_gen.items()))}")
    print(f"Gen 1 quality: {dict(q_g1)}")
    print(f"Gen 2 quality: {dict(q_g2)}")
    print(f"Gen 3 quality: {dict(q_g3)}")
    print(f"Gen 4 quality: {dict(q_g4)}")
    print(f"Suspicious (gs_suspicious_mismatch=1): {susp}")
    print(f"Header: {','.join(MASTER_COLS)}")


if __name__ == "__main__":
    main()
