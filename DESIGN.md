---
name: Condor Web UI
description: Dark admin canon for an HTCondor cluster companion — GitHub/Kubernetes Dashboard craft bar, cyan action accent, software-legible status
colors:
  primary: "#22d3ee"
  on-accent: "#08222a"
  ground: "#0b0f14"
  panel: "#10161d"
  card: "#121a22"
  card-hover: "#17202a"
  input-well: "#0d1218"
  log-sink: "#050a10"
  hairline: "rgba(148, 163, 208, 0.14)"
  hairline-hover: "rgba(148, 163, 208, 0.28)"
  row-hairline: "rgba(148, 163, 208, 0.09)"
  text-primary: "#e7edf3"
  text-secondary: "#9aa4b8"
  text-muted: "#828da6"
  status-idle: "#fbbf24"
  status-running: "#34d399"
  status-held: "#f87171"
  status-completed: "#60a5fa"
  status-transferring: "#c084fc"
  status-removed: "#6b7280"
typography:
  display:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1.55rem"
    fontWeight: 650
    letterSpacing: "-0.02em"
  title:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1rem"
    fontWeight: 650
    letterSpacing: "-0.01em"
  body:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.87rem"
    fontWeight: 400
  label:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.74rem"
    fontWeight: 650
    letterSpacing: "0.07em"
  mono:
    fontFamily: "ui-monospace, 'JetBrains Mono', 'Fira Code', 'SF Mono', monospace"
    fontWeight: 500
rounded:
  sm: "6px"
  md: "10px"
  lg: "12px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "20px"
  xl: "24px"
  section: "28px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-accent}"
    rounded: "8px"
    padding: "8px 15px"
    height: "34px"
  button-primary-hover:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-accent}"
  button-ghost:
    backgroundColor: "{colors.card}"
    textColor: "{colors.text-secondary}"
    rounded: "8px"
    padding: "8px 15px"
  button-danger:
    backgroundColor: "rgba(248, 113, 113, 0.14)"
    textColor: "{colors.status-held}"
    rounded: "8px"
    padding: "8px 15px"
  input-text:
    backgroundColor: "{colors.input-well}"
    textColor: "{colors.text-primary}"
    rounded: "8px"
    padding: "9px 12px"
  status-badge-running:
    backgroundColor: "rgba(52, 211, 153, 0.12)"
    textColor: "{colors.status-running}"
    rounded: "20px"
    padding: "3px 10px"
  stat-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "18px 20px"
  nav-link-active:
    backgroundColor: "rgba(34, 211, 238, 0.09)"
    textColor: "{colors.primary}"
    rounded: "8px"
    padding: "9px 14px"
---

# Design System: Condor Web UI

## Overview

**Creative North Star: "the category standard, executed impeccably"**

This is the dark admin-panel canon — sidebar shell, stat overview, dense grouped job table — the cluster tool researchers already know, played completely straight and finaled at the craft bar of GitHub (Actions/PRs) and Kubernetes Dashboard. There is no invented persona world and no ornament; the differentiator is craft: status and duration rendered software-legibly (status badges with live dots, exact `1h 42m` wall times, tabular numerals), panels that are calm, plain, and disciplined. It is deliberately simplistic — made-for-us precision for lab researchers on a shared HTCondor cluster, who glance in, act, and leave; density and muscle memory beat novelty.

Confirmed visual anti-references: the generic SaaS panel, terminal cosplay, and cyber/neon styling. No gradients, no glows, no theatrics. Depth comes from faint near-black shadows over blue-tinted tonal grounds, elevated flat panels ruled by 1px hairlines. HTCondor's own language (statuses, hold reasons, wall time) supplies all color drama; the interface itself stays quiet.

Dark is the design target and the only design system. A pre-existing light-theme variable override ships as a carried-over convenience surface (recorded exception in PRODUCT.md) — its values are swapped via `.light-theme` custom properties and receive no separate system guidance.

**Key Characteristics:**
- Near-black blue-tinted grounds (#0b0f14 → #17202a tonal ladder) with 1px white-blue hairlines
- One cyan action accent (#22d3ee); amber/green/red/blue/purple status color family confined to status surfaces
- System UI sans + true monospace; every number, ID, command, and duration is mono with `tabular-nums`
- Flat canon panels: hairline border + faint resting shadow, hover raises border/background only — never lift
- 14px root type, dense reading sizes (0.74–0.93rem), uppercase micro-labels with tracking
- 8px spacing rhythm, 6/10/12px radii, hairlines at three strengths (row 0.09, border 0.14, hover 0.28)
- Native checkboxes/radios tinted `accent-color: cyan`; global `:focus-visible` cyan ring; reduced-motion honored everywhere

## Colors

A near-black blue-tinted ground ladder carrying exactly one saturated action color; all remaining color is HTCondor status semantics, tinted at low alphas behind their own hue.

### Primary

- **Cyan Action Accent** (#22d3ee): The only interactive color in dark mode — primary buttons (`Submit Job`), job-ID links, active nav, selected toggle/filter states, checkboxes via `accent-color`, carets, focus rings, progress fills. On the accent itself, text runs near-black teal (#08222a; light theme flips to #ffffff). Its rarity is the point: on any screen the cyan paints actions and nothing else.

### Secondary

- **Amber Queued** (#fbbf24): Idle jobs — status badges, idle bar segments, warning rate (75%+) quota fills, hold-action hover.
- **Running Green** (#34d399): Running jobs and the schedd-connected health dot; also the healthy quota fill.
- **Held Red** (#f87171): Held/broken jobs and destructive action affordances (`Delete`, `Remove`, hover tints) — always as a 12–14% tint of itself behind its own border (25%).
- **Completed Blue** (#60a5fa): Completed jobs' badges, bar segments, and legend swatches. Plainly informational, never decorative.
- **Transferring Orchid** (#c084fc): Output-transfer state badges and segments only.
- **Removed Gray** (#6b7280): Removed jobs — the status family's muted terminus.

### Neutral

- **Near-Black Blue Ground** (#0b0f14): Page ground, `body`.
- **Slate Panel** (#10161d): Sidebar, sticky table header band, secondary raised chrome.
- **Blue-Slate Card** (#121a22): Cards, panels, ghost buttons at rest.
- **Slate Hover Card** (#17202a): Card and row hover surface.
- **Input Well** (#0d1218): Form fields, filter wells, bar tracks — one step darker than cards.
- **Abyssal Log Sink** (#050a10): Log/stdout panels, the darkest surface in the system.
- **Cool Blue Hairlines** (rgba(148, 163, 208, 0.14) / 0.28 hover / rgba(148, 163, 208, 0.09) rows): Periwinkle at low alpha, one pixel thick, in three strengths.
- **Soft Cloud White** (#e7edf3): Primary text and values.
- **Slate Lavender** (#9aa4b8): Secondary text, table headers, inactive states.
- **Faded Slate-Blue** (#828da6): Muted hints, timestamps, meta, disabled.

### Named Rules
**The One Voice Rule.** Cyan answers "can I act here?" — status color answers "what happened?" Each stays on its own side; semantic colors never decorate, and cyan never signals status.
**The Status Tint Rule.** A status color ships as a set: its hue for text/dot, its 12% tint for the fill, its 25% tint for the badge border. Never a raw swatch where a tinted pill belongs.
**The Hairline Rule.** Structure is drawn with 1px periwinkle-alpha lines, not by darkening surfaces: rows 0.09, panel borders 0.14, interactions 0.28.

## Typography

**Display Font:** system-ui stack (system-ui, -apple-system, 'Segoe UI', sans-serif) — no loaded webfont
**Body Font:** the same system stack, per the canon UI-family decision
**Label/Mono Font:** ui-monospace stack with JetBrains Mono preference (ui-monospace, 'JetBrains Mono', 'Fira Code', 'SF Mono', monospace)

**Character:** A browser-native system pairing that reads as software, not marketing: dense sans for labels and prose, true monospace wherever the cluster speaks — job IDs, command lines, wall time, quotas, log output — with `font-variant-numeric: tabular-nums` so numbers align down columns.

### Hierarchy
- **Display** (650 weight, 1.55rem at 14px root ≈ 22px, −0.02em tracking, balanced wrapping): One per page — the page-header h1 ("Jobs", "Submit Job").
- **Title** (650, 1rem ≈ 14px, −0.01em): Card headers, modal headers (1.1rem), section names.
- **Body** (400, 0.87rem ≈ 12px baseline reading size): Table cells, form inputs, toast copy, empty-state guidance.
- **Label** (650, 0.74–0.8rem, 0.07em→0.05em tracking, uppercase): Table headers (0.74rem/slate lavender), field labels, quota paths, usage tiles.
- **Meta** (500–600, 0.78–0.85rem): Status badge text (600), secondary labels, timestamps; never uppercase unless it is a structural label.
- **Mono** (500, 0.82–1.1rem, tabular numerals): `.job-id`, `.job-cmd`, `.job-host`, wall time, quota usage, progress text, code editor, log output. Stat values are sans (2rem/700/−0.03em), but every computed numeric detail is mono.

### Named Rules
**The Mono Truth Rule.** If it identifies or measures a job — ID, command, host, wall time, sizes, percentages, file counts — it renders in the mono family and `tabular-nums`. Sans numerals appear only in the stat-card headline counts.

## Layout

A fixed application shell: a 240px left sidebar (collapses to 60px; auto-converts to an icon rail below 900px) separated from a single main column by a hairline. The main column carries `margin-left: 240px`, a `max-width: 1560px` cap, and `28px 32px 40px` padding — content breathes at the top, runs dense in the tables. (Build note: the surface brief sketched 232px; the shipped system is 240px — the build's value is canon.)

Density is the spatial model: an 8px rhythm governs gaps (4/6/8/10/12px inside components, 8/12/14/16px between siblings, 20/24px between sections), while padding stays rectangular and compact — cards `18–20px`, card headers `15–16px 20px`, table cells `11–12px 16px`. The dashboard's first viewport is exactly the brief: page title row with schedd health dot and 30s refresh countdown, four auto-fit stat cards (grid, `minmax(200px, 1fr)`, 14px gap), then the grouped job table filling the remainder inside a scroll-owning container — `.table-container { max-height: calc(100vh - 300px) }` with `position: sticky` headers and a `0 1px 0` hairline shadow stamping the header band. Controls belong inline in the flow they govern: a filter bar in the page header, bulk actions in the table card's header strip, filter badges right-aligned in that strip. Below 768px, submit-form rows drop to a single column; at 480px, page padding tightens to 12px and the auto-refresh label drops.

## Elevation & Depth

A hybrid of faint resting shadow and tonal layering, at whisper volume. At rest, every panel — card, ghost button, input — carries the faintest near-black shadow (`0 1px 2px rgba(1, 4, 9, 0.35)`) over the hairline; depth steps mostly come from the tonal ladder itself (ground → panel → card → hover card). Shadows swell only as a state response, never as decoration, and nothing ever lifts or translates vertically: primary-button hover deepens to `0 3px 12px -2px` and drops back on active; tooltips and dropdowns take the mid shadow; modals and toasts take the large shadow (`0 12px 32px -8px rgba(1, 4, 9, 0.55)`) plus a `rgba(2, 6, 12, 0.72)` scrim with a 4px backdrop blur. Floating UI (sticky table header) separates by a 1px hairline shadow.

### Shadow Vocabulary
- **resting** (`0 1px 2px rgba(1, 4, 9, 0.35)`): Cards, inputs, buttons, stat and quota tiles — barely-there depth at rest.
- **raised** (`0 3px 12px -2px rgba(1, 4, 9, 0.45)`): Primary button hover, active tooltips, toggled segmented tab.
- **floating** (`0 12px 32px -8px rgba(1, 4, 9, 0.55)`): Modals, toasts — the only truly lifted surfaces.

### Named Rules
**The Flat Canon Rule.** Nothing lifts off the page. Shadows are near-black, faint at rest, and respond to state by swelling in place — hover, focus, or entrance — never by `translateY` elevation.

## Shapes

The form language is compact rounded rectangles over hairlines, tuned per hierarchy: micro-controls (action buttons, checkboxes tiles, tooltips, group rows) at 6px, fields and buttons at 8px, cards and modals at 10px and 12px, status badges as full pills (20px), progress/track bars as thin 3–4px rails. Borders are always the 1px white-blue hairline (see Colors), with the danger set drawing its own 25%-tinted border. Two authored exceptions to the rectangle: dashed state — the empty/form dropzone draws a 2px dashed hairline border and answers dragover/hover with a cyan border on a 4% cyan wash; and drawn chevrons — collapsible-card arrows are `clip-path` geometry, group expanders are 2px-stroke SVG chevrons, and both rotate in 0.2s — never typed glyphs. Table headers keep square silhouette; overflow cells always ellipsize (`max-width` + `text-overflow`), never wrap mid-row.

## Components

### Buttons
- **Shape:** compact rounded rectangles (8px radius; 6px for 30px icon action buttons)
- **Primary:** cyan action accent (#22d3ee) fill with near-black teal text (#08222a), `8px 15px` padding, 600 weight, resting shadow; hover brightens 6% and raises the shadow, active darkens 3%
- **Ghost:** blue-slate card fill, secondary text, hairline border; hover lifts text to primary white, border to 0.28, background to hover card
- **Danger:** held-red 14% tint with held-red text and 25% red border — reserved for queue-mutating actions (`Delete`, `Remove`); hover deepens the tint to 24%, never fills solid red
- **Disabled:** 45–55% opacity, `not-allowed` cursor
- **Small / Large:** `5px 10px` at 0.8rem and `12px 24px` at 0.95rem variants
- **Focus:** global 2px cyan `:focus-visible` outline, offset 2px

### Chips
- **Status Badge:** 20px pill, 5px inner dot (`::before`), the semantic-set treatment (hue text on 12% tint, 25% border); running and transferring dots pulse (2s / 1.5s); 0.78rem/600 text
- **Filter Badge:** same pill silhouette in the cyan voice (12% fill, cyan text) with a 16px circular clear button that deepens its tint on hover
- **Toggle / Segmented Tabs:** `card-tabs` and `mode-toggle` are hairline-cornered wells; the active segment turns cyan-tinted (12%, 10% in light) or takes the card surface with a mid shadow

### Cards / Containers
- **Corner Style:** 10px radius (12px modals), hairline border, resting shadow
- **Background:** blue-slate card (#121a22); hover moves background + border, never shadow
- **Shadow Strategy:** faint resting whisper, per Elevation
- **Border:** 1px `rgba(148, 163, 208, 0.14)`; card headers close with a 1px bottom hairline
- **Internal Padding:** 18–20px; headers `15–16px 20px`
- **Collapsible:** native `details`/`summary` with the drawn clip-path chevron and a 0.2s fade-in opening

### Inputs / Fields
- **Style:** input-well fill (#0d1218 — darkest surface above the log sink), 1px hairline, 8px radius, `9px 12px` padding, 0.88rem sans
- **Focus:** cyan border + `0 0 0 3px rgba(34, 211, 238, 0.14)` ring, background rises to card; caret is cyan
- **Select:** custom 12×8 periwinkle chevron (inline SVG data-URI), 32px right padding, options restyled to the panel palette
- **Textarea / Code:** mono family at 0.85rem, line-height 1.5–1.6; the raw editor pairs a synced line-number gutter sharing the same well fill
- **Error / Disabled:** destructive intent is action-colored, not field-red; disabled runs 55% opacity

### Navigation
- Fixed 240px sidebar on the slate panel ground, hairline right border; three collapsible uppercase section titles (0.7rem/700, 0.08em tracking) with inline SVG chevrons; links at 0.93rem/500 with 18px inline SVG stroke icons. Hover: 8% periwinkle wash. **Active:** cyan text + icon on a 9% cyan wash with a 3px cyan rail bar (radius 2px) flush to the sidebar edge — the only left rail in the system, and it marks state, not decoration. Sidebar footer carries the connection health dot (green on connect with a 3px green halo ring, red otherwise). Below 900px the rail shows icons only.
- **Brand:** 30px cyan tile with a five-node wing constellation — a faint flight path through a cluster — followed by `Condor` + muted `UI`; the whole lockup links home and the same tile ships as the SVG favicon. It is not a control surface for theme or collapse.
- **Utilities:** the theme toggle lives in the sidebar footer, inline with the connection health dot when expanded (sun/moon icon + current-mode label); collapsed, it becomes an icon-only 32px target with the action in `title`/`aria-label`.
- **Collapse:** a persistent 32px bordered chevron button. Expanded, it sits at the header's right edge; in the 60px rail it stacks below the brand. It is never hidden or absolutely layered over the brand.

### Signature: Grouped Status Bar
The dashboard's main instrument: each cluster row owns a stacked 8px segmented bar (2px segment gaps on a 1px input-well track) whose widths are the cluster's status distribution — clickable segments link to the filtered view, each with an exact `count label (pct%)` tooltip; single-job rows show a plain status badge instead. No sparklines, no tiles — the distribution is the data.

### Signature: Number-First Stat Card
Flat canon panel: the count **is** the card — 2rem/700/−0.03em tabular value over an 0.8rem/500 slate label, optional 42px tinted icon tile (state color on its 10% tint). No top strip, no hover lift; hover only raises border + background.

### Native Control Reality
Table select-all, group, and row checkboxes are native `input[type="checkbox"]` rendered with `accent-color: var(--accent-cyan)` (radios too) — the browser-blue default is *not* retained anywhere; native controls are recolored to the system accent, and native focus-visible receives the cyan ring.

## Do's and Don'ts

### Do:
- **Do** spend cyan only on affordances: `Submit Job`, job-ID links, active nav, focus rings, selection checkboxes, caret, progress fills.
- **Do** render every job identifier, command, wall time, and size in the mono family with `font-variant-numeric: tabular-nums`.
- **Do** build with the hairline triad — rows at `rgba(148, 163, 208, 0.09)`, borders at 0.14, interactions at 0.28 — before reaching for any other device.
- **Do** wrap status color in its three-part set (hue text, 12% tint fill, 25% border) inside a 20px pill with a 5px dot.
- **Do** keep the global reduced-motion kill switch, the cyan `:focus-visible` ring, and `accent-color` on native controls in any new surface.
- **Do** sit added UI on the tonal ladder (`--bg-secondary` → `--bg-input`) and answer hover with border + background only.

### Don't:
- **Don't** use gradients, text glows, neon/cyber color, or any shadow beyond the three-value near-black vocabulary.
- **Don't** add ornamental costume to panels — no top stripes, no side stripes on cards, no hover lift; the number is the card's job.
- **Don't** introduce eyebrows or kickers above headings; uppercase+tracking is reserved for structural labels (table headers, field labels, section titles).
- **Don't** ship an emoji or typed glyph where an inline SVG stroke icon belongs.
- **Don't** let status colors decorate non-status UI or cyan answer "what happened?" — each color has one question it may answer.
- **Don't** grow the light theme: it stays a carried variable-override convenience surface; dark is the design target and the only documented system.
- **Don't** invent a second accent, a display webfont, or custom easing outside the shipped motion constants (`--transition` 0.15s cubic-bezier(0.25, 0, 0.3, 1); entrance 0.25s cubic-bezier(0.16, 1, 0.3, 1) fade-up).
