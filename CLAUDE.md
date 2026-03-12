# Mokyr Survey Project

## Working Principles

- This is an active research data collection project. **Never overwrite or delete raw data files.**
- Survey respondents are real academics — treat name/email data as sensitive.
- When in doubt about cleaning decisions, keep the respondent and flag for manual review.
- All dates in filenames use **MMDDYY** format (e.g., `013026` = January 30, 2026).
- Prefer simple, self-contained Python scripts over heavy dependencies.

## Project Overview

This project collects and cleans responses for an academic genealogy survey of Joel Mokyr's intellectual descendants. The survey is distributed in waves via Qualtrics to PhD students and advisees connected to Joel Mokyr. Ran Abramitzky is the PI.

The pipeline: **Qualtrics export → Raw CSV → Cleaning script → Cleaned CSV → Analysis**

## Directory Structure

```
Mokyr Survey/
├── CLAUDE.md                       # This file
├── Code/                           # All scripts
│   └── clean_survey.py             # Main cleaning pipeline (CLI)
├── Data/
│   ├── Raw/                        # Unmodified Qualtrics exports (*_Raw.csv)
│   ├── Cleaned/                    # Output of cleaning pipeline (*_Cleaned.csv)
│   ├── Contact_Lists/              # Wave invitation CSVs, seed email lists
│   └── Derived/                    # Data generated from survey responses
├── Logs/                           # Cleaning logs, duplicate reports
├── Output/                         # Figures, tables (future analysis)
└── Communications/                 # Email drafts, memos
```

## Survey Question Map

| Column | Question |
|--------|----------|
| Q1 | First name |
| Q2 | Last name |
| Q3 | Email address |
| Q4 | Headshot photo upload (optional) — has sub-columns: Id, Name, Size, Type |
| Q5 | Current institution or employer (selected choice) |
| Q5_1_TEXT | Institution/employer free text |
| Q5b | Current status/role (selected choice) |
| Q5b_10_TEXT | Role "Other" free text |
| Q6 | Country |
| Q6a | US state (if applicable) |
| Q7 | Personal website URL (optional) |
| Q8 | Academic connection to Joel Mokyr (selected choice) |
| Q8_13_TEXT | Connection "Other/I'm not sure" free text |
| Q9 | PhD institution |
| Q10 | PhD completion year (YYYY) |
| Q11 | PhD advisor name(s) connecting respondent to Mokyr |
| Q12 | Whether respondent has supervised PhD students (yes/no) |
| Q12a | List of past/current PhD students with emails |

Qualtrics metadata occupies columns 0–16 (StartDate, EndDate, Status, IPAddress, Progress, Duration, Finished, RecordedDate, ResponseId, etc.). The first 3 rows of any raw export are: header, question text, import IDs — data starts at row 4 (index 3).

## Data Pipeline

### Cleaning Script Usage

```bash
# Basic: clean a new raw export (auto-outputs to Data/Cleaned/)
python Code/clean_survey.py --input Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv

# With baseline protection (preserves respondents from a prior wave)
python Code/clean_survey.py \
  --input Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv \
  --baseline Data/Raw/Mokyr_Survey_Responses_013026_Raw.csv

# Custom output path
python Code/clean_survey.py \
  --input Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv \
  --output Data/Cleaned/custom_name.csv
```

Relative paths are resolved against the project root. The script auto-derives the output filename by replacing `_Raw` with `_Cleaned`.

### What the Cleaning Script Does

1. Strips Qualtrics metadata rows (rows 2–3)
2. Removes Survey Preview / test responses (Status column)
3. Removes incomplete responses (Finished != True)
4. Detects and removes gibberish/test entries (keyboard mashing, single-char names)
5. Deduplicates by (first_name, last_name), keeping the most complete entry
6. Trims whitespace from all cells
7. Writes cleaned CSV and a duplicates log to `Logs/`

### Baseline Protection

When `--baseline` is provided, the script loads a previous raw export and builds a protected set of respondents (by name, email, and ResponseId). Protected respondents are never removed, even if they would otherwise be flagged. This prevents data loss when re-cleaning cumulative exports.

### Q12a Parser + Wave Generation (parse_q12a.py)

```bash
# Full pipeline: parse Q12a from raw + generate Wave 4
python3 Code/parse_q12a.py \
  --raw Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv \
  --cleaned Data/Cleaned/Mokyr_Survey_Responses_020726_Cleaned.csv \
  --wave2 Data/Contact_Lists/Mokyr_Survey_Wave2.csv \
  --wave3 Data/Contact_Lists/Mokyr_Survey_Wave3.csv

# Just parse Q12a (no wave generation)
python3 Code/parse_q12a.py \
  --raw Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv \
  --cleaned Data/Cleaned/Mokyr_Survey_Responses_020726_Cleaned.csv \
  --parse-only
```

**Part A — Q12a Parsing:** Reads the **raw** CSV (not cleaned) to capture Q12a data from all finished respondents, including Survey Preview entries (e.g., Santiago Perez) that contain legitimate student listings. Parses free-text Q12a entries into structured advisor-student pairs. Handles diverse formats: `Name, Year, Email`, `Name Email`, `Name (Institution)`, `Year, Name, Institution`, email-only lines, and malformed emails (missing `@`).

**Output:** `Data/Derived/Advisors_and_Reported_Students_MMDDYY.csv`

**Part B — Wave Generation:** Identifies non-respondents from previous waves + new Q12a students not yet contacted. Uses the **cleaned** CSV for respondent identification. Deduplicates by email and name.

**Output:** `Data/Contact_Lists/Mokyr_Survey_Wave4.csv`

## Common Tasks

### New Qualtrics Export Arrived
1. Download from Qualtrics, name it `Mokyr_Survey_Responses_MMDDYY_Raw.csv`
2. Place in `Data/Raw/`
3. Run: `python Code/clean_survey.py --input Data/Raw/Mokyr_Survey_Responses_MMDDYY_Raw.csv --baseline Data/Raw/<previous_raw>.csv`
4. Check `Logs/Mokyr_Survey_Duplicates.csv` for any issues
5. Review cleaning statistics printed to stdout

### New Wave of Invitations
1. Prepare contact list CSV
2. Place in `Data/Contact_Lists/` as `Mokyr_Survey_WaveN.csv`
3. Draft invitation email in `Communications/`

### Analysis
Place output figures and tables in `Output/`.

## Key Constants (in clean_survey.py)

- **Column indices** (auto-discovered from header, fallback defaults): Q1→17, Q2→18, Q3→19, ResponseId→8, Status→2, Finished→6, Progress→4
- **LEGITIMATE_SHORT_NAMES**: Real 2-letter names that should not be flagged as gibberish (e.g., `or`, `hu`, `wu`, `yi`, `xu`)
- **GIBBERISH_PATTERNS**: Known test/keyboard-mashing strings (e.g., `asdf`, `qwerty`, `test`)

## Data File Naming Convention

- Raw exports: `Mokyr_Survey_Responses_MMDDYY_Raw.csv`
- Cleaned data: `Mokyr_Survey_Responses_MMDDYY_Cleaned.csv`
- Early cleaned files (pre-pipeline): `Mokyr_Survey_Responses_MMDDYY.csv` (no `_Cleaned` suffix)
- Contact lists: `Mokyr_Survey_WaveN.csv`
- Derived Q12a data: `Advisors_and_Reported_Students_MMDDYY.csv`
