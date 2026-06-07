# LamaDB — Brand Spec

## Design System: cursor (adapted for dark terminal)
## Direction: Tech Utility (dark variant)

## Color Tokens

| Token | Value | OKLch | Usage |
|---|---|---|---|
| --bg | #0a0a0a | oklch(3% 0.002 280) | Page background |
| --surface | #111314 | oklch(5% 0.003 280) | Sidebar, card surfaces |
| --surface-2 | #181a1c | oklch(6% 0.005 280) | Hover, input backgrounds |
| --surface-3 | #1e2022 | oklch(8% 0.005 280) | Elevated surfaces, modals |
| --fg | #e4e5e8 | oklch(90% 0.005 280) | Primary text |
| --fg-2 | #b0b2b8 | oklch(72% 0.008 280) | Secondary text |
| --muted | #6b6e76 | oklch(48% 0.01 280) | Muted/placeholder text |
| --border | #242628 | oklch(14% 0.005 280) | Borders |
| --border-light | #2e3033 | oklch(18% 0.005 280) | Lighter borders |
| --accent | #00ff88 | oklch(70% 0.25 150) | Primary accent (terminal green) |
| --accent-cyan | #00d4ff | oklch(65% 0.18 220) | Secondary accent |
| --warn | #ffaa00 | oklch(75% 0.20 85) | Warning |
| --danger | #ff3333 | oklch(55% 0.25 30) | Critical/error |
| --info | #00bfff | oklch(62% 0.15 240) | Info |

## Typography

| Role | Font stack |
|---|---|
| Display / UI | -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', system-ui, sans-serif |
| Data / Mono | 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, monospace |

## Posture

- **Dark canvas** (#0a0a0a) with high contrast — this is a power-user terminal/hacker tool
- **Monospace data** in tables, stats, timestamps, code — JetBrains Mono everywhere data appears
- **Clean sans-serif** for headings, nav labels, buttons — Inter family
- **Accent green** (#00ff88) as primary signal — used sparingly for live/health indicators
- **Accent cyan** (#00d4ff) as secondary signal — info and secondary highlights
- **1px hairline borders** (#242628) — no shadows, no rounded corners on data tables
- **Dense information layout** — every pixel carries signal
- **Tabular numerics** with `font-variant-numeric: tabular-nums`
- **Color-coded severity dots**: green=info, yellow=warn, red=critical
