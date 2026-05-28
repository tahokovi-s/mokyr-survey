# Shape Page Narrative Redesign Master Plan

Version date: 2026-04-16
Status: approved, ready for implementation
Primary surface: `mokyr-legacy-site/shape/`

## Purpose

This file is the stable reference document for the `/shape/` page redesign
(known on the home page as "Joel's Legacy by the Numbers"). Future Claude Code
prompts or human builders working on this page should read this file first,
then only the minimum additional files needed for the current task.

Goal: redesign the existing 8-panel scrollytelling flow into a 10-panel arc
that weaves Google Scholar (GS) bibliometric impact data alongside the
existing structural and Open Syllabus (OS) content. The new arc reads
**roots → readership** — who the family is, what they have written, what is
still being read.

This plan is the output of a 2-round adversarial Codex review. Every
numerical claim has been verified against the underlying CSVs and every
per-panel disclosure follows the rules below.

## Locked Product Decisions

These decisions are fixed unless the user explicitly changes them later.

- Total panel count is **10** (current live page has 8).
- Arc order is: Overview → Structure → Branches → Cohorts+Hubs →
  **Still being read** → **Generations of impact** → **Works that travel**
  → Syllabi → Lineage → Reach.
- Cohorts and Training Hubs are **merged into a single panel** (new panel 4)
  to make room for GS impact panels without bloating the scroll.
- Lineage panel (OS 4-node chain Mokyr→Greif→Jha→Kosec) is **kept as-is**
  and sits alongside the new GS-based "Works that travel" panel. They are
  distinct: citation reach vs teaching reach.
- Gen 4 is **excluded from all GS impact panels** (n=5, only 2 matched —
  too thin to summarize). Mentioned only in the footer caveat strip.
- Page numerator/denominator standard: **tree size = 382** (not the stale
  386 on the live page). See "Denominator Reconciliation" below.
- Numbers are **hardcoded in HTML** using the existing `data-count-to`
  pattern. No live data loading. Drift is caught by a read-only verifier
  script (see Step 7).
- **Panel 5 leads with 201,607 lifetime citations** as the hero number.
  Recent / still-cited / currently-productive are support tiles.
- Per-panel source notes (below), not a single footer caveat, carry the
  coverage disclosure. A one-line footer strip covers Gen 4 omission only.

## Denominator Reconciliation (FIX FIRST)

The live `shape/index.html` has an **internal contradiction**:

- Panel 1 hero tile: `data-count-to="386"` (line 56)
- Panel 2 generation bars: 76 + 186 + 115 + 5 = 382
- `Data/Derived/GS_AllGens_041626.csv` row count: 382
- `Data/Derived/Network_Nodes_040126.csv` rows with generation ∈ {1,2,3,4}: 382

The `386` came from an older `Network_Nodes` count that included 4 non-root
nodes with blank `generation`. **All panels in the redesigned page use 382**
as the tree-size denominator. Step 1 of implementation is to update this
literal across the page; it is blocking for every subsequent step.

## Current Site Context

Current relevant files:

- `mokyr-legacy-site/shape/index.html` — the page itself; all 10 panels
  live in this single file.
- `mokyr-legacy-site/assets/styles.css` — panel-level CSS.
- `mokyr-legacy-site/assets/site.js` — scroll-spy logic for the left-rail
  progress nav.

Current behavior:

- 8 panels, hardcoded numbers with `data-count-to` count-up animations,
  left-rail progress nav, single OS source note on line 278 of the HTML.

## Hard Constraints

- Static site: plain HTML, CSS, and JS only. No framework.
- Numbers are hardcoded in the HTML. Do **not** introduce a live data
  fetch from CSVs at page load. Drift is caught offline by the verifier.
- Mobile support is required. The new split layout in panel 4 must
  collapse to single-column on narrow screens.
- `Data/Derived/` is gitignored. CSVs used as sources for hardcoded
  numbers must not be committed, but the verifier script (which reads
  those CSVs) can be committed.
- GS coverage is 40% of the tree (154 of 382). Every GS panel must
  disclose that matched-subset framing, without undermining the warm
  tone.

## Data Ground Truth (all numbers verified 2026-04-16)

All figures below are computed directly from the source CSVs. A builder
must not re-derive these — use the numbers as given and let the verifier
catch drift.

### Source CSVs

- `Data/Derived/GS_AllGens_041626.csv` — 382 rows (header excluded), 14
  columns. Canonical GS master for all 4 generations.
- `Data/Derived/GS_Top_Papers_By_Generation_041626.csv` — 71 rows (Gens
  1–3 only). Top 5 cited papers from the top 5 cited scholars per gen.
- `Data/Derived/OS_AllGens_041426.csv` — 377 rows (Gens 1–3 only). OS
  base does not include Gen 4.
- `Data/Derived/Network_Nodes_040126.csv` — 382 rows with generation
  assigned (root Mokyr + 381 descendants across 4 gens).

### Tree-wide totals (clean GS matches only)

| Metric | Value | Note |
|---|---|---|
| Total tree nodes | 382 | Network rows with generation ∈ {1,2,3,4} |
| GS-matched scholars | 154 | 40.3% coverage |
| Lifetime citations | 201,607 | Sum of `citations_all` on matched rows |
| Last-5-yr citations | 111,103 | 55.1% of lifetime |
| Scholars still cited | 151 | `citations_recent > 0`; 98.1% of matched |
| Currently productive | 45 | `h_index_recent >= 10`; 29.2% of matched |
| Lifetime i10 papers | 1,639 | Not displayed but available |
| Recent i10 papers | 1,248 | Not displayed but available |

### Per-generation (clean GS matches only; Gen 4 excluded from panels)

| Gen | Total | Matched | Coverage | median H | median Cit | recent-share% |
|---|---|---|---|---|---|---|
| 1 | 76 | 28 | 36.8% | 10 | 858 (raw 858.5 → displayed 858) | 36.4% → 36% |
| 2 | 186 | 86 | 46.2% | 7 | 332 | 62.8% → 63% |
| 3 | 115 | 38 | **33.0% (thinnest)** | 4 | 90 | 79.1% → 79% |
| 4 | 5 | 2 | 40.0% | — | — | — (omitted) |

### H-index top 5 (for panel 5 sidebar)

1. Avner Greif (gen 1) — 46
2. Scott Baker (gen 2) — 37
3. Karen Clay (gen 2) — 37
4. Alessandro Nuvolari (gen 1) — 34
5. Werner Troesken (gen 2) — 31

### Per-generation top paper (for panel 7)

| Gen | Title | Authors | Venue | Year | Cites |
|---|---|---|---|---|---|
| 1 | Institutions and the Path to the Modern Economy | A. Greif | Cambridge University Press | 2006 | 5,115 |
| 2 | Measuring Economic Policy Uncertainty | SR Baker, N Bloom, SJ Davis | QJE 131(4) | 2016 | 17,159 |
| 3 | Social capital I: measurement and associations with economic mobility | R Chetty et al. (incl. W Townsend) | Nature 608 | 2022 | 1,036 |

### Open Syllabus ground truth

- OS evaluated base: 377 scholars (Gens 1–3 only). Gen 4 is not in the OS
  source.
- OS-matched: 93 (`quality == "match"` in `OS_AllGens_041426.csv`).
- Panel 8 keeps existing numbers: Joel = 2,638 appearances; students
  combined = 5,319. Existing top-10 rank list is retained.

## Final Panel Flow

Each panel below gives a builder-ready spec: eyebrow, H2, lead, visual,
source note, data.

### Panel 1 — Overview (keep, revise)

- Eyebrow: **Overview**
- H2: **"A family, measured."**
- Visual: 4 hero tiles using the existing `data-count-to` pattern:
  - `382` — label "mapped scholars"
  - `4` — label "generations"
  - `76` — label "direct students"
  - `201607` — label "lifetime citations across the 154 scholars we matched
    on Google Scholar" (NEW — tease for panel 5)
- Status: Keep. Change `data-count-to="386"` → `382`. Add the new 4th tile.

### Panel 2 — Structure (keep as-is)

- Eyebrow: **Structure**
- H2: "The weight lands in the second generation."
- Visual: existing gen bars (76 / 186 / 115 / 5).
- Status: No changes.

### Panel 3 — Branches (keep as-is)

- Eyebrow: **Branches**
- H2: "A few first-students carry large families of their own."
- Visual: existing Gen-1 subtree rank (Abramitzky 152 / Greif 45 / Nye 22
  / Braggion 13 / Botticini 10).
- Status: No changes.

### Panel 4 — Cohorts & Hubs (merge old 4 + 5)

- Eyebrow: **Cohorts**
- H2: **"A younger family, trained in a widening set of places."**
- Lead: "Median PhD year slides from 2014 to 2026; training migrates from
  Northwestern to Stanford to Davis."
- Visual: split two-column layout, single-column on narrow screens:
  - Left: the existing PhD-year timeline ribbon (Gen 1 2014, Gen 2 2020,
    Gen 3 2022, Gen 4 2026).
  - Right: the existing 3 hub cards (Gen 1 Northwestern 64/76, Gen 2
    Stanford 77/186, Gen 3 UC Davis 17/115).
- Status: Delete the standalone Training Hubs panel. Fold its hub cards
  into the right column of the Cohorts panel.

### Panel 5 — Still being read (NEW)

- Eyebrow: **Impact**
- H2: **"The tree isn't just growing — it's still being read."**
- Lead (MANDATORY, this exact narrative structure — echoes panel 4 before
  pivoting to impact): *"A younger family, trained in more places — and
  one still actively writing. Across the 154 scholars we could match on
  Google Scholar, their work has been cited 201,607 times, more than half
  of those in just the last five years."*
- Visual: 4 hero tiles + compact ranked sidebar strip
  - Tile 1: `201607` — label "lifetime citations"
  - Tile 2: `111103` — label "last-5-yr citations"
  - Tile 3: `98` with `%` suffix — label "still cited in the last 5 years"
  - Tile 4: `45` — label "currently productive — h-index of 10 or more in
    the last 5 years"
  - Below tiles, a one-line ranked strip:
    **"H-index top five: Greif 46 · Baker 37 · Clay 37 · Nuvolari 34 ·
    Troesken 31"**
- Source note (REQUIRED): *"Google Scholar totals cover the 154 of 382
  scholars (40%) we could match. The 98% and 'currently productive' figures
  describe that matched subset, not the whole tree."*
- Status: NEW panel. Also absorbs the H-index sidebar that would
  otherwise bloat panel 7.

### Panel 6 — Generations of impact (NEW)

- Eyebrow: **Generations**
- H2: **"Each generation carries the torch differently."**
- Visual: 3 mini-cards side-by-side (collapse to stacked on mobile). Each
  card shows medH / medCit / recent-share% plus a one-line tag:
  - Gen 1 card: H `10` · Cit `858` · Recent `36%` — tag "**Still
    accumulating — the older work keeps getting cited.**"
  - Gen 2 card: H `7` · Cit `332` · Recent `63%` — tag "**The tree's
    biggest share of impact at scale.**"
  - Gen 3 card: H `4` · Cit `90` · Recent `79%` — tag "**Most
    forward-facing citation profile — 79% of their citations are from the
    last five years.**"
- Source note (REQUIRED): *"Based on the 152 matched scholars in Gens 1–3
  (28, 86, 38). Coverage is thinnest in Gen 3 (33%), highest in Gen 2
  (46%); per-generation medians reflect those subsets."*
- Terminology rule: this panel **must NOT** use the word "active" or
  "currently active" — that wording collides with panel 5's "currently
  productive." Use "forward-facing citation profile" for the Gen 3 tag.
- Status: NEW panel.

### Panel 7 — Works that travel (NEW)

- Eyebrow: **Works**
- H2: **"The papers doing the traveling."**
- Lead: "One book from Gen 1, one paper from Gen 2, one from Gen 3 — the
  pieces most read outside our walls."
- Visual: 3 vertically-stacked work cards. Each card: title, authors,
  venue + year, citation-count badge, one-line editorial blurb. **No
  sidebar** — that ranking is now in panel 5.
  - Gen 1 card: *Institutions and the Path to the Modern Economy* /
    A. Greif / Cambridge University Press, 2006 / 5,115 cites.
  - Gen 2 card: *Measuring Economic Policy Uncertainty* / SR Baker,
    N Bloom, SJ Davis / QJE 131(4), 2016 / 17,159 cites.
  - Gen 3 card: *Social capital I: measurement and associations with
    economic mobility* / R Chetty et al. (incl. W Townsend) / Nature
    608, 2022 / 1,036 cites.
- Source note (REQUIRED): *"Top paper per generation, chosen by lifetime
  Google Scholar citations among the top 5 matched scholars per gen
  (top-scholars approach — not exhaustive)."*
- Status: NEW panel.

### Panel 8 — Syllabi (keep, rewrite lead)

- Eyebrow: **Syllabi**
- H2: "Assigned, generation after generation."
- Lead (REVISED, pair with panel 7): **"Citation is one channel; teaching
  is another. Open Syllabus finds Joel on 2,638 course pages; his
  students together on 5,319."**
- Visual: existing 2,638 / 5,319 bars + existing top-10 ranked list.
- Source note (REVISED denominator): *"Source: Open Syllabus Analytics.
  93 of 377 scholars evaluated (Gens 1–3 only; Gen 4 is not yet in the OS
  source base). Figures are lower bounds."* — uses OS's own evaluated
  base (377), not the tree (382), because the OS source does not cover
  Gen 4 at all.
- Status: Keep. Only changes are the lead paragraph and the denominator
  in the source note.

### Panel 9 — Lineage (keep as-is)

- Eyebrow: **Lineage**
- H2: "Ideas carried four generations forward."
- Visual: existing 4-node chain: Mokyr → Greif → Jha → Kosec with each
  scholar's top-syllabi work and OS appearance count.
- Status: No changes. This panel is the OS counterpart to panel 7's GS;
  the two are intentionally distinct (teaching vs citation reach).

### Panel 10 — Reach (keep, repositioned as closer)

- Eyebrow: **Reach**
- H2: "And the map keeps widening."
- Visual: existing top-8 countries bar (US 212 / UK 20 / China 15 /
  Italy 13 / Israel 12 / India 11 / Canada 10 / Spain 10).
- Status: No changes.

### Footer caveat strip

Under panel 10, muted `<p class="shape-source-note">`:

*"Gen 4 (n=5, 2 matched) is omitted from the Google Scholar impact panels
above; too thin to summarize meaningfully."*

The footer is deliberately minimal. Per-panel notes on 5, 6, 7, 8 carry
the full coverage story for their respective data sources.

## Bridge Prose & Terminology Rules

### The 4 → 5 pivot is the riskiest transition

Panel 5's lead paragraph must echo panel 4's "younger, more widely
trained" framing before introducing the 201k number. Without the echo,
the page reads as a jump from institutional diffusion to a brag total.
The exact lead is specified in the Panel 5 spec above and is **not**
subject to copy edits without re-reviewing the arc.

### "Current" vocabulary

Only panel 5 tile 4 may use "currently productive" (definition:
`h_index_recent ≥ 10`). Panel 6 Gen 3 tag MUST use "forward-facing
citation profile" and MUST NOT use "most currently active." Three
different gen-6 tags, three different framings, one metric per card.

## Coverage Table (use as the single source of truth on matched-subset
framing)

| Gen | Total | GS-matched | GS coverage | OS-matched | OS coverage (of evaluated 377) |
|-----|-------|-----------|-------------|-----------|--------------------------------|
| 1 | 76 | 28 | 36.8% | ~25 | — |
| 2 | 186 | 86 | 46.2% | — | — |
| 3 | 115 | 38 | 33.0% | — | — |
| 4 | 5 | 2 | 40.0% | 0 (not in OS) | — |
| **All** | **382** | **154** | **40.3%** | **93** | **24.7% of 377** |

## Implementation Steps

### Step 1 — Fix the 386 → 382 denominator (BLOCKING)

In `mokyr-legacy-site/shape/index.html`:

- Line 56: change `data-count-to="386"` to `data-count-to="382"` and the
  inner text `386` to `382`.
- Line 278 (OS source note): change from
  `"Source: Open Syllabus Analytics. 93 of 386 scholars matched; figures
  are lower bounds."`
  to
  `"Source: Open Syllabus Analytics. 93 of 377 scholars evaluated (Gens
  1–3 only; Gen 4 is not yet in the OS source base). Figures are lower
  bounds."`
- Search the rest of the file for `386`. Any copy that refers to the tree
  total must become `382`.

Nothing else is touched in this step. Commit independently so the fix is
visible in isolation.

### Step 2 — Hardcode the new panels 1, 5, 6, 7

- Panel 1: add a 4th hero tile with `data-count-to="201607"` and the
  specified label.
- Panel 5: full new section per the Panel 5 spec. Include the H-index
  strip under the four tiles and the per-panel source note.
- Panel 6: full new section per the Panel 6 spec, including the Gen 1 /
  Gen 2 / Gen 3 tags. Do NOT include any Gen 4 card.
- Panel 7: full new section per the Panel 7 spec. 3 work cards, no
  sidebar, the source note.

CSS: add rules to `assets/styles.css` for the new hero-tile strip, the
3-card gen layout, and the stacked work cards. Reuse existing
`.shape-stat-card`, `.shape-bar`, `.shape-source-note` classes where
possible.

### Step 3 — Merge Cohorts + Hubs into new panel 4

Delete the standalone Training Hubs panel. Inside the Cohorts panel,
wrap the content in a two-column CSS grid. Left column is the existing
PhD-year timeline; right column is the three existing hub cards. On
narrow screens, the grid collapses to a single column.

### Step 4 — Rewrite panel 8 Syllabi lead

Replace the current lead with the specified "Citation is one channel;
teaching is another…" lead. Visual unchanged.

### Step 5 — Reorder panels in the HTML source

Final DOM order: Overview / Structure / Branches / Cohorts+Hubs /
Still-being-read / Generations-of-impact / Works-that-travel /
Syllabi / Lineage / Reach.

### Step 6 — Update the left-rail progress nav

Current nav has 8 entries. New nav has 10 — add "Impact", "Generations",
"Works" as entries 5, 6, 7. Update the scroll-spy JS in
`assets/site.js` to track 10 sections.

### Step 7 — Add `tmp/verify_shape_page.py` read-only drift detector

Create a new script at `tmp/verify_shape_page.py`. It parses the HTML
(regex on `data-count-to` and known literal strings in panels 5, 6, 7,
8 and the per-panel source notes) and asserts each number matches the
source CSV read directly. The verifier MUST couple each number to its
correct source layer:

1. Panel 1 hero tile `382` ≡ count of rows in
   `Data/Derived/Network_Nodes_040126.csv` where `generation ∈
   {"1","2","3","4"}`. (Network source, not GS.)
2. Sum of panel 2 gen-bar values ≡ panel 1 hero tile. (Internal
   consistency; catches any future 386-style regression.)
3. Panel 5 four tile values computed directly from
   `Data/Derived/GS_AllGens_041626.csv`:
   - sum of `citations_all` on matched rows = `201607`
   - sum of `citations_recent` on matched rows = `111103`
   - `round(100 * count(citations_recent > 0) / count(matched))` = `98`
   - `count(h_index_recent >= 10)` = `45`
4. Panel 5 H-index strip — names AND values match top 5 matched rows
   sorted by `h_index_all` desc: Greif 46 / Baker 37 / Clay 37 /
   Nuvolari 34 / Troesken 31.
5. Panel 6 three gen-cards computed per gen from
   `Data/Derived/GS_AllGens_041626.csv`:
   - `median(h_index_all)` for Gens 1/2/3 = `10, 7, 4`
   - `median(citations_all)` for Gens 1/2/3 = `858, 332, 90` (rule: Gen
     1 raw median 858.5 displays as 858)
   - `round(100 * sum(citations_recent) / sum(citations_all))` per gen
     = `36, 63, 79`
6. Per-panel disclosure numbers:
   - Panel 5 note `154 of 382 (40%)` — `count(in_gs=True)` and network
     total.
   - Panel 6 note `152 matched scholars (28, 86, 38)` and `Gen 3 (33%)`
     + `Gen 2 (46%)` — per-gen matched counts from GS master.
   - Panel 8 OS note `93 of 377` — `count(quality="match")` in
     `OS_AllGens_041426.csv`.
7. Panel 7 three work-card citation counts ≡ rows where `rank_in_gen ==
   1` in `Data/Derived/GS_Top_Papers_By_Generation_041626.csv` for Gens
   1/2/3: 5115, 17159, 1036.

The verifier exits non-zero on any mismatch. It does NOT call
`tmp/top_papers_by_gen.py` (which regenerates the CSV as a side effect)
and does NOT parse `tmp/gs_descriptives.py` stdout (brittle to helper
format changes). All calculations are recomputed directly inside the
verifier from the CSVs.

## Verification

After all steps:

1. Run `python3 tmp/verify_shape_page.py` from the project root — must
   exit 0.
2. Open `mokyr-legacy-site/shape/index.html` in a browser; scroll from
   top to bottom; verify all 10 panels render in order and the left-rail
   progress nav highlights each as it scrolls into view.
3. Spot-check that panel 5 count-up animations trigger on first viewport
   entry.
4. Narrow the browser to mobile width; verify the Cohorts+Hubs split
   panel collapses to single-column gracefully. Verify the 3-card gen
   layout in panel 6 stacks vertically on mobile.
5. Read aloud the panel 5 lead paragraph and confirm it explicitly
   echoes panel 4's "younger, more widely trained" frame before the
   201k number.
6. Confirm panels 5 and 6 do NOT both use "active" or "currently active"
   for their current-vs-lifetime language.
7. Confirm that `Gen 4` is not named in any GS panel body (only in the
   footer caveat strip).
8. Run `mokyr-legacy-site` locally (Eleventy dev server if present) and
   confirm desktop and mobile layouts behave.

## Non-Goals / Out of Scope

- Live data loading from CSVs at page render. Keep hardcoded HTML +
  offline verifier. Revisit only if refresh cadence becomes painful.
- Any changes to `/family/` (network viz) or `/about/` pages.
- Gen 4 impact content (permanently excluded from the GS panels).
- Refactoring existing panels' CSS beyond what's needed for the new
  visual shapes (4-tile hero + H-index strip, 3-card gen mini, 3
  vertically-stacked work cards, 2-column split for Cohorts+Hubs).
- OpenAlex paper-level integration — that is a separate future project;
  the existing `Data/Derived/OpenAlex_*.csv` files are not used by this
  page.

## Change Log

- 2026-04-16: initial version, drafted from approved plan at
  `/Users/tahokovi/.claude/plans/calm-noodling-wren.md` after two
  rounds of adversarial Codex review.
- 2026-04-21: Ran 041726 feedback supersedes the earlier 10-panel arc for `/shape/`.
