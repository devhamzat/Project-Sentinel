# Sentinel "Watchtower" Design System

A design language for Project Sentinel, inspired by the *judgment* behind
Perplexity's UI — not its values. Adaptation level: **Moderate**. Source
material was read as research (computed-style frequency analysis + two
screenshots) and no CSS, markup, or assets were copied.

The tokens live in `src/styles.css` under `:root[data-theme="watchtower"]`
and are the source of truth. Watchtower is the default theme; Light, Dark,
and Mono remain selectable in Settings → Appearance.

## Color

| Token | Value | Role |
|---|---|---|
| `--bg` | `#161513` | Warm graphite page background |
| `--surface` | `#1d1b18` | Cards, inputs, list containers |
| `--surface2` | `#26231e` | Hover states, nested chrome |
| `--sidebar` | `#1a1815` | Sidebar panel |
| `--ink` | `#e7e2d9` | Primary text — warm parchment, not pure white |
| `--ink2` | `#c9c2b4` | Body/secondary text |
| `--soft` / `--softer` | `#98917f` / `#6e6759` | Muted labels, hints |
| `--line` / `--line2` | parchment at 10% / 18% | Hairline borders |
| `--accent` | `#e2a33b` | **Signal amber** — active nav, data values, send, focus |
| `--accent-h` | `#f0b95c` | Amber hover |
| `--accent-ink` | `#1b1408` | Text on amber fills (dark, for contrast) |
| `--ok` | `#8fbf72` | Muted moss green |
| `--error` | `#e06c5a` | Clay red |

**What changed from the source and why.** Perplexity keys everything to a
single teal on warm near-black. Watchtower keeps the *role structure* —
one warm dark neutral ramp built from a single ink color at opacity steps,
plus exactly one accent — but moves the accent to amber and the ink to
parchment. Amber is rationed: it marks "live signal" (active states,
graph counts, primary actions), never decoration. That rationing, plus
the warm parchment ink, is what keeps this from being the generic
"black + neon accent" template.

## Typography

| Token / face | Usage |
|---|---|
| `--font-display` → **Space Grotesk** (500–700) | Page titles, brand, stat values, section titles |
| Inter (400–600) | Body, UI labels |
| JetBrains Mono | Data labels, keys, kickers, counts |

**Changed:** Perplexity uses one custom sans at unusually light weights
(330/420) for a calm, editorial feel. Rather than imitating the light-weight
trick, Watchtower gets its calm from color restraint and puts character in
a technical display face (Space Grotesk) over a neutral body (Inter),
keeping JetBrains Mono for data — which was already part of Sentinel's
identity.

## Spacing, shape, elevation

- **Rhythm:** 8px-based like the source (an 8px grid is common property),
  but page padding is more generous relative to component density — airier
  than Sentinel was, denser than Perplexity.
- **Radii:** `--radius: 6px`, `--radius-lg: 10px` — deliberately crisper
  than both the source (6/8/12 + pills) and the old Sentinel (8/12). Pills
  are dropped except status badges.
- **Elevation:** shadows are `none` in Watchtower. Hierarchy comes from
  hairline opacity borders and surface steps — the one piece of source
  judgment adopted most directly, executed with different values.
- **Focus:** every focusable surface uses `--ring` (amber at 16%).

## Signature element

**Constellation texture** — a faint tiling SVG of node-and-edge dots (one
amber node per tile) behind the Dashboard and the Ask empty state, applied
via the `.constellation` class, watchtower theme only. It echoes the
knowledge graph itself; no equivalent exists in the source.

## Composition notes

- Sidebar information architecture is Sentinel's own, minus the Search tab
  (merged into Ask). The active nav item carries a 2px amber indicator bar.
- The content column is capped at 1120px and centered, so wide screens get
  a focused reading column rather than full-bleed sprawl.
- The Ask page borrows one composition judgment: when the chat is empty,
  an oversized centered input is the hero (`.ask-hero`) with a mono kicker,
  a Space Grotesk headline, and three clickable suggested queries — a
  different construction from the source's pill-toolbar input card.
- The chat input has an Ask/Search mode dropdown (`.mode-select`) — a
  drop-up menu with icon, label, and description per mode. Search results
  render as passage cards (`.passage`) inside the conversation.
- **Micro-label system:** every small uppercase label (section labels, card
  titles, stat labels, nav section headers, pipeline labels) is set in
  JetBrains Mono at reduced size — the "instrument panel" register that
  separates chrome from content across the whole app.
- The constellation texture appears on Dashboard, Ingest, and the Ask
  empty state (watchtower theme only).

## Legal note

This is design adaptation, not legal clearance. Sentinel is functionally
adjacent to Perplexity; if this ever ships commercially, trade-dress
questions are for a lawyer, not a style guide.
