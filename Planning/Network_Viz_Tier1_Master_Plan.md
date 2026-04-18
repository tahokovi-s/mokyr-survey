# Network Visualization — Tier 1 Master Plan

Version date: 2026-04-17
Status: approved, ready for implementation
Primary surface: `Code/Network/viz_network.py`

## Prerequisites

Read `Planning/Network_Viz_Design_System_Reference.md` first. Do not load `Planning/Network_Viz_Tier2_Master_Plan.md` or `Planning/Network_Viz_Tier3_Master_Plan.md`.

## Purpose

Port the viz's visual chrome to the site's light editorial system so the network page reads as part of the site rather than a standalone tool. Zero layout, interaction, or control-structure changes — those belong to Tier 2 and Tier 3.

## Locked Product Decisions

- Light mode only. No dark-mode toggle.
- Single-accent palette. `var(--accent)` (gold) is reserved for Gen 0 (Joel) and the selection focus ring. Every other generation uses a step of the graphite ramp defined in `Network_Viz_Design_System_Reference.md` § Palette Swap.
- Viz page is wrapped in the shared site header (wordmark + back-link) and footer credit line, matching `mokyr-legacy-site/shape/index.html` and `mokyr-legacy-site/family/index.html`.
- CSS stays inlined in the Python template — no split to `mokyr-legacy-site/assets/styles.css`. Site tokens and class idioms are copied into the inline `<style>`.

## Scope (four atomic changes)

1. **Token substitution** in the CSS block at `Code/Network/viz_network.py` **L209–413**. Introduce a `:root { ... }` custom-property block at the top of the style tag holding every token listed in the reference doc § Site Design Tokens. Replace every hardcoded `#1a1a2e`, `#eee`, `#ddd`, `#888`, `#aaa`, and `rgba(8, 12, 28, ...)` with the appropriate token.
2. **Palette collapse** at `Code/Network/viz_network.py` **L531–538**. Rewrite `GEN_COLOR` per reference doc § Palette Swap. Update the inline legend markup (`<div id="legend">` at ~L469) so dot colors match.
3. **Shared chrome** at the top and bottom of the HTML template around `<svg id="graph">` (L464):
   - Header row: `.wordmark` link ("M" avatar + "Joel Mokyr" + "An 80th Birthday Celebration") plus `.back-link` ("Back to welcome", `href="../"`). Structure mirrors `mokyr-legacy-site/shape/index.html` L20–29.
   - Footer: `.footer-credit` matching `mokyr-legacy-site/index.html` L85–87.
   - Adjust SVG height to `calc(100vh - header-height - footer-height)` so the canvas fills the remaining viewport.
4. **Panel / tooltip re-skin** for `#tooltip`, `#person-panel`, and `#settings-panel`. All three become white-card:
   - `background: #ffffff`
   - `border: 1px solid var(--line)`
   - `border-radius: var(--radius-lg)`
   - `box-shadow: var(--card-shadow)`
   - Remove `backdrop-filter: blur(...)` and all `rgba(8, 12, 28, ...)` opacity backgrounds. No glass.

## Non-Goals (explicit — belong to later tiers)

- Flattening the gear popover into an inline pill row → Tier 2.
- Legend as hairline strip → Tier 2.
- Link stroke unification and q12a dash removal → Tier 2.
- Person panel structural port to `.pathway-card` (chip grid, Iowan title) → Tier 2.
- Editorial frame above the canvas → Tier 3.
- Concentric layout → Tier 3.
- Motion-token audit → Tier 3.

## Working Files

- `Code/Network/viz_network.py`
  - CSS block: **L209–413**.
  - HTML template body markup: ~**L415–620**.
  - `GEN_COLOR` constant: **L531–538**.
  - Legend markup: ~**L469**.
- Donor stylesheet (read-only reference): `mokyr-legacy-site/assets/styles.css`.

## Implementation Phases

- **Phase 1** — Add `:root` custom-property block at the top of the style tag; replace every hardcoded color in L209–413 with token references.
- **Phase 2** — Rewrite `GEN_COLOR` per § Palette Swap; update the inline legend dot colors to match.
- **Phase 3** — Insert the wordmark header and footer-credit markup; adjust SVG height; ensure the mobile person-panel breakpoint at 900px still places the panel correctly beneath the new header.
- **Phase 4** — Re-skin `#tooltip`, `#person-panel`, and `#settings-panel` chrome to white-card.

## Completion Criteria

- Regenerated `Output/mokyr-genealogy-041726.html` opens with cream background, graphite text, no saturated primaries.
- Legend shows graphite dots plus a single gold Joel dot.
- Wordmark header is visible at the top; "Back to welcome" navigates to `../`. Footer credit line is present at the bottom.
- Tooltip, person panel, and settings panel are all white cards — no glass.
- All § Non-Negotiables of the reference doc pass (node/edge counts, search, toggles, mobile breakpoint, keyboard accessibility).
- Deployed copy: `Output/mokyr-genealogy-041726.html` has been copied to `mokyr-legacy-site/network/mokyr-genealogy.html`.
- Playwright before/after pair saved for 1440×900 and 390×844.

## Deferred

All Tier 2 and Tier 3 scope.

## Recommended Prompt Preamble

> Load `Planning/Network_Viz_Tier1_Master_Plan.md` and `Planning/Network_Viz_Design_System_Reference.md`. Do not load Tier 2 or Tier 3. All edits land in `Code/Network/viz_network.py`. After editing, regenerate with `python3 Code/Network/viz_network.py --date 041726`, copy the resulting `Output/mokyr-genealogy-041726.html` to `mokyr-legacy-site/network/mokyr-genealogy.html`, and capture Playwright screenshots at 1440×900 and 390×844. Do not touch interaction logic, the settings popover, link stroke styles, or layout topology — those are Tier 2 / Tier 3.
