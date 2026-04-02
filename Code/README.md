# Code Directory

All scripts for the Mokyr Survey pipeline. Run from the project root
(`Mokyr Survey/`).

## Layout

| Folder | Purpose |
|--------|---------|
| **Shared/** | Reusable helpers imported by other scripts (name normalization) |
| **Survey/** | Qualtrics cleaning (`clean_survey.py`) and Q12a parsing (`parse_q12a.py`) |
| **Network/** | Node/edge graph build, master contact list, descriptive stats, visualization |
| **Validation/** | Audit validators, verification renderers, and descriptive-input checks |
| **Outreach/** | Response-tracking against outreach contact lists |
| **Orchestration/** | `refresh_downstream.py` -- single-command rebuild of all derived outputs |
| **Archive/** | Historical one-off scripts no longer part of the active pipeline |

## Active Pipeline Scripts

These are the scripts invoked by `refresh_downstream.py` or run directly:

```
Code/Survey/clean_survey.py                     # clean raw Qualtrics export
Code/Survey/parse_q12a.py                       # parse Q12a free-text student listings
Code/Network/build_network.py                   # build node/edge CSVs
Code/Network/describe_first_generation.py       # first-generation descriptive statistics
Code/Network/build_master_list.py               # one-row-per-person master CSV
Code/Network/build_outstanding_lists.py         # outstanding outreach lists
Code/Network/viz_network.py                     # interactive HTML genealogy
Code/Validation/validate_descriptive_inputs.py  # pre-descriptive input validation
Code/Validation/validate_gen1_audit.py          # Gen 1 browser-verification audit
Code/Validation/validate_gen2_capture_audit.py  # Gen 2 student-capture audit
Code/Validation/validate_gen3_public_student_verification.py  # Gen 3 verification
Code/Validation/validate_unresolved_research.py # unresolved-case research validation
Code/Validation/render_gen2_empty_q12a_public_recovery.py     # Gen 2 recovery rendering
Code/Validation/render_unresolved_research_report.py          # unresolved research report
Code/Outreach/check_outreach_responses.py       # outreach response tracking
Code/Orchestration/refresh_downstream.py        # pipeline orchestrator
```

## Invocation

All scripts are run from the project root:

```bash
# Individual script
python3 Code/Survey/clean_survey.py --input Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv

# Full pipeline rebuild
python3 Code/Orchestration/refresh_downstream.py --date 033126
```

Scripts resolve `PROJECT_ROOT` from their own file path, so they work from
any working directory. The orchestrator calls child scripts via subprocess
with `cwd=PROJECT_ROOT`.

## Import Convention

Scripts that import from other subfolders insert `PROJECT_ROOT / "Code"` into
`sys.path` at startup, then use package-style imports:

```python
from Shared.name_normalization import normalize_person_text
from Network.build_network import MANUAL_RESPONDENT_DEDUP
```
