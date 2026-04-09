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

Suggested future scripts:

- `match_authors.py`
- `fetch_openalex.py`
- `fetch_repec.py`
- `fetch_semantic_scholar.py`
- `build_bibliometric_panel.py`
- `build_openalex_panel.py`

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
