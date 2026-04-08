# Gen 4 Nonrespondent Backfill Master Plan

Version date: 2026-04-08
Status: active working plan
Anchor snapshot: `040126`

## Purpose

This file is the stable reference document for all Gen 4 nonrespondent
backfill work. Future Claude phase prompts should read this file first, then
only the minimum additional files needed for the current phase.

Gen 4 is a narrow follow-on project, not a full multi-wave research program.
The universe is 4 nonrespondent nodes. The goal is to recover reliable metadata
where evidence supports it, integrate approved rows into the existing
multi-backfill pipeline, and produce a short descriptive output.

## Fixed Scope

- Universe: Gen 4 nodes in `Data/Derived/Network_Nodes_040126.csv`
- Current footprint: 5 total Gen 4 nodes, 1 respondent, 4 nonrespondents
- Do not expand the Gen 4 roster unless the anchor snapshot changes
- Do not modify raw survey files
- Keep findings separate from pipeline-approved backfill rows
- Only backfill fields currently supported by `Code/Network/build_network.py`

## Snapshot Facts

From `Data/Derived/Network_Nodes_040126.csv`:

- Total Gen 4 nodes: 5
- Gen 4 respondents: 1
- Gen 4 nonrespondents: 4
- No Gen 4 nodes have descendants (all are leaf nodes)

### Respondent

Christina Nguyen (`R-R_6nmE1UuZX8Ob0v7`), advised by Jacquelyn Pless
(Gen 3). Full core metadata populated: phd_year, phd_institution_canon,
current_employer_canon, country, us_state, email. No backfill needed.

### Nonrespondent Universe (Backfill Targets)

All 4 nonrespondents currently have only `email` populated in
`Network_Nodes_040126.csv`. All other core metadata fields (phd_year,
phd_institution_canon, current_employer_canon, country, us_state) are blank.

| Node ID | Name | Advisor (Gen 3) | Current Evidence |
|---------|------|-----------------|-----------------|
| S-R_6Q4Uwi4ubOpJtAx-0001 | Shimeng Huang | Philip Mulder | weak |
| S-R_9i4H75l7IKGKK6n-0001 | Muchen Li | Zhihao Xu | moderate |
| S-R_9i4H75l7IKGKK6n-0002 | Mengyu Chen | Zhihao Xu | moderate |
| S-R_9i4H75l7IKGKK6n-0003 | Sicheng Zhao | Zhihao Xu | moderate |

Three of the four are students of Zhihao Xu at Tsinghua University, School
of Social Sciences.

### Existing Evidence Base

All 4 nonrespondents already appear in
`Data/Derived/Gen3_Public_Student_Verification_Report_040126.md` with
verification notes from the Gen 3 public student verification pass. That
report should be treated as the starting evidence base rather than duplicating
web research from scratch.

Key findings from the verification report:

- **Shimeng Huang**: PhD from University of Wisconsin (insurance economics),
  now Assistant Professor of Actuarial Science at Purdue (2025--26). Mulder is
  faculty with overlapping climate-risk research, but no public source
  explicitly names him as advisor. Evidence strength: weak.
- **Muchen Li**: Co-author on published JCEBS paper (2025) with Xu. Listed on
  Xu's Chinese-language faculty page. Email domain consistent with ~2021
  enrollment. Evidence strength: moderate.
- **Mengyu Chen**: Co-author on same JCEBS paper. Listed on Xu's faculty page.
  Email domain consistent with 2024 enrollment and ~2029 expected graduation.
  Evidence strength: moderate.
- **Sicheng Zhao**: Co-author on working paper with Xu (presented at Duke
  Kunshan, ANU). Email domain consistent with 2023 enrollment and ~2028
  expected graduation. Caveat: Ke Rong (co-author, also Tsinghua professor)
  could be alternate advisor. Evidence strength: moderate.

## Pipeline-Facing Backfill Fields

Same schema as Gen 2 and Gen 3 backfill. `Code/Network/build_network.py`
accepts these approved backfill columns:

- `node_id`
- `backfill_email`
- `backfill_phd_institution_raw`, `backfill_phd_institution_canon`
- `backfill_phd_year`
- `backfill_current_employer_raw`, `backfill_current_employer_canon`
- `backfill_country`, `backfill_us_state`
- `source_1_url`, `source_2_url`
- `evidence_strength`
- `clear_fields`
- `notes`

Approved CSV schema: exactly the 14 pipeline-facing columns above. No workflow
helper columns belong in the approved export.

Findings CSV schema: the same 14 approved columns plus 3 workflow helpers:

- `first_name`
- `last_name`
- `research_status`

Semantics:

- Nonblank `backfill_*` value: set or overwrite canonical node field
- Blank `backfill_*` value: no change
- `clear_fields`: comma-separated canonical field names to explicitly blank
- Do not put the same field in both `clear_fields` and a nonblank
  `backfill_*` column

## Working Files

- `Planning/Gen4_Nonrespondent_Backfill_Master_Plan.md` (this file)
- `Data/Derived/Gen4_Nonrespondent_Backfill_Roster_040126.csv`
- `Data/Derived/Gen4_Nonrespondent_Backfill_Findings_040126.csv`
- `Data/Derived/Gen4_Nonrespondent_Backfill_Approved_040126.csv`
- Phase memos under `Output/Gen4_Nonrespondent_Backfill_Phase{N}_040126.md`

No batch assignment CSV is needed. The universe is 4 nodes; all are processed
in a single pass.

## Phase Order

### Phase 1: Freeze Roster and Scaffold Files

Goal: lock down the working universe and create empty templates.

Tasks:

- Freeze the 4 nonrespondent Gen 4 node_ids into the roster CSV
- Create findings CSV with the 17-column findings schema: approved schema +
  `first_name`, `last_name`, `research_status`
- Create approved CSV with the exact 14-column pipeline-facing schema
- Seed each findings row with `node_id`, `first_name`, `last_name`, and
  default `research_status=unresolved`
- Copy the already-known public-verification context from
  `Gen3_Public_Student_Verification_Report_040126.md` into findings
  `source_1_url`, `source_2_url`, `evidence_strength`, and `notes` where that
  report already contains those values
- Validate: 4 roster rows, 4 findings rows, 0 approved rows, all node_ids
  present in `Network_Nodes_040126.csv`, findings headers match the 17-column
  schema exactly, approved headers match the 14-column schema exactly

Outputs:

- `Data/Derived/Gen4_Nonrespondent_Backfill_Roster_040126.csv`
- `Data/Derived/Gen4_Nonrespondent_Backfill_Findings_040126.csv`
- `Data/Derived/Gen4_Nonrespondent_Backfill_Approved_040126.csv` (empty, header only)
- `Output/Gen4_Nonrespondent_Backfill_Phase1_040126.md`

### Phase 2: Targeted Evidence Review and Backfill

Goal: attempt to recover phd_institution, phd_year, current_employer, country,
and us_state for each of the 4 nonrespondents.

Tasks:

- Re-open the 4 nonrespondent cases using the Gen 3 public student
  verification report as the evidence base
- For each node, search for additional public evidence (institutional pages,
  dissertation repositories, co-authored papers, faculty listings) to
  corroborate or upgrade the existing verification findings
- Populate backfill fields in the findings CSV where strong or moderate
  evidence supports them
- Assign a research_status to each row: `approved`, `hold`, or `unresolved`
- Because the universe is 4 nodes, process all in a single compact pass (no
  separate difficulty batches)

Evidence priorities per node:

- All 4: phd_institution and phd_year (most likely recoverable from
  institutional pages)
- All 4: country (likely inferable from employer/institution location)
- Shimeng Huang: current_employer may already be Purdue per verification report
- Xu's 3 students: current_employer may be Tsinghua if still enrolled

Outputs:

- Updated `Data/Derived/Gen4_Nonrespondent_Backfill_Findings_040126.csv`
- `Output/Gen4_Nonrespondent_Backfill_Phase2_040126.md`

### Phase 3: QA and Promotion

Goal: review findings and promote only sufficiently supported rows into the
approved file.

Tasks:

- Review all 4 findings rows for accuracy, consistency, and evidence quality
- Promote rows with strong or moderate evidence into the approved CSV
- Leave hold or unresolved rows in findings only
- Ensure approved rows use pipeline-compatible fields only (no raw email
  addresses in notes, proper canonical mappings, country/us_state consistency)
- Validate: approved subset equals findings rows with `research_status=approved`
  and every exported approved field exactly matches its findings counterpart

Outputs:

- Updated `Data/Derived/Gen4_Nonrespondent_Backfill_Approved_040126.csv`
- `Output/Gen4_Nonrespondent_Backfill_Phase3_040126.md`

### Phase 4: Pipeline Integration and Canonical Descriptives

Goal: integrate approved backfill into the existing pipeline and produce a
canonical Gen 4 descriptive output.

Tasks:

- Add `gen4_backfill` to `FILE_SPECS` in
  `Code/Orchestration/refresh_downstream.py` alongside the existing
  `gen2_backfill` and `gen3_backfill` entries
- Extend the backfill auto-discovery loop in
  `Code/Orchestration/refresh_downstream.py` so Gen 4 approved backfill is
  loaded automatically when present
- Update `Code/README.md` so curated inputs and the backfill description no
  longer describe the system as Gen 2/Gen 3 only
- Extend `Code/Validation/validate_nonrespondent_backfill_audit.py` to support
  Gen 4 roster/findings/approved files plus Gen 4 markdown outputs
- Run `validate_nonrespondent_backfill_audit.py --date 040126` before the final
  pipeline rebuild
- Add `Code/Network/describe_fourth_generation.py` and wire it into
  `refresh_downstream.py` so Gen 4 is part of the standard descriptive rebuild
  alongside Gen 1, Gen 2, and Gen 3
- Run `refresh_downstream.py --date 040126` to rebuild downstream outputs
- Verify that approved Gen 4 backfill values propagate correctly into
  `Network_Nodes_040126.csv`
- Produce canonical Gen 4 descriptive outputs:
  `Data/Derived/Fourth_Generation_Headlines_040126.csv`,
  `Data/Derived/Fourth_Generation_Subtree_Sizes_040126.csv`,
  `Data/Derived/Fourth_Generation_Profile_040126.csv`,
  `Data/Derived/Fourth_Generation_Metadata_Coverage_040126.csv`, and
  `Output/Fourth_Generation_Descriptives_040126.md`
- Gen 4 descriptives should follow the same contract as the existing Gen 2/Gen
  3 descriptive scripts: canonical CSV outputs plus a markdown summary written
  by the pipeline, not a hand-written one-off report

Outputs:

- Updated `Code/Orchestration/refresh_downstream.py`
- Updated `Code/README.md`
- Updated `Code/Validation/validate_nonrespondent_backfill_audit.py`
- Updated `Code/Network/describe_fourth_generation.py`
- Rebuilt `Data/Derived/Network_Nodes_040126.csv`
- `Output/Gen4_Nonrespondent_Backfill_Phase4_040126.md`
- `Data/Derived/Fourth_Generation_Headlines_040126.csv`
- `Data/Derived/Fourth_Generation_Subtree_Sizes_040126.csv`
- `Data/Derived/Fourth_Generation_Profile_040126.csv`
- `Data/Derived/Fourth_Generation_Metadata_Coverage_040126.csv`
- `Output/Fourth_Generation_Descriptives_040126.md`

## Evidence Standards

Reuse the same three-level system from the Gen 3 master plan:

- **Strong**: official university/employer page, dissertation repository, or
  academic database with explicit name + field match
- **Moderate**: reliable profile or publication with corroboration from a
  second independent source (co-authored paper, faculty listing, etc.)
- **Weak**: single uncorroborated source (LinkedIn alone, personal website
  without institutional backing, etc.)

Approval rules:

- Strong evidence: approve
- Moderate evidence: approve if identity is unambiguous and values are not
  speculative
- Weak evidence: do not approve; leave in findings as hold or unresolved
- Do not infer country or us_state unless current affiliation location is
  sufficiently clear from the evidence
- Survey-backed Q12a links remain the capture rule for advisor-student
  relationships; public evidence is used only for metadata recovery

Because Gen 4 is tiny and sparse, err on the side of conservatism. It is
better to leave a field blank than to approve a speculative value for 1 of 4
nodes.

## Completion Criteria

Gen 4 nonrespondent backfill is complete when:

- All 4 nonrespondent cases have findings rows with research outcomes
- Any sufficiently supported metadata are promoted into the approved CSV
- The approved rows integrate cleanly into the pipeline via the existing
  multi-backfill `--backfill` mechanism
- `validate_nonrespondent_backfill_audit.py --date 040126` passes with Gen 4
  coverage enabled
- `refresh_downstream.py --date 040126` runs successfully with the Gen 4
  backfill auto-discovered
- `refresh_downstream.py --date 040126` emits the full four-generation
  descriptive set, including `Output/Fourth_Generation_Descriptives_040126.md`

## Recommended Prompt Preamble

Future phase prompts should begin with:

1. Read `Planning/Gen4_Nonrespondent_Backfill_Master_Plan.md`
2. Read the phase-specific working files listed for the current phase
3. Do not modify raw survey files or `build_network.py`
4. Stay within the 4-node universe unless the anchor snapshot changes
5. End with exactly three statuses: approved, hold, unresolved
