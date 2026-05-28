# Network Visualization — Design System Reference

Version date: 2026-04-17
Status: approved, ready for implementation
Primary surface: `Code/Network/viz_network.py`

## Purpose

Shared bedrock for all network-visualization redesign work. Any builder agent starting any tier of the redesign (Tier 1, Tier 2, or Tier 3) reads this file first. Each tier plan (`Network_Viz_Tier1_Master_Plan.md`, `Network_Viz_Tier2_Master_Plan.md`, `Network_Viz_Tier3_Master_Plan.md`) references this document by section heading rather than duplicating its content — the goal is to keep per-task token load low when only one tier is active.

## Source of Truth & Deploy Flow

- Canonical file: `Code/Network/viz_network.py` (995 lines).
- All CSS is inlined in a Python string template: `<style>` at **L209**, `</style>` at **L413**.
- Generation palette constant at **L531–538** (`const GEN_COLOR = { ... };`).
- Output path logic at **L955**: `Output/mokyr-genealogy-{date}.html`.
- Build:
  ```
  python3 Code/Network/viz_network.py --date MMDDYY
  ```
- Deploy (manual, per `mokyr-legacy-site/README.md` L35–40):
  1. Run the build above.
  2. Copy `Output/mokyr-genealogy-MMDDYY.html` → `mokyr-legacy-site/network/mokyr-genealogy.html`.
- There is **no automation** for step 2. Builder agents must do it explicitly at the end of every tier.

## Site Design Tokens

Lifted from `mokyr-legacy-site/assets/styles.css` L1–31 (`:root` block plus the `body.page-section` light-theme remap). Port these into the viz's inline `<style>` at the top of the block.

| Token | Value |
|---|---|
| `--bg` | `#fbfbf8` |
| `--text` | `#101216` |
| `--muted` | `rgba(16, 18, 22, 0.64)` |
| `--soft` | `rgba(16, 18, 22, 0.44)` |
| `--line` | `rgba(16, 18, 22, 0.08)` |
| `--line-strong` | `rgba(16, 18, 22, 0.15)` |
| `--accent` | `#d6bc7b` |
| `--accent-deep` | `#9b7f42` |
| `--card-shadow` | `0 16px 40px rgba(16, 18, 22, 0.06)` |
| `--radius-xl` | `32px` |
| `--radius-lg` | `22px` |
| `--radius-md` | `16px` |

## Typography Stack

- Display (headings, stat numbers): `"Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif` — weight 400.
- Body: `"Neue Haas Grotesk Text Pro", "Avenir Next", "Helvetica Neue", sans-serif`.
- Eyebrow: body stack, `0.76–0.82rem`, UPPERCASE, letter-spacing `0.14em–0.22em`, color `rgba(16, 18, 22, 0.46)`.
- Node labels in SVG: body stack, 11px, fill `#101216`, `paint-order: stroke; stroke: #fbfbf8; stroke-width: 3px;` (cream halo).

## Palette Swap

| Role | Current | New |
|---|---|---|
| Page background | `#1a1a2e` | `var(--bg)` (`#fbfbf8`) |
| Body text / node labels | `#eee` / `#ddd` | `var(--text)` (`#101216`) |
| Label stroke halo | `#1a1a2e` | `#fbfbf8` |
| Link default | `#888` @ 0.45α | `rgba(16, 18, 22, 0.12)` |
| Link highlighted | white | `rgba(214, 188, 123, 0.55)` |
| Gen 0 (Joel) | `#f5c518` | `#d6bc7b` (site accent) |
| Gen 1 | `#4a9eff` | `#1f242d` (graphite 1) |
| Gen 2 | `#50c878` | `#4a5161` (graphite 2) |
| Gen 3 | `#ff8c42` | `#8a92a3` (graphite 3) |
| Gen 4+ | `#aaa` | `#c9ced8` (graphite 4) |
| Panel / tooltip bg | `rgba(8, 12, 28, 0.9)` + blur | `#ffffff` + `1px solid var(--line)` + `var(--card-shadow)` |
| Selection indicator | white drop-shadow | `outline: 3px solid rgba(214, 188, 123, 0.6)` |

Rationale: saturated rainbow palettes read "dashboard." A graphite ramp with a single accent reads "editorial" and matches the rest of the site.

## Site Idioms to Reuse

Port these class idioms into the viz's inline `<style>`. Class names are preserved to keep mental-model parity with the rest of the site.

- `.pathway-card` — white bg, `1px solid var(--line)`, `var(--radius-xl)` radius, `38px` padding, `var(--card-shadow)`, lift on hover. Source: `mokyr-legacy-site/assets/styles.css` L575–596.
- `.privacy-pill` / `.back-link` — `999px` radius, `11px 16px` padding, white-ish bg with hairline border. Source: `styles.css` L258–297.
- `.home-stat-strip` — hairline row idiom: top + bottom `1px solid var(--line)` rules with in-row dividers. Source: `styles.css` L531–549.
- `.background-wash` + `.background-grid` — subtle radial + 64px grid overlay on light pages. Source: `styles.css` L127–143.
- `.eyebrow` — 0.82rem uppercase, muted or accent color. Source: `styles.css` L318–335.

## Motion Tokens

- Hover / opacity / highlight fade: `200–240ms cubic-bezier(0.22, 1, 0.36, 1)`.
- Card lift (person panel open, pathway-card hover): `240ms cubic-bezier(0.16, 1, 0.3, 1)`.
- No `transition: all`. Name properties explicitly.

## Verification Harness

- Playwright infrastructure exists at `Output/playwright/`.
- Baseline screenshot: `Output/mokyr-genealogy-040126-screenshot.png`.
- Before/after protocol after every tier:
  1. Regenerate: `python3 Code/Network/viz_network.py --date 041726`.
  2. Capture headless screenshots at 1440×900 and 390×844.
  3. Full-page + zoomed-to-canvas variants.

## Non-Negotiables

No tier is complete if any of the following regress vs. the pre-redesign deployed copy of `mokyr-legacy-site/network/mokyr-genealogy.html` captured at the start of the tier:

- Node count and edge count shown in the `#stats` widget are unchanged (as a baseline cross-check: the 040126 dataset has 387 nodes and 508 edges in `Data/Derived/Network_Nodes_040126.csv` / `Network_Edges_040126.csv` — the rendered count may be smaller if the JM-ROOT closure filter omits disconnected nodes; whatever the pre-redesign HTML renders is the baseline for that tier).
- Search-by-name still filters visible nodes.
- Person panel opens on node click; the Clear button closes it.
- Keyboard accessibility: Tab + Enter reach every interactive element.
- Mobile breakpoint at 900px still collapses the person panel to the bottom.
- High-confidence vs. medium-confidence edge distinction survives. The visual treatment changes in Tier 2, but the functional distinction must remain.

## Cross-References

- Tier 1 — `Planning/Network_Viz_Tier1_Master_Plan.md`.
- Tier 2 — `Planning/Network_Viz_Tier2_Master_Plan.md`.
- Tier 3 — `Planning/Network_Viz_Tier3_Master_Plan.md`.
- Donor stylesheet — `mokyr-legacy-site/assets/styles.css`.
- Editorial idiom reference — `mokyr-legacy-site/shape/index.html`, `mokyr-legacy-site/family/index.html`, `mokyr-legacy-site/index.html`.
- Deploy procedure — `mokyr-legacy-site/README.md` L35–40.
