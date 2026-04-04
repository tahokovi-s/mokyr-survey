# Gen 3 Nonrespondent Backfill Master Plan

Version date: 2026-04-03
Status: active working plan
Anchor snapshot: `040126`

## Purpose

This file is the stable reference document for all Gen 3 nonrespondent
backfill work. Future Claude phase prompts should tell agents to read this
file first, then read only the minimum additional files needed for the current
phase.

The goal is to backfill as much reliable field information as possible for Gen
3 nonrespondents without overloading agent context windows or mixing easy and
hard research tasks in the same pass.

## Fixed Scope

- Universe: Gen 3 nonrespondents from `Data/Derived/Network_Nodes_040126.csv`
- Do not expand the roster midstream unless the anchor snapshot changes
- Do not modify raw survey files
- Keep research findings separate from pipeline-approved backfill rows
- Only backfill fields currently supported by `Code/Network/build_network.py`

## Snapshot Facts

From `Data/Derived/Network_Nodes_040126.csv`:

- Total Gen 3 nodes: 115
- Gen 3 respondents: 37
- Gen 3 nonrespondents: 78
- Prefix split among nonrespondents: 64 `S-` nodes, 14 `M-` nodes

Current nonrespondent field coverage:

- `email`: 37
- `phd_year`: 8
- `phd_institution_canon`: 8
- `current_employer_canon`: 8
- `country`: 0
- `us_state`: 0
- No key fields at all: 36

Observed metadata patterns:

- 36 nodes have no key fields populated
- 34 nodes have email only
- 5 nodes have `phd_year` + `phd_institution_canon` + `current_employer_canon`
- 3 nodes have `phd_year` + `phd_institution_canon` + `current_employer_canon` + `email`

## Difficulty Buckets

Use these exact bucket definitions.

- `partial_core`
  - Nonrespondent Gen 3 node with any of `phd_year`,
    `phd_institution_canon`, or `current_employer_canon` already populated
  - Expected count: 8
- `email_only`
  - Has `email` but none of `phd_year`, `phd_institution_canon`,
    `current_employer_canon`, `country`, `us_state`
  - Expected count: 34
- `blank_manual`
  - `M-` node with none of `phd_year`, `phd_institution_canon`,
    `current_employer_canon`, `country`, `us_state`, `email`
  - Expected count: 2
- `blank_student`
  - `S-` node with none of `phd_year`, `phd_institution_canon`,
    `current_employer_canon`, `country`, `us_state`, `email`
  - Expected count: 34

These counts should be treated as a QA check in Phase 1.

## Pipeline-Facing Backfill Fields

`Code/Network/build_network.py` currently accepts these approved backfill
columns:

- `node_id`
- `backfill_email`
- `backfill_phd_institution_raw`
- `backfill_phd_institution_canon`
- `backfill_phd_year`
- `backfill_current_employer_raw`
- `backfill_current_employer_canon`
- `backfill_country`
- `backfill_us_state`
- `source_1_url`
- `source_2_url`
- `evidence_strength`
- `clear_fields`
- `notes`

Semantics:

- Nonblank `backfill_*` value: set or overwrite canonical node field
- Blank `backfill_*` value: no change
- `clear_fields`: comma-separated canonical field names to explicitly blank
- Do not put the same field in both `clear_fields` and a nonblank
  `backfill_*` column

## Core Working Files

Phase work should revolve around these files:

- `Planning/Gen3_Nonrespondent_Backfill_Master_Plan.md`
- `Data/Derived/Gen3_Nonrespondent_Backfill_Roster_040126.csv`
- `Data/Derived/Gen3_Nonrespondent_Backfill_Batches_040126.csv`
- `Data/Derived/Gen3_Nonrespondent_Backfill_Findings_040126.csv`
- `Data/Derived/Gen3_Nonrespondent_Backfill_Approved_040126.csv`
- `Output/Gen3_Nonrespondent_Backfill_Phase1_040126.md`

If later phases produce audit notes, keep them under `Output/` unless there is
a strong reason to add another derived CSV.

## Phase Order

### Phase 1: Scaffolding and Batching

Goal:

- Freeze the working universe
- Create templates and staging files
- Create small future research batches
- Validate counts and bucket assignments

Outputs:

- Frozen roster CSV
- Batch assignment CSV
- Findings template CSV
- Approved template CSV
- Short QA memo

Rules:

- No web research
- No pipeline wiring yet
- No content backfill yet

### Phase 2: Partial-Core Verification

Target:

- 8 `partial_core` nodes

Why first:

- Easiest cases
- Highest chance of quick completion
- Best place to validate workflow before larger research waves

Typical work:

- Verify existing `phd_year`, `phd_institution`, and employer values
- Add missing `email`, `country`, and `us_state`
- Correct stale or clearly wrong existing values where strong evidence exists

Batching:

- One compact phase, possibly 1 batch
- Keep prompts narrow and structured

### Phase 3: Email-Only Nodes

Target:

- 34 `email_only` nodes

Why second:

- Exact email strings reduce ambiguity
- Likely best yield per unit of context

Typical work:

- Use public email domain to identify institution or employer
- Recover PhD institution, year, current employer, country, and state where
  possible

Batching:

- 3 to 4 batches
- Prefer grouping by domain family or institution family
- Avoid mixing personal-email cases with clean university-domain cases

### Phase 4: Blank Manual Nodes

Target:

- 2 `blank_manual` nodes

Why third:

- Small count
- Usually more senior people with richer public profiles
- More research depth than email-only, but still manageable

Batching:

- One node per agent if parallelized

### Phase 5: Blank Student Nodes

Target:

- 34 `blank_student` nodes

Why last:

- Hardest cases
- Most likely to be sparse, ambiguous, or only locally visible through advisor
  branches

Typical work:

- Search by advisor subtree, department roster, dissertation repository,
  job-market page, lab page, or placement page
- Use advisor institution and field context aggressively

Batching:

- Group by advisor branch, not alphabetically
- One advisor branch per batch whenever practical
- Keep to 8 to 12 nodes max per batch

### Phase 6: QA and Promotion

Goal:

- Review all findings rows
- Promote only sufficiently supported rows into the approved file
- Leave ambiguous rows in findings only

Checks:

- No duplicate `node_id`
- No conflicting approved values across batches
- `clear_fields` only used when necessary and well supported
- Approved schema remains pipeline-compatible

### Phase 7: Pipeline Integration and Downstream Use

Goal:

- Decide whether to merge Gen 3 approved rows into the existing approved
  backfill flow or extend the pipeline for a separate Gen 3 approved file
- Rebuild network outputs only after the approved file is clean
- Revisit Gen 3 descriptives after enough metadata has been added

This phase is downstream of the research work and should not start early.

## Evidence Standards

Use a simple three-level system:

- `strong`
  - Official university directory
  - Official employer page
  - Dissertation repository
  - Personal site or CV with clear institutional corroboration
- `moderate`
  - Reliable public profile plus at least one corroborating source
  - RePEc or Google Scholar only when supported by a stronger institutional cue
- `weak`
  - Standalone profile pages, uncorroborated social pages, or loose name matches

Approval rule:

- `strong`: eligible for approved file
- `moderate`: eligible for approved file if identity is clear and values are not
  speculative
- `weak`: findings only, not approved

## Approval Rules

- Do not approve a row if identity is materially ambiguous
- Do not infer `country` or `us_state` unless current affiliation location is
  sufficiently clear
- Do not fill `us_state` just because `country` is `United States`
- Use `clear_fields` only when existing node data is clearly stale or wrong
- If advisor linkage is uncertain but person identity is clear, person-level
  metadata can still remain in findings; approval should be conservative

## Context-Window Management Rules

Every phase prompt should minimize context:

- Read this master plan first
- Then read only the specific files needed for that phase
- Keep batches to 8 to 12 nodes max
- Do not mix easy and hard buckets in the same prompt
- Prefer CSV output over prose
- Limit each node to at most 2 source URLs and 1 short evidence note
- End each batch with exactly three statuses:
  - `approved`
  - `hold`
  - `unresolved`

## Multi-Agent Coordination Rules

For multi-agent runs:

- Give each agent a disjoint file ownership set
- Do not have multiple agents editing the same CSV
- Keep one coordinator agent responsible for final QA and integration
- Workers should not expand scope beyond the current phase
- Workers should not start a later phase just because some cases look easy

## Recommended Prompt Preamble

Future phase prompts should start with something close to:

1. Read `Planning/Gen3_Nonrespondent_Backfill_Master_Plan.md` first.
2. Stay within the assigned phase only.
3. Use the fixed `040126` Gen 3 nonrespondent universe.
4. Do not change raw data or unrelated files.
5. Keep findings and approved outputs separate.
6. Keep outputs structured and concise.

## Phase Completion Criteria

### Phase 1 complete when:

- Roster, batch, findings-template, approved-template, and QA memo exist
- Roster count is 78
- Bucket counts match 8 / 34 / 2 / 34

### Phase 2 complete when:

- All 8 `partial_core` nodes have been reviewed
- Findings rows exist for all 8
- Any strong or moderate cases are promoted to approved

### Phase 3 complete when:

- All 34 `email_only` nodes have findings rows
- Batches stayed within context limits

### Phase 4 complete when:

- Both `blank_manual` nodes have been fully researched

### Phase 5 complete when:

- All 34 `blank_student` nodes have findings rows
- Advisor-branch grouping was preserved where practical

### Phase 6 complete when:

- Approved file is deduplicated and QA checked
- Findings and approved files are internally consistent

## Notes for Later Gen 3 Descriptives

Do not start Gen 3 descriptive statistics until there is materially better
coverage for nonrespondents. Right now the largest immediate gains are likely:

- `country`
- `current_employer`
- `email`
- `phd_institution`
- `phd_year`

This plan is intentionally staged so those fields can be improved before any
serious Gen 3 descriptive reporting.
