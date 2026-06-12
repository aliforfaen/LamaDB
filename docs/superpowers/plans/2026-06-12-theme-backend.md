# Theme Backend Basics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist per-user theme preferences (color scheme + accent color) server-side with GET/PUT endpoints and frontend integration.

**Architecture:** JSONB column on `users` table, REST endpoints, frontend dual-write (localStorage + API), CSS custom property `--accent` for accent colors.

**Tech Stack:** PostgreSQL (JSONB), FastAPI, vanilla JS, CSS custom properties

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `migrations/015_user_theme.sql` | Add theme column to users |
| Modify | `app/core/users.py` | Add GET/PUT theme endpoints |
| Modify | `static/js/app.js` | Fetch theme on login, apply accent |
| Modify | `static/js/pages/settings.js` | Add Appearance section with accent picker |
| Modify | `static/css/dashboard.css` | Replace hardcoded accents with `var(--accent)` |

---

### Task 1: Migration — Add Theme Column

**Files:**
- Create: `migrations/015_user_theme.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 015_user_theme.sql
-- Add per-user theme preferences (color scheme + accent color)

ALTER TABLE users ADD COLUMN IF NOT EXISTS theme JSONB DEFAULT '{"scheme": "dark", "accent": "#6366f1"}';
```

- [ ] **Step 2: Commit**

```bash
git add migrations/015_user_theme.sql
git commit -m "feat(theme): add theme JSONB column to users table"
```

---

### Task 2: Theme API Endpoints

**Files:**
- Modify: `app/core/users.py`

- [ ] **Step 1: Add GET /api/users/me/theme endpoint**

Add after the existing `deactivate_user` endpoint:

```python
@router.get("/users/me/theme")
async def get_my_theme(
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Get the authenticated user's theme preferences."""
    if not user.user_id:
        return {"scheme": "dark", "accent": "#6366f1"}

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT theme FROM users WHERE id = $1", user.user_id)

    if not row or not row["theme"]:
        return {"scheme": "dark", "accent": "#6366f1"}

    theme = row["theme"]
    if isinstance(theme, str):
        import json
        theme = json.loads(theme)

    return theme
```

- [ ] **Step 2: Add PUT /api/users/me/theme endpoint**

```python
@router.put("/users/me/theme")
async def update_my_theme(
    body: dict,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Update the authenticated user's theme preferences."""
    if not user.user_id:
        raise HTTPException(status_code=403, detail="No user identity on this API key")

    scheme = body.get("scheme", "dark")
    accent = body.get("accent", "#6366f1")

    if scheme not in ("dark", "light"):
        raise HTTPException(status_code=422, detail="scheme must be 'dark' or 'light'")

    import re
    if not re.match(r'^#[0-9a-fA-F]{6}$', accent):
        raise HTTPException(status_code=422, detail="accent must be a hex color like '#6366f1'")

    import json
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET theme = $1, updated_at = now() WHERE id = $2",
            json.dumps({"scheme": scheme, "accent": accent}),
            user.user_id,
        )

    return {"scheme": scheme, "accent": accent}
```

- [ ] **Step 3: Commit**

```bash
git add app/core/users.py
git commit -m "feat(theme): add GET/PUT /api/users/me/theme endpoints"
```

---

### Task 3: Frontend — Fetch Theme on Login

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 1: Add applyAccent function**

After the `applyTheme` function (around line 156), add:

```javascript
function applyAccent(accent) {
  document.documentElement.style.setProperty('--accent', accent);
  // Also set derived shades
  document.documentElement.style.setProperty('--accent-dim', accent + '20');
  document.documentElement.style.setProperty('--accent-glow', accent + '40');
}
window.applyAccent = applyAccent;
```

- [ ] **Step 2: Add fetchAndApplyTheme function**

```javascript
async function fetchAndApplyTheme() {
  try {
    var theme = await api('/api/users/me/theme');
    if (theme && theme.scheme) {
      applyTheme(theme.scheme);
      localStorage.setItem('lamadb_theme', theme.scheme);
    }
    if (theme && theme.accent) {
      applyAccent(theme.accent);
      localStorage.setItem('lamadb_accent', theme.accent);
    }
  } catch (e) {
    // Fall back to localStorage
    var storedAccent = localStorage.getItem('lamadb_accent');
    if (storedAccent) applyAccent(storedAccent);
  }
}
```

- [ ] **Step 3: Call fetchAndApplyTheme on auth success**

In the `submitApiKey` function, after `hideAuthModal()` and `connectSSE()`:

```javascript
fetchAndApplyTheme();
```

Also in the bootstrap function, after the `api('/api/dashboard/overview').then(...)` call:

```javascript
fetchAndApplyTheme();
```

- [ ] **Step 4: Update toggleTheme to persist server-side**

Modify `window.toggleTheme` to also call the API:

```javascript
window.toggleTheme = function() {
  var newTheme = _currentTheme === 'dark' ? 'light' : 'dark';
  localStorage.setItem('lamadb_theme', newTheme);
  applyTheme(newTheme);
  // Persist to server (non-blocking)
  var accent = localStorage.getItem('lamadb_accent') || '#6366f1';
  api('/api/users/me/theme', {
    method: 'PUT',
    body: JSON.stringify({ scheme: newTheme, accent: accent })
  }).catch(function() {});
};
```

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js
git commit -m "feat(theme): fetch theme on login, apply accent, persist toggle"
```

---

### Task 4: Frontend — Accent Picker in Settings

**Files:**
- Modify: `static/js/pages/settings.js`

- [ ] **Step 1: Add Appearance section to loadSettings**

In `window.loadSettings`, add a call to `loadAppearance()`:

```javascript
window.loadSettings = async function() {
  loadModules();
  loadModuleConfigs();
  loadApiKeys();
  loadHealth();
  loadCacheStats();
  loadAppearance();  // Add this
};
```

- [ ] **Step 2: Add loadAppearance function**

```javascript
function loadAppearance() {
  var container = document.getElementById('appearance-section');
  if (!container) return;

  var accents = [
    { name: 'Indigo', hex: '#6366f1' },
    { name: 'Emerald', hex: '#10b981' },
    { name: 'Rose', hex: '#f43f5e' },
    { name: 'Amber', hex: '#f59e0b' },
    { name: 'Cyan', hex: '#06b6d4' },
    { name: 'Violet', hex: '#8b5cf6' },
  ];

  var currentAccent = localStorage.getItem('lamadb_accent') || '#6366f1';
  var currentScheme = localStorage.getItem('lamadb_theme') || 'dark';

  container.innerHTML =
    '<h4>Appearance</h4>' +
    '<div style="margin-bottom:16px;">' +
      '<label style="display:block;margin-bottom:8px;color:var(--fg-2);font-size:13px;">Color Scheme</label>' +
      '<div style="display:flex;gap:8px;">' +
        '<button class="btn btn-sm ' + (currentScheme === 'dark' ? 'btn-primary' : 'btn-ghost') + '" onclick="window.toggleTheme(); loadAppearance();">Dark</button>' +
        '<button class="btn btn-sm ' + (currentScheme === 'light' ? 'btn-primary' : 'btn-ghost') + '" onclick="window.toggleTheme(); loadAppearance();">Light</button>' +
      '</div>' +
    '</div>' +
    '<div>' +
      '<label style="display:block;margin-bottom:8px;color:var(--fg-2);font-size:13px;">Accent Color</label>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;">' +
        accents.map(function(a) {
          var isActive = a.hex === currentAccent;
          return '<button class="accent-swatch' + (isActive ? ' active' : '') + '" ' +
            'onclick="setAccent(\'' + a.hex + '\')" ' +
            'title="' + a.name + '" ' +
            'style="width:32px;height:32px;border-radius:50%;background:' + a.hex + ';border:3px solid ' + (isActive ? 'var(--fg)' : 'transparent') + ';cursor:pointer;transition:border-color 0.2s;">' +
          '</button>';
        }).join('') +
      '</div>' +
    '</div>';
}

window.setAccent = function(hex) {
  localStorage.setItem('lamadb_accent', hex);
  if (window.applyAccent) window.applyAccent(hex);
  // Persist to server
  var scheme = localStorage.getItem('lamadb_theme') || 'dark';
  window.api('/api/users/me/theme', {
    method: 'PUT',
    body: JSON.stringify({ scheme: scheme, accent: hex })
  }).catch(function() {});
  loadAppearance();
};
```

- [ ] **Step 3: Add appearance section to HTML**

In `static/index.html`, in the Settings page tab-panel for "general", add:

```html
<div id="appearance-section" class="settings-card"></div>
```

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/settings.js static/index.html
git commit -m "feat(theme): add accent picker to Settings page"
```

---

### Task 5: CSS — Replace Hardcoded Accents

**Files:**
- Modify: `static/css/dashboard.css`

- [ ] **Step 1: Add --accent custom property to :root**

In the CSS file, find the `:root` or `[data-theme="dark"]` block and add:

```css
:root {
  --accent: #6366f1;
  --accent-dim: #6366f120;
  --accent-glow: #6366f140;
}
```

- [ ] **Step 2: Replace hardcoded accent colors**

Search for hardcoded `#6366f1` (or similar accent colors) in the CSS and replace with `var(--accent)`. Common locations:
- Button backgrounds
- Link colors
- Active states
- Focus rings
- Badge colors

**Important:** Only replace colors that should follow the accent theme. Keep colors that are semantically different (e.g., success green, danger red).

- [ ] **Step 3: Commit**

```bash
git add static/css/dashboard.css
git commit -m "feat(theme): replace hardcoded accent colors with CSS var(--accent)"
```

---

## Execution Order

1. Task 1 (Migration) — standalone
2. Task 2 (API endpoints) — depends on migration
3. Task 3 (Frontend fetch) — depends on API
4. Task 4 (Accent picker) — depends on API + fetch
5. Task 5 (CSS) — can be done in parallel with 3-4

## Verification

After all tasks:
```bash
docker compose build api && docker compose up -d api
```
1. Login → theme should persist across refresh
2. Toggle dark/light → should persist
3. Pick accent color → should update immediately and persist
4. Check Settings → Appearance section with 6 color swatches
