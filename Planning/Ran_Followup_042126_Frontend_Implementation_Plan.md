# Ran Follow-Up (042126) — Frontend Implementation Plan

Version date: 2026-04-22
Status: ready for implementation
Primary surface: `mokyr-legacy-site/` (home, shape, family, network)
Source of asks: `Communications/Drafts/Ran_Follow_Up_Mokyr_Site_042126.txt`
Screenshots on iPhone: `IMG_7935.png`, `IMG_7936.png` (referenced in Ran's email; request them from the user if not already in the repo).

## Scope

Implement action items 1, 2, 3, 4, 6, and 7 from Ran's April 21, 2026 emails.
Explicitly **out of scope** for this plan: adding photos to tree tooltips (item 5)
and the full-screen tree walkthrough (item 8) — those are handled separately.

Do **not** touch `Data/Raw/` or survey CSVs. This plan is frontend-only.

## Standing rule (applies site-wide)

**Do not surface co-advisor / secondary-advisor relationships anywhere in the
public UI.** We are not displaying "Also supervised by …", "Co-advised by …",
"Additional advisor", or any equivalent phrase on any page. Every person is
shown under a single primary advisor. This is a deliberate editorial
decision for standardization — it avoids asymmetry (we only know co-advisor
relationships when respondents happened to mention them, which is biased)
and it makes the Santi-type bug class impossible by construction. The
underlying data can still carry multiple parent edges; the UI must render
only the primary parent.

Treat this as a hard constraint when touching the family tree, the network
node panel, or any future panel. If the data layer still exposes a
`secondaryAdvisorById` map, the renderer must ignore it (or the map should
be removed outright — see item 7 below).

---

## Repository map (the only files you need)

Site pages (edit these):

- `mokyr-legacy-site/index.html` — welcome / home page (90 lines)
- `mokyr-legacy-site/shape/index.html` — "By the Numbers" scrollytelling page (774 lines)
- `mokyr-legacy-site/family/index.html` — Family Tree + Network Map tabs (151 lines)
- `mokyr-legacy-site/network/mokyr-genealogy.html` — full D3 network page (1249 lines, generated)
- `mokyr-legacy-site/assets/styles.css` — shared styles for all site pages
- `mokyr-legacy-site/assets/family-tree.js` — Family Tree renderer
- `mokyr-legacy-site/assets/genealogy-data.js` — derived GENEALOGY object (built from RAW_NODES/RAW_EDGES) — includes `secondaryAdvisorById` used for "Also supervised by" label

Generator (edit these if their output is regenerated):

- `Code/Network/viz_network.py` — generates `mokyr-legacy-site/network/mokyr-genealogy.html` and `Output/mokyr-genealogy-<date>.html`.
  - Line 807: footer credit string — must be updated in lockstep with the static HTML footer edits so re-runs don't regress.

Derived data (read-only for item 7):

- `Data/Derived/Network_Edges_<date>.csv` — edges (`source,target,edge_type,confidence`)
- `Data/Derived/Network_Nodes_<date>.csv` — nodes with `id,label,generation,...`
- `Data/Derived/Advisors_and_Reported_Students_<date>.csv` — Q12a-parsed advisor/student pairs, by respondent
- `Data/Derived/Manual_Edges_<date>.csv` — manually added advisor edges
- Latest date is the largest `<date>` suffix; use it.

Local baselines for visual diffs:

- `Output/tier1-baseline-mobile.png`, `tier1-baseline-desktop.png` (home)
- `Output/tier2-baseline-mobile.png`, `tier2-baseline-desktop.png` (shape)
- `Output/tier3-baseline-mobile.png`, `tier3-baseline-desktop.png` (family)

Existing Playwright artifacts and harness: `Output/playwright/`.

---

## Action items

### 1 — iPhone: overlapping text on the Shape page

Problem: Ran reports "see attached text over other text" on iPhone Safari.
The Shape page uses full-bleed `story-panel--full-bleed` sections with
absolutely positioned "anchor" numbers (e.g. the 29-countries reach anchor
at `shape/index.html:153–156`). At narrow widths the story-copy stack and
the anchor/visual stack can collide.

Fix strategy:

- Audit every `story-panel*` + `story-panel--full-bleed` section in
  `shape/index.html` at 375 px (iPhone SE) and 390 px (iPhone 13/14) widths.
- In `styles.css`, promote the narrow-viewport breakpoint for shape panels
  to a single column layout with a clear vertical rhythm. Absolute-positioned
  anchors (e.g. `.reach-anchor`, `.shape-stat-card-citation` source note)
  should become static/flow on ≤640 px.
- Ensure `story-copy` and `story-visual` children never share a grid row at
  mobile widths; use `grid-template-columns: 1fr` and `gap: clamp(16px, 4vw, 28px)`.
- Prevent text-on-text by removing any `position: absolute; inset: 0;`
  overlays on `.story-panel-backdrop-*` at ≤640 px; keep the colored
  backdrop but push all content into the flow.
- Check the home page (`index.html`) hero and stat grid at the same widths.
- Check the family page (`family/index.html`) intro kicker strip at the
  same widths — `.ft-kicker-strip` can wrap but should not overlap the H1.

Acceptance:

- No element overlaps any other at 375 px or 390 px widths on the home,
  shape, and family pages.
- Screenshots saved to `Output/tier1-after-mobile.png`, `tier2-after-mobile.png`,
  `tier3-after-mobile.png`, replacing current "after" images, with a short
  diff note written to the PR body.

### 2 — iPhone: Family Tree cuts off at Gen 2, cannot scroll to Gen 3

Problem: On iPhone, the Family Tree expands Joel → 76 Gen 1 branches fine,
but opening a Gen 1 branch (to reveal Gen 2 students) and then a Gen 2
student (to reveal Gen 3) leaves Gen 3 off-screen with no way to scroll to
it. This is almost certainly an overflow / height-containment issue in the
`.ft-tree-root` container or an ancestor `.ft-panel-frame`.

Fix strategy:

- Inspect `mokyr-legacy-site/family/index.html:100` (`<div id="ft-tree-root" class="ft-tree-root"></div>`)
  and the surrounding `#ft-tree-panel` — verify the container allows
  unbounded vertical growth on mobile (no `max-height`, no `overflow: hidden`,
  no `position: fixed` ancestor that clips).
- In `styles.css`, on ≤640 px, ensure:
  - `.ft-tree-root` has `overflow: visible` and no `max-height`
  - `.ft-panel-frame` does not apply a fixed height on mobile
  - The page's main/shell does not trap scroll inside the panel (no nested
    scroll container; the document itself should scroll)
- If the renderer adds per-level indentation that pushes Gen 3 off the right
  edge, reduce indentation on mobile (e.g. `--ft-indent: clamp(8px, 2.5vw, 20px)`)
  so deep nodes remain readable.
- When a node is expanded, smoothly scroll the **newly revealed children**
  into view. In `mokyr-legacy-site/assets/family-tree.js` around the expand
  branch handler (see `toggleBranch` called at line ~199), after children
  render, call `newChildrenUl.scrollIntoView({ block: 'nearest', behavior: 'smooth' })`
  (guarded by `prefers-reduced-motion`).
- Verify with Playwright on iPhone 13 viewport: expand Joel → a Gen 1 → a
  Gen 2 → confirm Gen 3 children are visible or reachable by page scroll.

Acceptance:

- On 390×844 viewport, a user can open Joel → a specific Gen 1 (e.g.
  "Avner Greif") → a specific Gen 2 → a specific Gen 3 student, and every
  revealed node is reachable by normal page scroll.
- Screenshot of a Gen 3 node visible on iPhone viewport saved to
  `Output/tier3-after-mobile.png` (overwriting baseline after approval).

### 3 — Rename "First-gen students" → "Direct students" on welcome page

Problem: Label is ambiguous with first-generation college students.

Exact edits:

- `mokyr-legacy-site/index.html:49` — change
  `<span class="stat-label">First-gen students</span>`
  to `<span class="stat-label">Direct students</span>`.
- `mokyr-legacy-site/family/index.html:43` — change
  `<span><strong>77</strong> first-generation students</span>`
  to `<span><strong>77</strong> direct students</span>`.
- Do **not** touch `shape/index.html:91` — it already reads "Direct students".
- Do **not** touch `mokyr-legacy-site/design-proposals/*` — those are
  archived design drafts, not shipped pages.

Acceptance:

- Project-wide grep for `first-gen|first-generation` in live site files
  returns zero matches outside `design-proposals/`.

### 4 — Reorder Shape page: move "Where the family works today" up to right after the countries figure

Current panel order in `shape/index.html`:

1. `#overview`   (line 72)
2. `#structure`  (line 102)
3. `#reach`      (line 145) — the countries figure
4. `#cohorts`    (line 311)
5. `#impact`     (line 342)
6. `#generations` (line 374)
7. `#jobs`       (line 438) — "Where the family works today."
8. `#syllabi`    (line 510)
9. `#lineage`    (line 537)

Target order: move `#jobs` to position 4, so it sits between `#reach` and
`#cohorts`:

1. `#overview`
2. `#structure`
3. `#reach`
4. **`#jobs`**  ← moved
5. `#cohorts`
6. `#impact`
7. `#generations`
8. `#syllabi`
9. `#lineage`

Edits required:

- Move the entire `<section ... id="jobs" ...>` block (currently lines
  438–508) to sit directly after the closing tag of the `#reach` section
  (the `</section>` just before `#cohorts` at line 311). Preserve the
  existing block verbatim — no text changes.
- Update the side-nav (`shape-progress`) in `shape/index.html:32–68` so
  the `Careers` item (currently under chapter 02 "The Work" on line 55)
  moves to chapter 01 "The Tree" alongside Reach. Target chapter 01 list:
  Overview → Structure → Reach → **Careers** → Cohorts. Chapter 02 then
  contains: Impact → Generations → Syllabi.
- Confirm scrolly progress highlighting still works (the
  `data-story-nav-item` keys already match; the nav re-render just follows
  the new DOM order).
- The text "Where the family works today" appears only in the `#jobs`
  heading (`shape/index.html:441`). Do not introduce a duplicate reference.

Acceptance:

- DOM order matches the target list above.
- Side-nav visually matches the target chapter layout.
- Scroll narrative still reveals panels in the correct order (no broken
  anchor links, no duplicated nav entries).

### 6 — Update attribution line on every page footer

New attribution (Ran's exact words):

> "For Joel's 80th. Project led by Ran Abramitzky. I thank Jensen Ahokovi for his superb assistance."

Exact edits:

- `mokyr-legacy-site/index.html:84` — change
  `<p class="footer-credit">For Joel's 80th. Survey led by Ran Abramitzky.</p>`
  to the new attribution (preserve the `&rsquo;` / apostrophe style already
  used on the page; plain `'` in the current file, so plain `'` is fine).
- `mokyr-legacy-site/network/mokyr-genealogy.html:595` — same string.
- `Code/Network/viz_network.py:807` — same string (this is the generator
  for the network HTML; keep static HTML and generator in sync so the
  next `python3 Code/Network/viz_network.py` run does not regress).
- Check `shape/index.html` and `family/index.html` — they currently have
  no `.footer-credit`. Do **not** add one unless the user asks (Ran is
  asking for a text change, not a layout change).

Acceptance:

- Grep `"For Joel's 80th"` across the repo returns the new line in all
  three locations (home HTML, network HTML, Python generator) and no stale
  "Survey led by" phrasing on live pages.

### 7 — Remove all co-advisor surfacing from the UI (kills the Santi bug class by construction)

Ran flagged two of Santi's students displayed as "also supervised by Ran
Abramitzky" when they were not. Rather than diagnose and patch individual
bad edges, we are **removing the entire co-advisor UI feature** — see the
"Standing rule" at the top of this plan. This is the fix.

Why remove instead of repair:

- We only ever know co-advisor relationships when a respondent happens to
  mention them, so the data is structurally biased. Surfacing it implies
  completeness we cannot guarantee.
- The rendering logic in `genealogy-data.js` will label any extra parent
  edge as "Also supervised by <label>" regardless of whether that edge
  came from a trustworthy Q12a report, a Manual_Edges override, or a
  name-match false positive. Any one of those is sufficient to produce
  the Santi-style bug; removing the surface removes the whole class.

Hard-required edits (UI — ship these first):

1. `mokyr-legacy-site/assets/family-tree.js`, around the current
   "Also supervised by" block (≈ lines 184–189): delete the block that
   reads `const coAdv = GENEALOGY.secondaryAdvisorById ...` and the
   `li.appendChild(coNote)` call that follows. The family tree should
   render no secondary-advisor line under any node.
2. `mokyr-legacy-site/assets/styles.css`: if `.ft-co-note` has dedicated
   styling, remove the rule (or leave orphaned — either is fine, but
   prefer removing).
3. `mokyr-legacy-site/network/mokyr-genealogy.html`: audit the node
   detail panel / tooltip code for any "Also supervised", "Co-advised",
   "Secondary advisor", "Additional advisor", or similar label. Remove
   those render paths. Note: `line 585` contains the phrase "direct
   advisors and direct students" as descriptive copy — leave that copy
   intact, but ensure the actual panel renders only the primary advisor
   (not a list of all parent edges).
4. Mirror the same removal in `Code/Network/viz_network.py` if that
   generator emits any co-advisor label in its node-panel HTML. Do not
   let the next regeneration reintroduce the phrase.

Hard-required edits (data layer — ship alongside the UI edits so nothing
downstream depends on a map we no longer use):

5. `mokyr-legacy-site/assets/genealogy-data.js`: remove the
   `secondaryAdvisorById` block (≈ lines 75–90 in the current file) and
   drop `secondaryAdvisorById` from the exported `GENEALOGY` object at
   the bottom. This prevents any future renderer from accidentally
   surfacing it.
6. Leave the underlying `RAW_EDGES` array untouched. Multiple-parent
   edges can continue to exist in the graph (descendant counts still
   walk all advisor edges intentionally — see the comment above
   `descendantCountById` in `genealogy-data.js`). Only the
   *presentation* of secondary parents is removed.

Audit (lightweight, keep for the record — do this only after the UI
edits above are committed):

- Grep the repo for any residual occurrence of
  `secondaryAdvisor\|Also supervised\|Co-advised\|co_advisor\|coAdvisor\|additional advisor`
  in live site files (`mokyr-legacy-site/`, excluding `design-proposals/`)
  and in `Code/`. Every hit should be gone.
- Briefly record in the PR body: (a) the approximate number of nodes
  that previously showed a secondary-advisor line (a quick count from
  the pre-change `genealogy-data.js` would tell us how many entries in
  `secondaryAdvisorById` were non-null), and (b) confirmation that the
  post-change UI renders zero such lines.
- No dedicated audit CSV or audit markdown is required for this item.

Acceptance:

- Grep for `secondaryAdvisor|Also supervised|Co-advised|coAdvisor|additional advisor`
  in `mokyr-legacy-site/` (excluding `design-proposals/`) and in `Code/`
  returns zero matches.
- Opening the family tree and expanding every branch shows no secondary
  advisor text under any node — including, specifically, Santi's Gen 3
  students.
- The network page's node-detail panel shows only the primary advisor
  (or none, for root).
- Nothing in the data pipeline was modified; `Data/Raw/` and
  `Data/Derived/` are untouched.

---

## Execution order

Do items in this order (each is independent except where noted):

1. Item 3 (label rename) — smallest change; ship first.
2. Item 6 (footer attribution) — small, touches the generator.
3. Item 4 (shape panel reorder + nav update).
4. Item 1 (mobile overlap fix) — CSS only.
5. Item 2 (mobile tree scroll fix) — CSS + JS.
6. Item 7 (remove co-advisor surfacing from UI + data layer).
   - Run this last because it deletes a section of `genealogy-data.js`
     and a block in `family-tree.js`; committing it separately keeps
     the diff legible.

---

## Verification checklist (before handoff back)

- [ ] Home, shape, family rendered at 375 px, 390 px, 768 px, 1280 px with
      no overlapping text.
- [ ] On 390 px viewport, opening Joel → Gen 1 → Gen 2 → Gen 3 reaches a
      visible Gen 3 node via page scroll.
- [ ] Grep `first-gen\|first-generation` in live site returns no hits
      outside `design-proposals/`.
- [ ] Shape page `#jobs` section sits between `#reach` and `#cohorts`;
      side-nav mirrors this.
- [ ] Grep `"Survey led by Ran Abramitzky"` returns zero hits in live
      site and `viz_network.py`; new attribution string appears in all
      three places.
- [ ] Grep `secondaryAdvisor\|Also supervised\|Co-advised\|coAdvisor\|additional advisor`
      in `mokyr-legacy-site/` (excluding `design-proposals/`) and in
      `Code/` returns zero matches.
- [ ] Family tree shows no "Also supervised by" line under any node
      after all branches are expanded.
- [ ] Network page node-detail panel shows only a primary advisor.
- [ ] Before/after screenshots for home, shape, family saved under
      `Output/tier{1,2,3}-after-{mobile,desktop}.png`.
- [ ] No raw CSVs in `Data/Raw/` were modified.

---

## Things you must NOT change

- Do not modify `Data/Raw/` or any survey export.
- Do not rewrite `RAW_NODES`/`RAW_EDGES` in `genealogy-data.js` by hand —
  it is generated; edit the Python pipeline and regenerate.
- Do not add photos to tree tooltips (deferred, item 5).
- Do not alter the hero subtitle copy ("Four generations. 388 scholars.")
  — the 388 figure is a deliberate editorial number (see
  `Planning/Shape_Page_Narrative_Redesign_Master_Plan.md` for the
  denominator discussion).
- Do not ship a layout change on shape/family footers unless explicitly
  requested — item 6 is text-only.

---

## Questions to flag to the user, not block on

These do not block implementation but should be surfaced in the PR body:

- iPhone screenshots `IMG_7935.png` / `IMG_7936.png` from Ran's email —
  we do not have them in the repo. Implementation can proceed from the
  structural analysis above, but the user may want to attach them for
  the PR record.
- The new footer string is long enough that on very narrow viewports it
  may wrap to 3 lines. Acceptable per spec, but flag if it looks bad.
