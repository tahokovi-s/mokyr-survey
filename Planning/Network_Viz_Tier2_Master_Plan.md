# Network Visualization — Tier 2 Master Plan

Version date: 2026-04-17
Status: approved, ready for implementation
Primary surface: `Code/Network/viz_network.py`

## Prerequisites

- Read `Planning/Network_Viz_Design_System_Reference.md` first.
- `Planning/Network_Viz_Tier1_Master_Plan.md` must be complete: cream background, graphite palette, wordmark header, and white-card panels are all present. Confirm by loading the current `mokyr-legacy-site/network/mokyr-genealogy.html` and spot-checking.
- Do not load `Planning/Network_Viz_Tier3_Master_Plan.md`.

## Purpose

Replace the viz's ad-hoc control chrome, legend card, link dash pattern, and person-panel layout with the site's pathway-card, pill, and hairline idioms so the interactive surfaces feel native to the rest of the site.

## Locked Product Decisions

- Control bar is a single inline row. No gear icon, no popover, no modal.
- Legend is a hairline strip below the header, not a card.
- Medium-confidence (`.link.q12a`) edges differ from high-confidence edges only by opacity — no dash pattern. The functional distinction survives.
- Person panel is a white pathway-card, not a glass panel.
- Search input stays; toggles become `.privacy-pill` chips.

## Scope

5. **Inline control bar.** Remove `#settings-trigger` and `#settings-panel` from the HTML template and their CSS from L209–413. Put the search input (left) and three toggle chips (right) directly in a row beneath the wordmark header added in Tier 1. Toggles:
   - "Mokyr-direct only" (was `#showMokyrDirect`)
   - "Labels" (was `#showLabels`)
   - "Medium-confidence" (was `#showMedium`)
   Chip chrome: `.privacy-pill` idiom per `Planning/Network_Viz_Design_System_Reference.md` § Site Idioms to Reuse. Active-state chip uses `var(--accent)` border and deeper text color. Preserve existing event handlers — only markup and chrome change.
6. **Legend as hairline strip.** Replace `#legend` card at ~L469 with a row of dot + label pairs separated by middots, sitting on top + bottom `1px solid var(--line)` rules. Idiom: `.home-stat-strip` per reference doc. Five items in order: Joel, Gen 1, Gen 2, Gen 3, Gen 4+.
7. **Link styling.** In the CSS block (L209–413), unify `.link`:
   - Default: `stroke: rgba(16, 18, 22, 0.12); stroke-width: 1;`
   - Highlighted: `stroke: rgba(214, 188, 123, 0.55); stroke-width: 1.5;`
   - `.link.q12a`: remove `stroke-dasharray: 4 3`; replace with `stroke-opacity: 0.06`.
8. **Person panel as pathway-card.** Port `.pathway-card` chrome per reference doc. Structure:
   - Eyebrow: uppercase "Person Details" in `var(--muted)`.
   - Title: Iowan serif H3, `#101216`, 24px.
   - Subtitle: body stack, 13px, `var(--muted)`.
   - Detail grid items become small hairline chips — `1px solid var(--line)`, `var(--radius-md)` radius, 11px uppercase label in `var(--muted)`, 14px value in `#101216`. No dark glass anywhere.
   - Tooltip gets a matching miniature version: white, hairline border, `var(--card-shadow)`, 13px body, `var(--radius-md)` radius.

## Non-Goals

- Editorial frame above the canvas → Tier 3.
- Concentric layout → Tier 3.
- Motion-token audit → Tier 3.
- Rewriting the data model, link semantics, or generation assignment.

## Working Files

- `Code/Network/viz_network.py`
  - CSS block: **L209–413** (add `.privacy-pill`, `.legend-strip`, `.pathway-card` variants and the new link styles).
  - Controls markup currently at **L216–231**: rewrite as an inline row in the header.
  - Legend markup at **~L469**.
  - Person-panel markup at **~L247–260**.
  - Tooltip markup at **~L262**.
  - Event handlers for search and toggles (preserve; only chrome changes).
- Donor stylesheet (read-only reference): `mokyr-legacy-site/assets/styles.css` — `.privacy-pill` at L258–297, `.home-stat-strip` at L531–549, `.pathway-card` at L575–596.

## Implementation Phases

- **Phase 5** — Flatten controls into an inline row. Remove the gear button and popover; ensure all three toggles and the search input are always visible.
- **Phase 6** — Rebuild legend as a hairline strip; drop the card background.
- **Phase 7** — Unify link stroke styles; remove the dashed medium-confidence style.
- **Phase 8** — Port pathway-card idiom into the person panel; restyle tooltip to match.

## Completion Criteria

- No gear icon exists anywhere on the page. Search box and three pill toggles are visible on first load without any clicks.
- Legend sits on a single hairline strip — no card background, no drop shadow.
- Medium-confidence edges are visually distinguishable from high-confidence edges only by being fainter — no dashes.
- Opening any person shows a white pathway-card with Iowan title and hairline detail chips. Tooltip is a matching miniature white card.
- All § Non-Negotiables of the reference doc pass. Mobile breakpoint at 900px still collapses the person card to the bottom.
- Deployed copy: new HTML has been copied to `mokyr-legacy-site/network/mokyr-genealogy.html`. Playwright before/after pair saved at both breakpoints.

## Deferred

All Tier 3 scope.

## Recommended Prompt Preamble

> Load `Planning/Network_Viz_Tier2_Master_Plan.md` and `Planning/Network_Viz_Design_System_Reference.md`. Confirm Tier 1 changes are present (cream bg, graphite palette, wordmark header, white-card panels) before starting. Do not reopen Tier 1 decisions and do not load Tier 3. Edits land in `Code/Network/viz_network.py`. Regenerate, copy to `mokyr-legacy-site/network/mokyr-genealogy.html`, Playwright before/after at both breakpoints.
