# Lineage Panel — Respond to Ran (042426)

## Context

Ran sent three comments about the **Lineage** tab on the Shape page (`mokyr-legacy-site/shape/index.html`, panel `#lineage`, lines 537–766):

1. **Replace the Abramitzky-branch example** — he wants the four-step chain **Mokyr → Abramitzky → Santiago Perez → Reem Zaiour** ([reemzaiour.com](https://www.reemzaiour.com/)) featured somewhere on the panel.
2. **Metric inconsistency** — chains 1–2 (Kosec, Townsend) show *syllabus appearances*; chains 3–4 (Kocaata, Teague) show *citations*. Make them consistent — best path is to show **both** on every node.
3. **Selection rationale** — how were the four chains chosen? Was there a criterion, or were they picked arbitrarily?

The lineage panel is fully hand-authored HTML (no data binding). Four `<section class="shape-lineage-view">` tabs, each with a `chain-rail` of four `chain-node` cards, wired by generic tab JS at `assets/site.js:132-212`.

---

## Answers (goes in reply to Ran + source notes)

### Q3 — selection criterion

Honest answer: the original four were **editorial picks** to showcase different Gen-1 branches. No systematic rule was applied — we acknowledge that.

**New criterion (going forward):** one chain per major Gen-1 sub-lineage, preferring chains where **public bibliometric data is available at every node** so the counts are independently verifiable. Under that rule, the new set is:

| # | Chain | Gen-1 branch | Why |
|---|-------|-------------|-----|
| 1 | Mokyr → Greif → Jha → Kosec | Greif | OS + GS at every node; Kosec's top paper is in *Nature Climate Change* |
| 2 | Mokyr → Abramitzky → Cullen → Townsend | Abramitzky (branch A) | OS + GS at every node; Townsend's "Social Capital" is in *Nature* |
| 3 | **Mokyr → Abramitzky → Perez → Zaiour (NEW)** | Abramitzky (branch B) | Ran's own lineage, end-to-end; Zaiour has public GS profile |
| 4 | Mokyr → Nye → Johnson → Teague | Nye | Third Gen-1 branch (GMU cluster) |

**Kocaata gets dropped** — he isn't on Google Scholar or Open Syllabus, and his current card already breaks form by showing "Supervised by N. Dwarkasing" in place of a count. He's what forced the original metric inconsistency in the first place.

### Q2 — consistent metric

Every `chain-node` carries **two count lines**, in this order:

1. `Syllabus appearances — <Open Syllabus person total>`
2. `Citations (Google Scholar) — <GS citations_all>`

When a scholar is not yet indexed in a given source (early-career), render `—` rather than `0` to avoid false precision.

All four `shape-source-note` paragraphs collapse to one unified sentence:

> *Counts are per-scholar totals from Open Syllabus (syllabus appearances) and Google Scholar (citations). Early-career scholars may not yet appear in one or both.*

### Q1 — new Zaiour chain

Replaces the Kocaata panel (tab id `lineage-tab-kocaata` → `lineage-tab-zaiour`, panel id `lineage-panel-kocaata` → `lineage-panel-zaiour`, tab chain label `Braggion · Dwarkasing` → `Abramitzky · Perez`, tab label `Kocaata` → `Zaiour`).

Featured papers and counts for the new chain:

| Gen | Person | Featured work | Syllabus | Citations |
|-----|--------|---------------|----------|-----------|
| Root | Joel Mokyr | *The Lever of Riches* (OUP, 1990) | 2,638 | *lookup at implementation time* |
| 1 | Ran Abramitzky | *Europe's Tired, Poor, Huddled Masses: Self-Selection and Economic Outcomes…* (AER, 2012) | 284 | 6,605 |
| 2 | Santiago Perez | *Intergenerational Occupational Mobility Across Three Continents* (J Econ Hist, 2017) | 31 | 1,520 |
| 3 | Reem Zaiour | *Changes in International Immigration and Internal Native Mobility after COVID-19 in the USA* (J Pop Econ, 2023) | — | 91 |

Featured paper for Zaiour is deliberately the migration/Covid piece (thematic fit with Ran/Santi's labor-migration line) rather than her highest-cited gun-violence paper. Flag this in the reply email so Ran can request a swap if he prefers the most-cited.

---

## Complete count table for all four chains

Use these values verbatim when rewriting the HTML.

| Person | Syllabus | Citations |
|--------|----------|-----------|
| Joel Mokyr | 2,638 | **TODO: lookup GS at impl time** |
| Avner Greif | 1,627 | 30,436 |
| Saumitra Jha | 248 | 2,122 |
| Katrina Kosec | 30 | 3,547 |
| Ran Abramitzky | 284 | 6,605 |
| Zoe Cullen | 5 | 6,990 |
| Wilbur Townsend | 33 | 1,676 |
| Santiago Perez | 31 | 1,520 |
| Reem Zaiour | — | 91 |
| John Nye | — | 2,563 |
| Noel Johnson | — | 3,413 *(OpenAlex fallback; GS not matched)* |
| Megan Teague | — | 84 |

Sources:
- Syllabus: `Data/Derived/OS_AllGens_041426.csv` column `citation_count` (person-level OS appearances).
- Citations: `Data/Derived/GS_AllGens_041626.csv` column `citations_all`.
- Fallback for Johnson only: `mokyr-legacy-site/assets/data/bibliometric-panel.json` (OpenAlex `cited_by_count`).
- Joel Mokyr: not in our CSVs — fetch his public GS profile total during implementation.

---

## Files to change

1. **`mokyr-legacy-site/shape/index.html`** — full rewrite of lines 537–766:
   - Tab 3: swap `kocaata` → `zaiour` (ids, `aria-label`, `ft-tab-chain`, `ft-tab-label`).
   - All four `shape-lineage-view` panels: every `chain-node` gets **two** `chain-count` lines (syllabus + citations, using the table above). Preserve the existing `chain-node-root` block for Joel — same four times.
   - All four `shape-source-note` paragraphs replaced with the unified one-sentence text.
   - Kocaata panel body fully rewritten as the Zaiour chain (titles, venues, glue labels `Mokyr → Abramitzky`, `Abramitzky → Perez`, `Perez → Zaiour`).

2. **`mokyr-legacy-site/assets/styles.css`** — add a small rule so two stacked `.chain-count` lines render cleanly. Suggestion: wrap the two counts in a `<div class="chain-counts">` and style with `display: flex; flex-direction: column; gap: 2px;`. Low-risk; no selector churn.

3. **`mokyr-legacy-site/assets/site.js`** — no logic changes. The tab handler at `:132-212` uses generic `role="tab"` queries and still works after the id rename. Do a pass to confirm no id strings are hardcoded.

4. **`Communications/Drafts/Ran_Reply_Lineage_042426.txt`** — new short draft reply addressing all three comments.

---

## Don't touch

- `genealogy-data.js`, `RAW_NODES`, `RAW_EDGES` — no lineage data lives there.
- The missing Abramitzky → Perez advisor edge in the network CSVs — that's a separate data-quality issue; flag it in the reply email as a follow-up, do not fix it in this pass.
- Network page (`network/mokyr-genealogy.html`) — out of scope.
- "No co-advisor surfacing" standing rule — remains in force; this change introduces no "also supervised by" language.

---

## Verification checklist

- [ ] Four tabs render in order: **Kosec · Townsend · Zaiour · Teague**.
- [ ] Every one of the sixteen `chain-node` blocks shows two count lines (or one + `—`).
- [ ] Joel Mokyr card is identical across all four panels.
- [ ] All four `shape-source-note` blocks carry the same unified text.
- [ ] Keyboard: ArrowLeft/Right cycles through all four tabs; Home/End jump to first/last; focus ring visible.
- [ ] Mobile at 375px and 390px: two-line count area doesn't overflow the rail; panels don't cause horizontal scroll.
- [ ] No references to "Zeki Kocaata", "Dwarkasing", or "Supervised by N. Dwarkasing" remain anywhere on the site (grep to confirm).
- [ ] No console errors; no 404s for referenced assets.
- [ ] Static HTML opens cleanly without a dev server (this site is file://-friendly).

---

## Reply email — outline for the draft

Three paragraphs, plain text, save to `Communications/Drafts/Ran_Reply_Lineage_042426.txt`:

1. **Chain swap** — acknowledge, confirm Zaiour chain is now live in tab 3; flag the featured-paper choice (migration paper vs. her most-cited gun-violence paper) so he can redirect if he wants.
2. **Metric consistency** — we're now showing both syllabus + citations on every node (per-scholar totals from OS and GS). Early-career scholars show `—` where they're not yet indexed.
3. **Selection rationale** — admit the original four were illustrative picks with no criterion. State the new rule: one chain per major Gen-1 branch, preferring chains with public bibliometric data at every node. Table of the new four.

Close with: "Happy to swap any individual chain — let me know."

---

## Execution order (for implementing agent)

1. Fetch Joel Mokyr's GS citation total (WebFetch his public profile) — only missing value.
2. Rewrite `shape/index.html:537–766`.
3. Add the small CSS rule.
4. Grep for removed strings (Kocaata, Dwarkasing, Braggion on the Shape page).
5. Load `shape/` in a browser, click through all four tabs, verify.
6. Draft the reply email.
7. Commit on `family-redesign` with subject: `shape: unify lineage metrics and swap Kocaata chain for Zaiour.`
