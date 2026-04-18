# Network Visualization — Tier 3 Master Plan

Version date: 2026-04-17
Status: approved, ready for implementation
Primary surface: `Code/Network/viz_network.py`

## Prerequisites

- Read `Planning/Network_Viz_Design_System_Reference.md` first.
- `Planning/Network_Viz_Tier1_Master_Plan.md` must be complete.
- `Planning/Network_Viz_Tier2_Master_Plan.md` is strongly recommended but not strictly required. If Tier 2 is not yet landed, coordinate with the active Tier 2 builder to avoid markup collisions in `Code/Network/viz_network.py`.

## Purpose

Reshape the viz from "dashboard with a graph" into "editorial page with a lineage diagram." Add an introductory frame above the canvas, switch the default layout from free force-directed to concentric (Joel at center, generation rings outward), and sweep transitions for site motion tokens.

## Locked Product Decisions

- Editorial frame is always shown — eyebrow + Iowan H1 + one-line lead — above the interactive canvas. Mirrors the `/shape/` hero rhythm (see `mokyr-legacy-site/shape/index.html` L73–82).
- Concentric layout is the **default** on first load.
- Force-directed layout is kept as a **secondary** mode via a toggle in the control bar.
- Joel (`JM-ROOT`) sits at the visual center of the concentric view.
- Single-view page. No scrollytelling, no multiple sections, no alternative roots — those are explicit non-goals.

## Scope

9. **Editorial frame.** In the HTML template above `<svg id="graph">` (around L464), insert a `.viz-intro` block:
   - `.eyebrow` text: "The Network".
   - Iowan H1: draft wording "Four generations, charted." (final wording confirmed by the project owner before shipping).
   - One-line lead: draft wording "388 scholars, traced through Joel's advising lineage." (final wording pending owner confirmation).
   - SVG height becomes `calc(100vh - header-height - intro-height - footer-height)`.
10. **Concentric / radial layout.** Add a D3 radial force to the simulation setup:
    - Per-node: `forceRadial(ringRadius(d.generation), cx, cy)`.
    - Retain collision force tuned for the new layout.
    - Ring radii scale by generation population:
      - Gen 0: `r = 0`.
      - Gen 1, 2, 3, 4: increasing radii with enough inter-ring gap that rings remain visually distinct.
    - Label density policy: with ~77 Gen 1 / ~186 Gen 2 nodes per ring, permanent labels on crowded rings will overlap. Default behavior: show labels only for Gen 0 (Joel) and the currently-hovered-or-selected node plus its direct neighbors; the global "Labels" toggle (from Tier 1/2) when ON shows all labels (accepting overlap as a user choice). Alternative acceptable solution: fade labels by ring density — fully opaque on Gen 0, progressively faded on Gens 2–4 when crowding exceeds a threshold.
    - Layout toggle: a new pill chip. If Tier 2 is landed, add the chip to the inline control row. If Tier 2 is not landed, add the chip to the existing settings popover (already re-skinned as a white card by Tier 1). States: "Concentric" (default) and "Force" (legacy).
    - Toggling must not reload the page; it re-seeds the D3 force and re-runs the simulation.
11. **Motion tokens.** Audit every transition in the CSS block at L209–413:
    - Hover / opacity / highlight fade → `200–240ms cubic-bezier(0.22, 1, 0.36, 1)`.
    - Person-panel open and card lift → `240ms cubic-bezier(0.16, 1, 0.3, 1)`.
    - Remove any `transition: all`; name properties explicitly.
    - Remove abrupt state changes (no 0ms swaps).

## Non-Goals

- Narrative scrollytelling (Tier 3 keeps single-view).
- Alternative roots (browsing from a non-Joel node).
- Layouts beyond concentric and force (no tidy tree, no Sankey, no hierarchical edge bundling).
- Changes to what metadata appears in the person panel.
- Changes to data ingestion, link semantics, or generation assignment.

## Working Files

- `Code/Network/viz_network.py`
  - CSS additions: **L209–413**.
  - New intro block markup: insert around **L440–470**.
  - D3 simulation setup: ~**L580–660**. Layout toggle state + handler: ~**L700–780**.
- Reference for editorial idiom: `mokyr-legacy-site/shape/index.html` hero at L73–82.

## Implementation Phases

- **Phase 9** — Insert editorial frame; resize SVG accordingly. Confirm scrollless layout still works on 390×844 mobile.
- **Phase 10** — Implement concentric layout with radial force + ring radii. Tune radii at 1440×900 and 390×844 breakpoints until no labels collide at default zoom. Add the layout toggle chip.
- **Phase 11** — Sweep all CSS transitions for token compliance; remove abrupt state jumps.

## Completion Criteria

- First-load view: Joel at center, all four generation rings visually distinct at default zoom on 1440×900; on 390×844 all four rings are legible without clipping (zooming allowed for mobile).
- Label density policy is in place. With the "Labels" toggle OFF, only Gen 0 plus the currently-hovered-or-selected node (and its direct neighbors) show labels. With the toggle ON, all labels render (overlap accepted as a user-driven choice).
- Toggle to "Force" re-seeds the simulation and returns to the legacy layout without refreshing the page; toggling back to "Concentric" returns without refresh.
- Hover and selection transitions feel consistent with `/shape/` page hover motion on visual inspection.
- Editorial frame scrolls with the page; SVG canvas uses remaining viewport height with no internal scrollbar.
- All § Non-Negotiables of the reference doc pass.
- Deployed copy: new HTML has been copied to `mokyr-legacy-site/network/mokyr-genealogy.html`. Playwright before/after pair saved at both breakpoints.

## Deferred / Explicit Non-Goals

- Scrollytelling narrative arc (like `/shape/`).
- Any alternate root.
- A third layout option.

## Recommended Prompt Preamble

> Load `Planning/Network_Viz_Tier3_Master_Plan.md` and `Planning/Network_Viz_Design_System_Reference.md`. Tier 1 must be complete. Budget time for ring-radius tuning at 1440×900 and 390×844. Do not undo Tier 1/2 decisions, do not add layouts beyond concentric + force, and do not introduce scrollytelling. Edits land in `Code/Network/viz_network.py`. Regenerate, copy to `mokyr-legacy-site/network/mokyr-genealogy.html`, and capture Playwright screenshots at both breakpoints.
