# Visual Design Research: Terminal-Inspired Neon Dashboard

**For:** LamaDB Life-OS dashboard (Alpine.js + vanilla CSS)
**Current state:** Existing palette uses `#00ff88` green / `#00d4ff` cyan on `#0a0a0a` with `--accent-dim`/`--accent-glow` tokens already wired. Research below extends and refines that system.

---

## 1. Color Schemes — Avoiding "Hacker Movie" Syndrome

The trap: pure `#00ff00` on black = 1995 Matrix / Mr. Robot aesthetic. Classy neon needs **restraint** — neon as accent, not as the default ink.

### Principles

- **70/20/10 rule.** ~70% neutral dark surface, ~20% secondary text/borders, ~10% neon accent. If neon is more than 15% of visible pixels, it stops feeling premium.
- **Desaturate slightly.** True `#00ff88` reads as "console terminal." Pulling toward `#3ee8a8` or `#4ade80` (Tailwind emerald-400) makes it feel "instrumented software" rather than "Hollywood hacker."
- **Lift the base black.** Pure `#000` makes neon explode visually. `#0a0a0a` → `#0f1115` (current `--bg` is good) lets accents breathe without glare.
- **Use HSL channels for variants.** Easier to keep hues coherent:
  ```
  --accent-h: 152;   /* hue */
  --accent-s: 100%;
  --accent-l: 50%;
  --accent: hsl(var(--accent-h) var(--accent-s) var(--accent-l));
  --accent-dim: hsl(var(--accent-h) var(--accent-s) var(--accent-l) / 0.12);
  --accent-glow: hsl(var(--accent-h) 100% 60% / 0.4);
  ```
  Then changing the theme is just `--accent-h: 280;` (cyan → magenta).

### Five preset directions

| Preset | Accent | Feel |
|--------|--------|------|
| **Phosphor** (current) | `#00ff88` emerald | Classic terminal, friendly |
| **Cyberdeck** | `#00d4ff` cyan + `#ff2a6d` magenta dual | Synthwave-but-restrained, Blade Runner not Hotline Miami |
| **Amber CRT** | `#ffaa00` amber on warm-black `#0e0c08` | Vintage mainframe, easy on eyes |
| **Vaporwave** | `#ff6ec7` pink + `#7df9ff` cyan dual | Nostalgic, high-energy |
| **Nord minimal** | `#88c0d0` muted cyan + `#a3be8c` muted green | Low-saturation, "calm professional," no glow at all |

Tradeoff: high-saturation neons pop but exhaust the eye; muted versions feel grown-up but lose the "Life-OS energy." Best UX answer is **a theme picker** — see §6.

---

## 2. Typography — Pairings for Terminal + Classy

### Recommended pairing (Google Fonts, all free)

| Role | Font | Why |
|------|------|-----|
| Display / UI | **Inter** (you already have it) | Neutral, excellent at small sizes, large weight range |
| Mono primary | **JetBrains Mono** (you already have it) | Designed for code editors, ligatures available |
| Mono alternative | **IBM Plex Mono** | Warmer humanist feel — good for narrative text in cards |
| Optional display | **Space Grotesk** | Slightly geometric, gives "tech product" not "terminal app" feel |

### Concrete font-stack upgrades

```css
:root {
  /* Display: Inter with proper fallback metrics */
  --font-display: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI Variable',
                  'Segoe UI', system-ui, sans-serif;
  /* Mono: JetBrains with tabular-nums for data alignment */
  --font-mono: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, 'SF Mono',
               Menlo, Consolas, monospace;
  /* Feature settings — tabular numbers for metrics, slashed zero */
  --font-features: 'cv11', 'ss01', 'tnum', 'zero';
}
body { font-feature-settings: var(--font-features); }
.metric, .stat-value, table { font-variant-numeric: tabular-nums; }
```

`tabular-nums` is **the single biggest typography win** for a dashboard — all your numbers line up cleanly.

### Hierarchy rules

- **H1/H2:** `font-weight: 600`, tight tracking (`letter-spacing: -0.01em`)
- **Section labels:** uppercase, `font-size: 11px`, `letter-spacing: 0.08em`, color `--muted`
- **Metrics:** mono, `font-weight: 600`, `font-size: 24-32px`
- **Body:** `font-weight: 400`, `line-height: 1.55`
- **Captions/timestamps:** mono, `font-size: 11px`, `--fg-2`

### Don't
- Don't use display fonts for body text. Inter is fine at 14px; Space Grotesk gets clunky below 16px.
- Don't mix more than 2 type families. Inter + JetBrains Mono is the sweet spot.

---

## 3. Neon Glow — Subtle Effects That Don't Burn

Glow is **expensive visual budget.** Each glow competes for attention. Use it for: (a) live data, (b) the active state of something, (c) hover affordances. Never for decoration alone.

### CSS techniques

**Text glow** — small shadow stack, low opacity, kept tight:
```css
.glow-text {
  color: var(--accent);
  text-shadow:
    0 0 4px var(--accent-glow),
    0 0 12px hsl(var(--accent-h) 100% 50% / 0.2);
}
/* Heavy emphasis — use sparingly */
.glow-text-strong {
  text-shadow:
    0 0 2px var(--accent),
    0 0 8px var(--accent-glow),
    0 0 20px hsl(var(--accent-h) 100% 50% / 0.3);
}
```

**Box glow / focus rings** — prefer outer shadows over inner for "screen glow":
```css
.glow-card {
  border: 1px solid var(--border);
  box-shadow:
    0 0 0 1px var(--border),
    0 0 24px -8px var(--accent-glow);
}
.glow-card:hover {
  border-color: var(--accent);
  box-shadow:
    0 0 0 1px var(--accent),
    0 0 32px -6px var(--accent-glow),
    0 0 60px -20px var(--accent-glow);
}
```

**Status dot with glow** — your existing `mcp-dot.online` (line 1367) does this; refine:
```css
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 6px var(--accent), 0 0 12px var(--accent-glow);
}
/* Pulsing version */
.status-dot.live::before {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.4;
  animation: pulse-ring 2s ease-out infinite;
}
@keyframes pulse-ring {
  0%   { transform: scale(1);    opacity: 0.5; }
  100% { transform: scale(2.4);  opacity: 0; }
}
```

**`drop-shadow` filter vs `box-shadow`** — for SVG icons, `filter: drop-shadow()` follows the shape; `box-shadow` is rectangular. Use `drop-shadow` for icon glow.

**Critical anti-pattern:** never apply glow to body text. Reserve for status values, metric numbers, and section headers.

---

## 4. Thin Line Aesthetics — 1px Borders, Dividers, Panels

### CSS reset for crisp 1px borders

HiDPI displays render `1px` as 2 device pixels — fuzzy. Two fixes:

```css
/* Option A: sub-pixel borders via inset shadow */
.crisp-border {
  border: 1px solid var(--border);
  box-shadow: inset 0 0 0 1px hsl(0 0% 100% / 0.02);
}

/* Option B: border via background-clip (best for variable borders) */
.panel {
  background:
    linear-gradient(var(--surface), var(--surface)) padding-box,
    linear-gradient(180deg, var(--border-light), var(--border)) border-box;
  border: 1px solid transparent;
  border-radius: var(--radius);
}
```

### Panel/terminal aesthetic patterns

**"Window chrome" header bar:**
```css
.panel { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: hidden; }
.panel-header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--muted);
}
.panel-header::before {
  content: '▸';  /* or ❯ */
  color: var(--accent);
  font-size: 10px;
}
```

**Traffic-light dots (macOS terminal reference, very classy):**
```css
.window-dots { display: flex; gap: 6px; margin-right: 8px; }
.window-dots span {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--muted); opacity: 0.5;
}
```

**Subtle dotted divider:**
```css
.divider-dot {
  height: 0;
  border-top: 1px dashed var(--border-light);
}
.divider-glow {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent-glow), transparent);
}
```

**Grid background (very subtle, adds texture):**
```css
.grid-bg {
  background-image:
    linear-gradient(var(--border) 1px, transparent 1px),
    linear-gradient(90deg, var(--border) 1px, transparent 1px);
  background-size: 24px 24px;
  background-position: -1px -1px;
  opacity: 0.3;
}
/* Or radial dot grid */
.dot-bg {
  background-image: radial-gradient(circle, var(--border-light) 1px, transparent 1px);
  background-size: 16px 16px;
}
```

**Corner brackets (terminal-y without being silly):**
```css
.corner-brackets {
  position: relative;
  padding: 12px;
}
.corner-brackets::before,
.corner-brackets::after {
  content: '';
  position: absolute;
  width: 10px; height: 10px;
  border: 1px solid var(--accent);
}
.corner-brackets::before { top: 0; left: 0; border-right: 0; border-bottom: 0; }
.corner-brackets::after  { bottom: 0; right: 0; border-left: 0; border-top: 0; }
```

---

## 5. Animations — Subtle, Restrained, Purposeful

### Core rules

- **Duration 120-250ms** for state changes; longer feels laggy.
- **Use `ease-out` for entrances, `ease-in` for exits.** Never linear except for continuous motion (spinners).
- **Animate `transform` and `opacity`** — they're GPU-composited. Avoid animating `width`/`height`/`top`/`left`.
- **`prefers-reduced-motion` is mandatory:**
  ```css
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      transition-duration: 0.01ms !important;
  } }
  ```

### Micro-interactions

**Card hover lift:**
```css
.card {
  transition:
    transform 180ms ease-out,
    border-color 180ms ease-out,
    box-shadow 180ms ease-out;
}
.card:hover {
  transform: translateY(-1px);
  border-color: var(--accent-dim);
}
```

**Button press:**
```css
.btn:active { transform: translateY(1px) scale(0.98); }
```

**Tab indicator slide** (instead of "pop in/out"):
```css
.tab-indicator {
  position: absolute;
  bottom: 0;
  height: 2px;
  background: var(--accent);
  transition: left 220ms cubic-bezier(0.4, 0, 0.2, 1),
              width 220ms cubic-bezier(0.4, 0, 0.2, 1);
}
```

### Skeleton loaders

```css
@keyframes shimmer {
  0%   { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
.skeleton {
  background: linear-gradient(
    90deg,
    var(--surface-2) 0%,
    var(--surface-3) 50%,
    var(--surface-2) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
  border-radius: var(--radius-sm);
}
```

### Page transitions

For Alpine.js SPA-style view swaps:
```css
[x-transition] {
  transition: opacity 180ms ease-out, transform 180ms ease-out;
}
.fade-enter { opacity: 0; transform: translateY(4px); }
.fade-enter-active { opacity: 1; transform: none; }
```

### Number tickers (for live metrics)

```js
// Alpine component — counts from old to new over 600ms
function tween(from, to, duration = 600) {
  const start = performance.now();
  return new Promise(resolve => {
    function step(now) {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);  // ease-out cubic
      const value = from + (to - from) * eased;
      if (t < 1) requestAnimationFrame(step); else resolve(to);
    }
    requestAnimationFrame(step);
  });
}
```

### Pulsing live indicators (SSE-connected widgets)

```css
@keyframes live-pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 var(--accent-glow); }
  50%      { opacity: 0.7; box-shadow: 0 0 0 6px transparent; }
}
.live-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: live-pulse 2s ease-in-out infinite;
}
```

---

## 6. Theme Selector UX

### Pattern: accent picker (not full theme picker)

Users care about accent color more than full themes. One accent variable controls everything.

```html
<div class="accent-picker" x-data="{ accent: localStorage.getItem('accent') || '152' }">
  <button @click="accent='152'; document.documentElement.style.setProperty('--accent-h', accent); localStorage.setItem('accent', accent)"
          :class="{ active: accent==='152' }" data-color="#00ff88"></button>
  <button @click="accent='195'; ..." :class="{ active: accent==='195' }" data-color="#00d4ff"></button>
  <button @click="accent='290'; ..." :class="{ active: accent==='290' }" data-color="#a855f7"></button>
  <button @click="accent='35'; ..."  :class="{ active: accent==='35'  }" data-color="#ffaa00"></button>
  <button @click="accent='340'; ..." :class="{ active: accent==='340' }" data-color="#ff2a6d"></button>
</div>
```

```css
.accent-picker { display: flex; gap: 8px; }
.accent-picker button {
  width: 22px; height: 22px;
  border-radius: 50%;
  border: 2px solid var(--border);
  cursor: pointer;
  transition: transform 120ms ease-out, border-color 120ms;
}
.accent-picker button:hover { transform: scale(1.15); }
.accent-picker button.active {
  border-color: var(--fg);
  box-shadow: 0 0 0 2px var(--bg), 0 0 8px currentColor;
}
```

CSS handles everything via HSL:
```js
document.documentElement.style.setProperty('--accent-h', userChoice);
```

The `accent-dim`/`accent-glow`/`accent-cyan` cascade automatically.

### Settings page integration

```html
<fieldset>
  <legend>Accent</legend>
  <div class="accent-picker">
    <button data-h="152" style="--c: #00ff88" aria-label="Phosphor green"></button>
    <button data-h="195" style="--c: #00d4ff" aria-label="Cyber cyan"></button>
    ...
  </div>
</fieldset>
<fieldset>
  <legend>Density</legend>
  <label><input type="radio" name="density" value="comfortable"> Comfortable</label>
  <label><input type="radio" name="density" value="compact"> Compact</label>
</fieldset>
<fieldset>
  <legend>Motion</legend>
  <label><input type="checkbox" name="motion"> Reduced motion</label>
</fieldset>
```

### Persistence

```js
// On any setting change
function savePrefs(prefs) {
  localStorage.setItem('lamadb-prefs', JSON.stringify(prefs));
  applyPrefs(prefs);
}
// On boot (before Alpine init)
const saved = JSON.parse(localStorage.getItem('lamadb-prefs') || '{}');
if (saved.accentH) document.documentElement.style.setProperty('--accent-h', saved.accentH);
if (saved.theme === 'light') document.documentElement.dataset.theme = 'light';
if (saved.reducedMotion) document.documentElement.dataset.reducedMotion = 'true';
```

---

## 7. "Smart Notes" / Attention Cards

The pattern: surface "what needs you" without screaming.

### Layout principles

- **Single attention zone per page.** Don't have 5 "urgent" cards.
- **Lead with action, not description.** "3 monitors down" > "Here's what's happening."
- **Right-align actions.** User scans left-to-right, action is the destination.
- **Progressive disclosure.** One-line summary by default; click to expand.

### Card structure

```html
<article class="attention-card" data-severity="warning">
  <header>
    <span class="attention-pulse"></span>
    <h3>3 services need attention</h3>
    <time>2 min ago</time>
  </header>
  <ul class="attention-list">
    <li><span class="dot down"></span> Sonarr <span class="reason">timeout</span></li>
    <li><span class="dot down"></span> Radarr <span class="reason">timeout</span></li>
    <li><span class="dot degraded"></span> Wiki sync <span class="reason">stale 4h</span></li>
  </ul>
  <footer>
    <button class="btn-ghost">Dismiss</button>
    <button class="btn-primary">Investigate →</button>
  </footer>
</article>
```

```css
.attention-card {
  border: 1px solid var(--warn-dim);
  background:
    linear-gradient(180deg, var(--warn-dim) 0%, transparent 30%),
    var(--surface);
  border-radius: var(--radius);
  padding: 16px;
  position: relative;
}
.attention-card[data-severity="critical"] {
  border-color: var(--danger);
  background:
    linear-gradient(180deg, var(--danger-dim) 0%, transparent 30%),
    var(--surface);
}
.attention-card[data-severity="info"] {
  border-color: var(--accent-cyan);
  background:
    linear-gradient(180deg, var(--accent-cyan-dim) 0%, transparent 30%),
    var(--surface);
}

.attention-pulse {
  display: inline-block; width: 8px; height: 8px;
  border-radius: 50%; background: var(--warn);
  box-shadow: 0 0 0 0 var(--warn);
  animation: pulse-warn 2s ease-out infinite;
}
@keyframes pulse-warn {
  0%   { box-shadow: 0 0 0 0 var(--warn-glow); }
  100% { box-shadow: 0 0 0 8px transparent; }
}

.attention-card header {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 12px;
}
.attention-card header h3 { font-size: 14px; font-weight: 600; flex: 1; }
.attention-card header time { font-family: var(--font-mono); font-size: 11px; color: var(--muted); }
```

### Insight card variants

| Type | Visual | Use |
|------|--------|-----|
| **Alert** (red border, pulsing dot) | "3 monitors down" | Service failures |
| **Heads-up** (amber) | "Wiki sync stale 4h" | Degraded but not broken |
| **Insight** (cyan, no pulse) | "12 unread kanban tasks assigned to you" | Awareness |
| **Nudge** (purple/accent, no border emphasis) | "Your morning brief is ready →" | Actionable suggestion |

### Quiet variant (no border, just elevation)

```css
.insight-quiet {
  background: var(--surface-2);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex; align-items: center; gap: 12px;
}
.insight-quiet .icon {
  width: 32px; height: 32px;
  border-radius: var(--radius-sm);
  background: var(--accent-dim);
  color: var(--accent);
  display: grid; place-items: center;
}
```

---

## 8. Mobile Adaptations

### Core problem

Neon glow + small screens = muddy unreadable mess. Lines that look crisp at 16px become blurry at 320px width.

### Specific fixes

**Disable glow on small screens** (battery + clarity):
```css
@media (max-width: 640px) {
  .glow-card, .glow-text { box-shadow: none !important; text-shadow: none !important; }
}
```

**Compress spacing scale:**
```css
:root { --gap-1: 4px; --gap-2: 8px; --gap-3: 12px; --gap-4: 16px; --gap-5: 24px; }
@media (max-width: 640px) {
  :root { --gap-1: 3px; --gap-2: 6px; --gap-3: 10px; --gap-4: 12px; --gap-5: 18px; }
}
```

**Collapse panels to bottom-sheets** instead of dropdowns:
```css
@media (max-width: 768px) {
  .panel-grid { grid-template-columns: 1fr; }
  .detail-panel {
    position: fixed; inset: 0; z-index: 100;
    border-radius: 0;
    transform: translateY(100%);
    transition: transform 220ms ease-out;
  }
  .detail-panel.open { transform: translateY(0); }
}
```

**Sidebar → bottom tab bar:**
```css
@media (max-width: 768px) {
  .sidebar { display: none; }
  .bottom-tabs {
    display: flex;
    position: fixed; bottom: 0; left: 0; right: 0;
    background: var(--surface);
    border-top: 1px solid var(--border);
    padding: 8px;
    gap: 4px;
    z-index: 50;
  }
  .bottom-tabs button {
    flex: 1;
    padding: 8px;
    font-size: 11px;
    color: var(--fg-2);
    border-radius: var(--radius-sm);
    background: none; border: none;
  }
  .bottom-tabs button.active {
    background: var(--accent-dim);
    color: var(--accent);
  }
  /* Push content above tab bar */
  .main { padding-bottom: 64px; }
}
```

**Truncate aggressively:**
```css
.truncate-mobile {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 60vw;
}
@media (min-width: 768px) {
  .truncate-mobile { max-width: none; overflow: visible; white-space: normal; }
}
```

**Hide mono decorations on mobile** — `▸` arrows, decorative `·` separators often add visual noise without value:
```css
@media (max-width: 640px) {
  .panel-header::before { content: ''; }
}
```

**Touch targets:** minimum 44×44px. Increase padding on interactive elements:
```css
@media (max-width: 768px) {
  .btn { padding: 12px 16px; }
  .tab-btn { padding: 12px 14px; }
}
```

---

## 9. Backdrop Filter & Glass

Use sparingly — overdone = "Apple keynote 2014." One signature use per page.

```css
.glass-panel {
  background: hsl(0 0% 8% / 0.6);
  backdrop-filter: blur(12px) saturate(180%);
  -webkit-backdrop-filter: blur(12px) saturate(180%);
  border: 1px solid hsl(0 0% 100% / 0.06);
}
/* Fallback for browsers without backdrop-filter */
@supports not (backdrop-filter: blur(1px)) {
  .glass-panel { background: var(--surface); }
}
```

Best uses: top header (always-visible glass over scrolling content), modal overlay, sticky ticker bar.

---

## 10. Three Distinct Visual Directions

### Direction A — "Calm Operator" (Recommended for daily-use Life-OS)

- Dark surface `#0f1115`, slightly warm
- Single accent (cyan OR green, user-selectable)
- Restrained glow — only on active states, status dots, primary CTA
- Mono for data, Inter for UI
- Subtle 1px borders, no corner brackets, no traffic lights
- Quiet attention cards, minimal motion
- Tradeoff: less "wow factor" on first impression, but excellent for 8-hour daily use
- **Best fit for: serious Life-OS, "I live in this" dashboard**

### Direction B — "Cyberdeck Hacker" (Power-user aesthetic)

- Pure black `#000` to `#0a0a0a`
- Dual accents (cyan + magenta simultaneously)
- Generous glow — borders, text, dots all glow
- Mono for almost everything, JetBrains Mono large sizes for headlines
- Corner brackets, traffic lights, scanlines (subtle)
- Bold attention cards with pulsing dots, animated ticker
- Tradeoff: high visual energy, eye-fatigue over long sessions
- **Best fit for: technical users, "I want to feel like I'm in Ghost in the Shell"**

### Direction C — "Editorial Dashboard" (Notion-meets-Terminal)

- Off-black `#14161a`, slightly desaturated
- Muted accent (`#88c0d0` Nord-cyan or `#a3be8c` Nord-green) — almost no glow
- Inter Display everywhere except numeric metrics
- Generous spacing, large type, no panel chrome
- Cards with subtle borders + lots of whitespace
- Tradeoff: loses the "terminal" feel entirely; minimal glow
- **Best fit for: stakeholders, screenshots, "I want it to look professional in a screen-share"**

---

## 11. Quick-Implement Recipe

Top 10 wins, ranked by ROI:

1. **HSL-based accent tokens** (`--accent-h` driving everything) — enables theme picker for ~30 lines of JS.
2. **`font-variant-numeric: tabular-nums`** on all `.stat-value` and `table` — 1-line CSS, instant data alignment.
3. **Pulse keyframe** for live SSE indicators — 5 lines, transforms the feel of real-time data.
4. **`prefers-reduced-motion` guard** — accessibility compliance, 4 lines.
5. **`@media (max-width: 640px) { .glow-* { box-shadow: none; text-shadow: none; } }`** — battery + clarity on mobile.
6. **Section headers with `▸` indicator + uppercase mono caption** — gives "terminal command output" vibe without trying.
7. **`.skeleton` shimmer class** — replaces awkward "loading..." text with something that feels intentional.
8. **Attention card with severity color band** — the core "smart notes" pattern in one component.
9. **`color-mix(in srgb, var(--accent), white 10%)`** for hover states — automatic hover lightening, no need for separate `--accent-hover` tokens.
10. **`background: linear-gradient(180deg, var(--warn-dim) 0%, transparent 30%), var(--surface)`** for attention cards — gives a "glow from top" feel without expensive filters.

---

## 12. Anti-Patterns Checklist

- ❌ Glow on body text → reduces readability, looks like spam
- ❌ Pure `#000` background → makes neon garish, use `#0a0a0a`-ish
- ❌ More than 2 accents competing at once → visual chaos
- ❌ Animations longer than 300ms for state changes → feels broken
- ❌ Neon on neon (e.g. cyan border + green text in same card) → clashes
- ❌ `text-shadow: 0 0 20px` on more than 3 elements per viewport → washes out
- ❌ Corners brackets on every panel → becomes noise, reserve for "special" sections
- ❌ Traffic-light dots on non-window-chrome elements → misleads about interactivity
- ❌ Mono fonts for headings > 24px → reads as "developer demo" not "product"
- ❌ Glassmorphism on multiple overlapping layers → performance + illegibility
