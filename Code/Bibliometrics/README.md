# Bibliometrics Code

Scripts in this folder will handle bibliometric enrichment for the Mokyr
genealogy, using the master contact list and network outputs as the starting
point.

Planned responsibilities:

- author matching across external scholarly sources
- work and citation retrieval
- field and topic enrichment
- source-level reconciliation and confidence scoring
- export of bibliometric panels used in downstream descriptive analysis

Intended source stack:

- OpenAlex as the primary source
- RePEc / CitEc as economics-specific enrichment
- Semantic Scholar as a citation cross-check
- ORCID as an identity-resolution supplement
- Crossref as DOI metadata verification

Expected upstream inputs:

- `Data/Derived/Master_Contact_List_{date}.csv`
- `Data/Derived/Network_Nodes_{date}.csv`
- `Data/Derived/Network_Edges_{date}.csv`

Current source-specific pipelines:

- `fetch_openalex.py`
- `build_openalex_panel.py`
- `GoogleScholar/`
- `RePEc/`

Suggested future scripts:

- `match_authors.py`
- `fetch_semantic_scholar.py`
- `build_bibliometric_panel.py`
## OpenAlex Quickstart

Store the API key outside the repo:

```bash
export OPENALEX_API_KEY="your_openalex_key"
export OPENALEX_MAILTO="research@stanford.edu"
```

Run a basic author search:

```bash
python3 Code/Bibliometrics/fetch_openalex.py \
  author-search --query "Joel Mokyr"
```

Fetch one author by OpenAlex ID:

```bash
python3 Code/Bibliometrics/fetch_openalex.py \
  author --author-id A5103336489
```

Fetch the most-cited works for one author:

```bash
python3 Code/Bibliometrics/fetch_openalex.py \
  works-by-author --author-id A5103336489 \
  --select id,display_name,publication_year,cited_by_count,doi
```

Build the dated OpenAlex match panel from the master list:

```bash
python3 Code/Bibliometrics/build_openalex_panel.py --date 040126
```

Apply a reviewed decision file during the build:

```bash
python3 Code/Bibliometrics/build_openalex_panel.py \
  --date 040126 \
  --manual-decisions Data/Derived/OpenAlex_All_Decisions_040126.csv
```

By default, the pipeline fetches only the first `works` page per matched author.
Because works are sorted by `cited_by_count:desc`, that is enough to recover the
top 10 most-cited papers while keeping refreshes fast. Pass
`--max-works-pages 0` if you need every work.

Outputs:

- `Data/Derived/OpenAlex_Scholar_Matches_{date}.csv`
- `Data/Derived/OpenAlex_Match_Review_{date}.csv`
- `Data/Derived/OpenAlex_Top_Papers_{date}.csv`
- `Data/Derived/Bibliometric_Panel_{date}.csv`
- `Data/Derived/Bibliometric_Panel_{date}.json`

Optional website copy:

```bash
python3 Code/Bibliometrics/build_openalex_panel.py \
  --date 040126 \
  --manual-decisions Data/Derived/OpenAlex_All_Decisions_040126.csv \
  --website-output mokyr-legacy-site/assets/data/bibliometric-panel.json
```

The dated JSON in `Data/Derived/` remains the full analyst artifact. The
optional website copy is filtered for public use: unresolved or suspicious rows
stay in the file with `public_ready=false`, but top-paper and topic fields are
suppressed unless the row is public-safe.

## OpenAlex Review Workflow

Run the audit first to identify rows that still need manual classification:

```bash
python3 Code/Bibliometrics/audit_review_decisions.py \
  --decisions Data/Derived/OpenAlex_Ambiguous_Decisions_040126.csv
```

For local smoke tests without API calls, use `--provider mock`.

Generate the default current-review queue:

```bash
python3 Code/Bibliometrics/generate_review_html.py --date 040126
```

The default page writes `tmp/openalex_review/openalex_claude_followup_review_040126.html`
and loads `OpenAlex_Claude_Review_Followup_040126.csv`, which contains the latest
rows that still need manual review after the Claude pass. The page shows Claude's
recommendation alongside the editable candidate list; export
`openalex_claude_followup_review_decisions_040126.csv` from the page.

If you want the older post-audit flagged queue instead, request it explicitly:

```bash
python3 Code/Bibliometrics/generate_review_html.py \
  --mode flagged \
  --date 040126
```

If you still need the original unresolved candidate picker, request it
explicitly:

```bash
python3 Code/Bibliometrics/generate_review_html.py \
  --mode unresolved \
  --date 040126
```

Merge reviewed decisions into the canonical union file:

```bash
python3 Code/Bibliometrics/merge_review_decisions.py \
  --audited ~/Downloads/openalex_flagged_review_decisions_040126.csv
```

Pass `--rebuild` to regenerate the panel with the merged decisions file.

## RePEc Quickstart

Install the lightweight HTML dependencies if needed:

```bash
python3 -m pip install requests beautifulsoup4
```

Build the dated RePEc manifest from the master list and network nodes:

```bash
python3 Code/Bibliometrics/RePEc/repec_manifest.py --date 040126
```

Consolidate batch outputs into one canonical enrichment file:

```bash
python3 Code/Bibliometrics/RePEc/consolidate_enrichment.py \
  --manifest Data/Derived/RePEc_Manifest_040126.jsonl \
  --enrichment Data/Derived/RePEc_Enrichment_040126_Batch_*.jsonl \
  --output Data/Derived/RePEc_Enrichment_040126.jsonl \
  --summary-output Data/Derived/RePEc_Enrichment_040126_Summary.csv
```

Fetch RePEc / IDEAS / CitEc enrichment:

```bash
python3 Code/Bibliometrics/RePEc/fetch_repec.py \
  --manifest Data/Derived/RePEc_Manifest_040126.jsonl \
  --output Data/Derived/RePEc_Enrichment_040126.jsonl \
  --delay 2
```

Run a second-pass robustness sweep on sparse rows from a prior enrichment:

```bash
python3 Code/Bibliometrics/RePEc/fetch_repec.py \
  --manifest Data/Derived/RePEc_Manifest_040126.jsonl \
  --prior-enrichment Data/Derived/RePEc_Enrichment_040126.jsonl \
  --output Data/Derived/RePEc_Enrichment_040126_Robust.jsonl \
  --review-output Data/Derived/RePEc_Review_040126.csv \
  --override-csv Data/Derived/RePEc_Handle_Overrides_040126.csv \
  --robustness-pass \
  --delay 2
```

Validate the enrichment JSONL:

```bash
python3 Code/Bibliometrics/RePEc/validate_enrichment.py \
  --manifest Data/Derived/RePEc_Manifest_040126.jsonl \
  --enrichment Data/Derived/RePEc_Enrichment_040126.jsonl
```

Merge RePEc fields into the bibliometric panel:

```bash
python3 Code/Bibliometrics/RePEc/merge_enrichment.py \
  --date 040126 \
  --enrichment Data/Derived/RePEc_Enrichment_040126.jsonl
```

If a scholar's handle is known and automatic discovery is brittle, either add
`repec_handle_override` to the manifest row or place `node_id,repec_handle_override,notes`
rows in `Data/Derived/RePEc_Handle_Overrides_040126.csv` and pass it with `--override-csv`.
