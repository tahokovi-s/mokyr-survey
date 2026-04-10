# Google Scholar Enrichment Task

## Task

For each scholar in your batch, find their Google Scholar profile and extract bibliometric data. Also find their personal or faculty website if possible.

You must produce exactly one output JSON line for each input scholar.

## Input

You will receive a JSONL file with one scholar per line. Each line includes:

- `node_id`
- `full_name`
- `phd_institution`
- `phd_year`
- `current_employer`
- `advisor`
- `search_queries`

## Output

Write one JSON object per line to your output file. Every line must conform to this schema:

```json
{
  "node_id": "R-R_xxx",
  "lookup_status": "found",
  "confidence": "high",
  "google_scholar": {
    "url": "https://scholar.google.com/citations?user=xxx",
    "name_on_profile": "Ariell Zimran",
    "affiliation_on_profile": "Vanderbilt University",
    "interests": ["Economic History", "Labor Economics", "Immigration"],
    "works_count": 36,
    "cited_by_count": 1200,
    "h_index": 9,
    "i10_index": 7,
    "coauthors": ["Ran Abramitzky", "Leah Boustan"]
  },
  "personal_website": {
    "url": "https://ariellzimran.com",
    "self_described_field": "Economic History"
  },
  "top_papers": [
    {
      "title": "Immigration and the...",
      "year": 2020,
      "citations": 150,
      "venue": "AER"
    }
  ],
  "disambiguation_notes": "Matched by institution (Vanderbilt) + research interests (Economic History)"
}
```

Allowed values:

- `lookup_status`: `found`, `not_found`, `ambiguous`
- `confidence`: `high`, `medium`, `low`

Rules:

- If `lookup_status = "found"`, `google_scholar.url` must be a valid `https://scholar.google.com/citations?user=...` URL.
- If `lookup_status = "not_found"`, omit `google_scholar` or set it to `null`.
- If `lookup_status = "ambiguous"`, you may include the best candidate in `google_scholar`, but only if you clearly explain the ambiguity.
- `top_papers` can contain at most 5 papers.
- Use integers for counts and years where possible.

## Search Strategy

1. Use the provided `search_queries` with WebSearch.
2. Prioritize Google Scholar profile URLs matching `scholar.google.com/citations?user=`.
3. Fetch the profile with WebFetch and extract:
   - profile name
   - profile affiliation
   - interests
   - total citations
   - h-index
   - i10-index
   - articles count
   - top 5 papers by citations
   - co-authors if visible
4. Search for the scholar's personal or faculty website:
   - `"{full_name} {institution}"`
   - or the homepage link shown from the Google Scholar profile

## Disambiguation Rules

- Require at least two matching signals before marking `found`.
- Acceptable signals include:
  - name + institution
  - name + research field
  - name + known co-author, including the advisor when plausible
- For common names, require an institution match.
- If multiple plausible profiles remain and you cannot determine the correct one, set `lookup_status = "ambiguous"`.
- Never guess. `ambiguous` is better than a wrong match.

## Edge Cases

- Maiden or married names: search both variants.
- Diacritics: search with and without accents.
- Retired scholars may have old affiliations or sparse profiles.
- Non-academic careers may have no Scholar profile. Use `not_found`.
- Generation 3 current students may have minimal Scholar pages.

## Worked Examples

### Example 1: Found

```json
{
  "node_id": "R-R_demo_found",
  "lookup_status": "found",
  "confidence": "high",
  "google_scholar": {
    "url": "https://scholar.google.com/citations?user=demo123",
    "name_on_profile": "Ariell Zimran",
    "affiliation_on_profile": "Vanderbilt University",
    "interests": ["Economic History", "Labor Economics", "Immigration"],
    "works_count": 36,
    "cited_by_count": 1200,
    "h_index": 9,
    "i10_index": 7,
    "coauthors": ["Ran Abramitzky", "Leah Boustan"]
  },
  "personal_website": {
    "url": "https://ariellzimran.com",
    "self_described_field": "Economic History"
  },
  "top_papers": [
    {
      "title": "Immigration and the American Dream",
      "year": 2020,
      "citations": 150,
      "venue": "AER"
    },
    {
      "title": "Another paper...",
      "year": 2018,
      "citations": 90,
      "venue": "JEH"
    }
  ],
  "disambiguation_notes": "Matched by exact name, Vanderbilt affiliation, and interests in Economic History and Immigration."
}
```

### Example 2: Not Found

```json
{
  "node_id": "R-R_demo_not_found",
  "lookup_status": "not_found",
  "confidence": "medium",
  "google_scholar": null,
  "personal_website": null,
  "top_papers": [],
  "disambiguation_notes": "Searched all provided queries plus name + institution combinations. Found no Google Scholar profile URL and no credible faculty page linking to a Scholar profile."
}
```

### Example 3: Ambiguous

```json
{
  "node_id": "R-R_demo_ambiguous",
  "lookup_status": "ambiguous",
  "confidence": "low",
  "google_scholar": {
    "url": "https://scholar.google.com/citations?user=demo999",
    "name_on_profile": "J. Smith",
    "affiliation_on_profile": "University of Somewhere",
    "interests": ["Economics"],
    "works_count": 18,
    "cited_by_count": 240,
    "h_index": 6,
    "i10_index": 4,
    "coauthors": []
  },
  "personal_website": null,
  "top_papers": [
    {
      "title": "Trade and Growth",
      "year": 2017,
      "citations": 48,
      "venue": "Journal of Economics"
    }
  ],
  "disambiguation_notes": "Two plausible Google Scholar profiles share the same surname and field. The best candidate is an economist, but the affiliation does not clearly match the known institution, so the match remains ambiguous."
}
```

## Quality Checklist

- Every manifest scholar has exactly one output line.
- Every `found` record has a valid Google Scholar profile URL.
- Every `found` record includes `h_index`, `cited_by_count`, `i10_index`, and `works_count`.
- Every `not_found` or `ambiguous` record explains the outcome in `disambiguation_notes`.
- No duplicate `node_id` values appear in the output.
