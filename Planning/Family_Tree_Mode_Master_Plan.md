# Family Tree Mode Master Plan

Version date: 2026-04-10
Status: active working plan
Primary surface: `mokyr-legacy-site/family/`

## Purpose

This file is the stable reference document for the `/family` redesign in
`mokyr-legacy-site`. Future Claude Code prompts for this project should read
this file first, then only the minimum additional files needed for the current
task.

The goal is to replace the current single-entry family page with a two-mode
experience:

- `Family Tree`: a controlled, traditional-feeling lineage browser
- `Network Map`: the existing interactive D3 network

The MVP is the `Family Tree` mode. The `Network Map` should remain available,
but the new work should not center that view.

## Locked Product Decisions

These decisions are fixed unless the user explicitly changes them later.

- Mode labels are `Family Tree` and `Network Map`
- `/family` must present both modes clearly
- `Family Tree` is the default featured option
- `Family Tree` uses controlled interaction, not a dead static image
- Tree mode initial state shows only the Joel Mokyr root node
- Initial helper text should non-invasively prompt the user to click the root
  to begin
- First interaction expands all 76 Gen 1 branches at once
- Gen 1 ordering is explicit editorial surname ordering, A-Z
- Visible node badges should show `total descendants`, not direct advisees
- Once a branch is opened below Gen 1, sibling branches remain visible but
  collapsed
- Co-advised people appear once under a primary branch, with a small
  cross-reference note for the secondary advisor
- Tree mode should run inline in `family/index.html`, not inside an iframe
- `Network Map` should be lazy-loaded only when selected
- Mobile support is required from the start

## Current Site Context

Current relevant files:

- `mokyr-legacy-site/family/index.html`
- `mokyr-legacy-site/network/mokyr-genealogy.html`
- `mokyr-legacy-site/assets/styles.css`
- `mokyr-legacy-site/assets/site.js`

Current behavior:

- `/family` currently embeds the existing D3 genealogy network in an iframe
- The data is baked into `network/mokyr-genealogy.html`
- There is no shared external genealogy data file yet

## Hard Constraints

These facts constrain every implementation decision.

- The genealogy is a DAG, not a pure tree
- 26 nodes have two or more parents because of co-advising
- Gen 2 has 186 nodes, so any "show everything at once" layout will fail
- Ran Abramitzky alone has 75 direct students, so even a single large branch
  can become visually dense immediately
- Current genealogy data is embedded as inline JS in a large HTML file, not in
  a reusable JSON or JS asset
- This is a static site: plain HTML, CSS, and JS only
- Avoid introducing a framework unless there is an overwhelming reason

## Product Interpretation

The phrase "static version" should not appear in the product UI. Internally it
refers to the new mode, but visitor-facing language should use:

- `Family Tree`
- `Network Map`

Reason:

- `Static` sounds less useful
- The new tree will still use interaction for clarity
- `Family Tree` communicates the traditional lineage framing more clearly

## MVP Definition

The MVP is not a full chart that renders the entire genealogy at once. It is a
collapsible family-tree browser with a traditional visual language.

MVP user experience:

1. Visitor lands on `/family`
2. Visitor sees a short intro plus two mode choices
3. Visitor chooses `Family Tree`
4. Tree view opens with only Joel Mokyr visible
5. A small helper callout says to click Joel Mokyr to open the tree
6. Clicking Joel reveals all 76 Gen 1 branches, sorted by surname A-Z
7. Each Gen 1 node displays total descendant count
8. Clicking a branch reveals its children while sibling branches remain visible
   but collapsed
9. Visitor can move across the tree without losing basic context
10. Visitor can switch to `Network Map` at any time

## Non-Goals for the MVP

The following items are explicitly deferred.

- Full left-to-right D3 pedigree chart
- Minimap
- Multi-branch simultaneous deep expansion
- "Render the entire genealogy at once" layouts
- Backend data services
- Search across the entire website
- Rebuilding the existing network visualization from scratch

## Information Architecture

Recommended structure for `/family`:

- Intro section
- Two mode tiles or buttons
- Inline `Family Tree` container
- Lazy-loaded `Network Map` iframe container
- Secondary mode-switch control once a mode is active

Recommended page flow:

- On first load, show the chooser and emphasize `Family Tree`
- Do not auto-expand the tree before user interaction
- When `Family Tree` is selected, render the root-only state immediately
- When `Network Map` is selected, set the iframe `src` at that moment

## Tree Interaction Contract

These are behavior requirements, not suggestions.

### Initial Tree State

- Only Joel Mokyr is visible
- Helper copy appears near the root node
- Example copy: `Click Joel Mokyr to open the tree.`
- Helper should disappear after first meaningful interaction

### First Expansion

- Clicking the Joel root expands all 76 Gen 1 branches
- Gen 1 branches are sorted by explicit surname ordering, A-Z
- Each Gen 1 node shows total descendant count
- A short note should make the ordering explicit, such as:
  `First-generation branches are ordered alphabetically by surname.`

### Deeper Expansion

- Clicking a visible branch expands that branch downward
- Sibling branches remain visible but collapsed
- The interface should preserve the currently active path clearly
- One active open path is the default behavior
- If a user opens a different branch at the same depth, the previous branch at
  that depth collapses

### Co-Advised Nodes

- Co-advised people appear once in the tree
- Each such node needs a small textual note naming the secondary advisor
- The primary parent used in the tree must come from an explicit override
  policy, not an accidental implementation detail

### Search

- Search is part of the MVP once Gen 1 has been expanded
- It should help users find people quickly among the many branches
- Search behavior can focus or highlight matching nodes, but should not
  silently mutate tree structure in surprising ways

### Navigation

- Breadcrumbs are recommended if the implementation uses a path-like state
- URL hash state is recommended from the start
- Browser back behavior should not feel broken

## Data Architecture

The current data layout is the main technical blocker. The first engineering
task should be data extraction and normalization.

### Required Data Refactor

Extract the embedded genealogy data from
`mokyr-legacy-site/network/mokyr-genealogy.html` into a shared asset, likely:

- `mokyr-legacy-site/assets/genealogy-data.js`

That shared asset should be consumable by both:

- the new `Family Tree` mode
- the existing `Network Map`

If migrating the network view immediately is too risky, step one may be:

- create the shared data file first
- keep the network view untouched temporarily
- migrate the network view to the shared data file only after the tree works

### Required Derived Structures

The implementation should derive, at minimum:

- `ROOT_ID`
- `peopleById`
- `childrenById`
- `parentIdsById`
- `primaryParentById`
- `secondaryParentNotesById`
- `descendantCountById`
- `gen1IdsSorted`

### Surname Sorting Policy

Gen 1 sorting must be editorial and explicit.

Do not rely on:

- splitting on the last whitespace token
- ad hoc browser locale behavior
- accidental data order from the source arrays

Instead:

- create a surname sort key helper
- maintain an override table for ambiguous surnames or particles
- tie-break identical surname keys with full display name

### Multi-Parent Resolution Policy

The tree must encode a primary parent policy explicitly.

Default policy:

- prefer the advisor edge that best preserves a readable lineage path
- if needed, prefer the lower-generation or primary academic lineage used by
  the project team

But:

- known co-advised cases should be reviewed manually
- final exceptions should live in an override table

## Proposed File Layout

Likely MVP file footprint:

- `mokyr-legacy-site/family/index.html`
- `mokyr-legacy-site/assets/styles.css`
- `mokyr-legacy-site/assets/site.js`
- `mokyr-legacy-site/assets/family-tree.js`
- `mokyr-legacy-site/assets/genealogy-data.js`

Optional later files:

- `mokyr-legacy-site/family/tree.html`
- `mokyr-legacy-site/assets/tree.js`

Guidance:

- keep family-tree-specific logic out of `site.js` where practical
- prefer a dedicated `family-tree.js` for tree state and rendering
- keep `styles.css` as the shared stylesheet unless it becomes unmanageable

## UI Components Required

MVP components:

- Mode chooser tiles or buttons
- Tree root node
- Helper callout
- Tree branch node
- Descendant count badge
- Surname ordering note
- Search input
- Breadcrumbs or equivalent path indicator
- Change-view control
- Lazy-loaded network iframe shell

Node content should usually include:

- Person name
- Institution if available
- PhD year if available
- Total descendant count
- Secondary advisor note where applicable

## Accessibility Requirements

Do not treat accessibility as a polish pass.

Required:

- All interactive controls use semantic buttons or links
- Tree interactions are keyboard reachable
- Focus states are visible
- Helper copy is readable but not disruptive
- Reduced-motion users should not depend on animation for comprehension
- Color should not carry branch state alone
- Mobile tap targets must be large enough

## Mobile Requirements

Tree mode exists specifically to avoid the current iframe friction on mobile.

Required:

- No nested iframe scroll in tree mode
- Readable root and branch nodes on narrow screens
- Controlled overflow behavior
- Search and mode switching remain easy on mobile
- Expansion behavior should not require precise pointer targeting

Acceptable fallback:

- the layout may stack more vertically on mobile
- dense branch presentation may simplify visually on narrow widths

## Suggested Implementation Phases

### Phase 1: Freeze Data Contract

Goal:

- define the shared genealogy asset and its derived structures

Tasks:

- extract embedded nodes and edges into a reusable JS file
- compute descendant counts
- define surname sort keys and overrides
- define primary parent overrides for co-advised nodes

Outputs:

- `mokyr-legacy-site/assets/genealogy-data.js`
- documented override tables for surname sorting and primary parents

### Phase 2: Build Family Mode Shell

Goal:

- replace the current single-purpose family page with a chooser plus inline
  tree shell

Tasks:

- update `family/index.html`
- add mode chooser UI
- add family tree container
- add network container
- lazy-load the network iframe on selection

Outputs:

- updated `mokyr-legacy-site/family/index.html`

### Phase 3: Implement Tree State and Rendering

Goal:

- ship the root-only state, first expansion, and branch-expansion behavior

Tasks:

- render Joel root node
- show helper callout
- expand all 76 Gen 1 branches on root click
- render descendant counts
- implement one-open-path behavior
- implement co-advised notes
- implement search
- add optional breadcrumbs and hash state

Outputs:

- `mokyr-legacy-site/assets/family-tree.js`

### Phase 4: Styling and Responsive Behavior

Goal:

- make the experience visually coherent with the existing site and usable on
  desktop and mobile

Tasks:

- style chooser
- style root and branch nodes
- style helper callout, badges, breadcrumbs, and search
- tune responsive behavior
- confirm readable spacing and hierarchy

Outputs:

- updated `mokyr-legacy-site/assets/styles.css`

### Phase 5: QA and Refinement

Goal:

- validate the full chooser and tree experience end to end

Tasks:

- test tree mode on desktop and mobile widths
- test keyboard interaction
- test first-load chooser behavior
- test root expansion and branch expansion
- test search
- test network lazy-loading
- test reduced motion

Outputs:

- bug fixes in the relevant files

## Agent Workstreams

This project is suitable for one lead and four workers.

### Lead Agent

Responsibilities:

- keep this plan as the source of truth
- define the shared data contract before parallel work begins
- review worker outputs
- integrate in a safe order

Integration order:

1. data foundation
2. tree behavior
3. styling
4. QA fixes

### Worker A: Data Foundation

Primary ownership:

- `mokyr-legacy-site/assets/genealogy-data.js`

Secondary ownership only if approved by lead:

- `mokyr-legacy-site/network/mokyr-genealogy.html`

Responsibilities:

- extract source data
- define derived structures
- compute descendant counts
- implement surname sorting and overrides
- implement primary parent overrides

### Worker B: Family Tree Structure and Behavior

Primary ownership:

- `mokyr-legacy-site/family/index.html`
- `mokyr-legacy-site/assets/family-tree.js`

Responsibilities:

- chooser behavior
- root-only state
- first expansion
- branch expansion
- search
- breadcrumbs or equivalent path handling
- network lazy-loading

### Worker C: Styling

Primary ownership:

- `mokyr-legacy-site/assets/styles.css`

Responsibilities:

- visual treatment of chooser and tree
- responsive behavior
- helper callout and badge styling
- preserving the commemorative site tone

### Worker D: QA and Accessibility

Primary ownership:

- verification and bug reporting first

Code ownership after lead assignment:

- only the files needed for approved bug fixes

Responsibilities:

- browser QA
- mobile QA
- keyboard and focus QA
- reduced-motion QA
- regression checks for the network map

## Merge and Coordination Rules

All future Claude worker prompts should reinforce these rules.

- Each worker owns a narrow write scope
- Workers are not alone in the codebase
- Workers must not revert others' edits
- Workers should report changed files clearly
- The data contract must be agreed before UI work depends on it
- UI workers should stub against the contract rather than inventing new data
  shapes midstream

## QA Checklist

Minimum acceptance checks:

- `/family` shows two mode choices clearly
- `Family Tree` is the primary featured mode
- Tree mode first shows only Joel plus helper copy
- Clicking Joel expands all 76 Gen 1 branches
- Gen 1 is actually ordered by surname A-Z
- Visible counts are total descendants
- Opening one branch preserves collapsed sibling context
- Co-advised note appears where expected
- Search can find people quickly
- `Network Map` does not load until selected
- Existing network view still works
- Mobile layout is usable
- Keyboard interaction works

## Deferred V2 Work

These ideas remain live, but should not block MVP shipment.

- full left-to-right pedigree chart
- dedicated `family/tree.html`
- D3-driven animated collapsible pedigree
- minimap
- richer subtree metrics
- more visual branch summaries

## Prompting Note

Future Claude Code prompts for this project should say:

- read `Planning/Family_Tree_Mode_Master_Plan.md` first
- treat it as the canonical implementation brief
- only then read the minimum additional files needed for your assigned task

This file should be updated whenever product decisions or scope change.
