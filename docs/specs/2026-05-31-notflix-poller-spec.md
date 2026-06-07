# LamaDB — Notflix Media Poller Spec

> **For Hermes delegate_task:** This is a self-contained implementation spec. Execute with TDD, following the module patterns in AGENTS.md. Use MiniMax-M2.7-highspeed.

**Goal:** Build a Notflix media poller module that periodically polls Sonarr, Radarr, and Tautulli APIs and surfaces library health, recent activity, and new content in the LamaDB dashboard.

**Repo:** `/home/messhias/LamaFiles/projects/lamadb/`
**Tech:** Python 3.12, FastAPI, asyncpg, httpx, Docker Compose

---

## Architecture

```
modules/notflix/
├── __init__.py      # MODULE_NAME, ENABLED, get_router(), collect()
├── routes.py        # Dashboard API endpoints
├── models.py        # Pydantic models
├── collector.py     # Poller logic (Sonarr, Radarr, Tautulli)
└── .state           # Runtime enabled/disabled override
```

**Poller interval:** 30 minutes (1800s) — media data doesn't change rapidly.
**Dashboard tab:** "Notflix" tab in sidebar nav, showing library stats + recent activity.

---

## Phase 1: Module Skeleton + Configuration

### Config (app/config.py)

Add to `Settings` class:

```python
# Notflix module
sonarr_url: str = ""
sonarr_api_key: str = ""
radarr_url: str = ""
radarr_api_key: str = ""
tautulli_url: str = ""
tautulli_api_key: str = ""
```

These come from the notflix .env file (`/home/messhias/LamaFiles/projects/notflix-skill/.env`). The LamaDB docker-compose.yml needs these env vars passed through.

### __init__.py

```python
"""Notflix media stack poller — Sonarr, Radarr, Tautulli."""
MODULE_NAME = "notflix"
MODULE_DESCRIPTION = "Media library health and activity from Sonarr, Radarr, Tautulli"
MODULE_VERSION = "0.1.0"
ENABLED = True

def get_router():
    from .routes import router
    return router

async def collect():
    """Run the media poller."""
    from .collector import collect as _collect
    return await _collect()
```

---

## Phase 2: Collector (collector.py)

### Poll Sonarr

```python
async def _poll_sonarr(client):
    """Fetch Sonarr library stats."""
    if not settings.sonarr_url or not settings.sonarr_api_key:
        return {"error": "Sonarr not configured"}

    headers = {"X-Api-Key": settings.sonarr_api_key}

    # Series count
    series_resp = await client.get(f"{settings.sonarr_url}/api/v3/series", headers=headers)
    series_resp.raise_for_status()
    series = series_resp.json()
    series_count = len(series)

    # Episode stats
    episodes = []
    for s in series[:50]:  # limit to avoid timeout
        ep_resp = await client.get(
            f"{settings.sonarr_url}/api/v3/episode?seriesId={s['id']}",
            headers=headers
        )
        ep_resp.raise_for_status()
        episodes.extend(ep_resp.json())

    total_episodes = len(episodes)
    episodes_with_file = sum(1 for ep in episodes if ep.get("hasFile"))

    # Missing episodes
    missing_resp = await client.get(
        f"{settings.sonarr_url}/api/v3/wanted/missing?page=1&pageSize=1",
        headers=headers
    )
    missing_resp.raise_for_status()
    missing_count = missing_resp.json().get("totalRecords", 0)

    # Queue
    queue_resp = await client.get(
        f"{settings.sonarr_url}/api/v3/queue?page=1&pageSize=1",
        headers=headers
    )
    queue_resp.raise_for_status()
    queue_count = queue_resp.json().get("totalRecords", 0)

    # Recent grabs (last 24h)
    history_resp = await client.get(
        f"{settings.sonarr_url}/api/v3/history?page=1&pageSize=20",
        headers=headers
    )
    history_resp.raise_for_status()
    recent = history_resp.json().get("records", [])

    return {
        "series_count": series_count,
        "total_episodes": total_episodes,
        "episodes_available": episodes_with_file,
        "missing_count": missing_count,
        "queue_count": queue_count,
        "recent_grabs": len([r for r in recent if r.get("eventType") == "grabbed"]),
    }
```

**⚠️ Do NOT iterate over ALL series for episode counts.** Sonarr can have 100+ series each with 50+ episodes = 5000+ API calls. Limit to first 50 series or use the `/api/v3/wanted/missing` endpoint for aggregate stats. The `totalRecords` field on paginated endpoints gives counts without fetching all items.

### Poll Radarr

Same pattern, substituting `/api/v3/movie` for series, `/api/v3/queue`, `/api/v3/history`:

```python
async def _poll_radarr(client):
    """Fetch Radarr library stats."""
    if not settings.radarr_url or not settings.radarr_api_key:
        return {"error": "Radarr not configured"}

    headers = {"X-Api-Key": settings.radarr_api_key}

    # Movie count
    movies_resp = await client.get(f"{settings.radarr_url}/api/v3/movie", headers=headers)
    movies_resp.raise_for_status()
    movies = movies_resp.json()
    movie_count = len(movies)
    movies_available = sum(1 for m in movies if m.get("hasFile"))

    # Missing
    missing_resp = await client.get(
        f"{settings.radarr_url}/api/v3/wanted/missing?page=1&pageSize=1",
        headers=headers
    )
    missing_resp.raise_for_status()
    missing_count = missing_resp.json().get("totalRecords", 0)

    # Queue
    queue_resp = await client.get(
        f"{settings.radarr_url}/api/v3/queue?page=1&pageSize=1",
        headers=headers
    )
    queue_resp.raise_for_status()
    queue_count = queue_resp.json().get("totalRecords", 0)

    # Recent grabs
    history_resp = await client.get(
        f"{settings.radarr_url}/api/v3/history?page=1&pageSize=20",
        headers=headers
    )
    history_resp.raise_for_status()
    recent = history_resp.json().get("records", [])

    return {
        "movie_count": movie_count,
        "movies_available": movies_available,
        "missing_count": missing_count,
        "queue_count": queue_count,
        "recent_grabs": len([r for r in recent if r.get("eventType") == "grabbed"]),
    }
```

### Poll Tautulli

```python
async def _poll_tautulli(client):
    """Fetch Tautulli Plex activity."""
    if not settings.tautulli_url or not settings.tautulli_api_key:
        return {"error": "Tautulli not configured"}

    # Current activity
    activity_resp = await client.get(
        f"{settings.tautulli_url}/api/v2",
        params={"apikey": settings.tautulli_api_key, "cmd": "get_activity"}
    )
    activity_resp.raise_for_status()
    activity = activity_resp.json()

    sessions = activity.get("response", {}).get("data", {}).get("sessions", [])
    active_streams = len(sessions)

    # Recent history (last hour)
    history_resp = await client.get(
        f"{settings.tautulli_url}/api/v2",
        params={"apikey": settings.tautulli_api_key, "cmd": "get_history", "length": 10}
    )
    history_resp.raise_for_status()
    history = history_resp.json()

    recent = history.get("response", {}).get("data", {}).get("data", [])
    recent_watches = [
        {
            "user": r.get("friendly_name", r.get("user", "")),
            "title": r.get("full_title", ""),
            "date": r.get("date", 0),
            "platform": r.get("platform", ""),
        }
        for r in recent[:5]
    ]

    return {
        "active_streams": active_streams,
        "recent_watches": recent_watches,
    }
```

### Main collect() function

```python
async def collect() -> dict:
    """Poll all media services and store results in events table."""
    import json
    from app.db import get_pool
    from app.config import settings

    results = {"sonarr": None, "radarr": None, "tautulli": None}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            results["sonarr"] = await _poll_sonarr(client)
        except Exception as e:
            results["sonarr"] = {"error": str(e)}

        try:
            results["radarr"] = await _poll_radarr(client)
        except Exception as e:
            results["radarr"] = {"error": str(e)}

        try:
            results["tautulli"] = await _poll_tautulli(client)
        except Exception as e:
            results["tautulli"] = {"error": str(e)}

    # Store summary as an event
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO events (source, type, severity, title, body, metadata, ticker, tags)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            "notflix", "media_snapshot", "info",
            "Media library snapshot",
            json.dumps(results),
            json.dumps(results),
            False,  # not a ticker item (too frequent)
            ["notflix", "media", "snapshot"],
        )

    return results
```

### Poller Registration

In `app/main.py`, add to the poller loop list:

```python
for module_name, interval in [
    ("freshrss", 900),
    ("ntfy", 300),
    ("dozzle", 300),
    ("notflix", 1800),  # ← ADD THIS
]:
```

---

## Phase 3: API Routes (routes.py)

### GET /api/notflix/status

Returns the latest media snapshot from the events table:

```python
@router.get("/status")
async def get_status(user: Annotated[AuthUser, Depends(_require_auth)]):
    """Get the latest media library snapshot."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT metadata, ts FROM events
               WHERE source = 'notflix' AND type = 'media_snapshot'
               ORDER BY ts DESC LIMIT 1"""
        )
    if not row:
        return {"status": "no_data"}
    
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return {"data": meta, "ts": row["ts"].isoformat()}
```

### GET /api/notflix/activity

Returns recent media activity (grabs, watches) from events:

```python
@router.get("/activity")
async def get_activity(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=20, ge=1, le=100),
):
    """Get recent media activity (recent grabs, watches)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT source, type, severity, title, body, metadata, ts
               FROM events
               WHERE source IN ('sonarr', 'radarr', 'tautulli', 'notflix')
               ORDER BY ts DESC LIMIT $1""",
            limit,
        )
    
    events = []
    for row in rows:
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        events.append({
            "source": row["source"],
            "type": row["type"],
            "title": row["title"],
            "body": row["body"],
            "metadata": meta,
            "ts": row["ts"].isoformat(),
        })
    
    return {"events": events, "count": len(events)}
```

### GET /api/notflix/health

Quick health check for all configured services:

```python
@router.get("/health")
async def check_health(user: Annotated[AuthUser, Depends(_require_auth)]):
    """Check which media services are reachable."""
    results = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, url, key in [
            ("sonarr", settings.sonarr_url, settings.sonarr_api_key),
            ("radarr", settings.radarr_url, settings.radarr_api_key),
            ("tautulli", settings.tautulli_url, settings.tautulli_api_key),
        ]:
            if not url:
                results[name] = {"reachable": False, "reason": "not configured"}
                continue
            try:
                headers = {"X-Api-Key": key} if key else {}
                resp = await client.get(f"{url}/api/v3/system/status" if name != "tautulli" else f"{url}/api/v2?apikey={key}&cmd=get_activity", headers=headers, timeout=5.0)
                results[name] = {"reachable": resp.status_code < 500}
            except Exception as e:
                results[name] = {"reachable": False, "reason": str(e)}
    
    return results
```

---

## Phase 4: Dashboard UI

### HTML section (in static/index.html)

Add a "Notflix" nav button and page section following the existing pattern (copy from Ntfy/Dozzle pages):

```html
<!-- Nav button: add after Agent Board button -->
<button class="..." onclick="switchTab('notflix')">Notflix</button>

<!-- Page section: -->
<section id="page-notflix" class="page" aria-label="Notflix">
  <div class="filter-bar" style="margin-bottom:12px;">
    <span style="flex:1;"></span>
    <span id="notflix-status" style="font-size:12px;color:var(--muted);"></span>
    <button class="btn btn-sm btn-secondary" onclick="window.loadNotflixPage()">↻ Refresh</button>
  </div>

  <!-- Stats cards -->
  <div id="notflix-stats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;">
  </div>

  <!-- Recent activity -->
  <h3 style="margin-top:20px;">Recent Activity</h3>
  <div id="notflix-activity"><p class="loading">Loading…</p></div>
</section>
```

### JS functions (in static/index.html)

```javascript
async function loadNotflixPage() {
  try {
    var status = await api('/api/notflix/status');
    renderNotflixStats(status.data);
  } catch(e) {
    document.getElementById('notflix-stats').innerHTML = '<p class="error">Failed to load</p>';
  }

  try {
    var activity = await api('/api/notflix/activity?limit=20');
    renderNotflixActivity(activity.events);
  } catch(e) {
    document.getElementById('notflix-activity').innerHTML = '<p class="error">Failed to load</p>';
  }
}

function renderNotflixStats(data) {
  var html = '';
  if (data.sonarr && !data.sonarr.error) {
    var s = data.sonarr;
    html += '<div class="col-card">' +
      '<div style="font-weight:600;font-size:13px;">📺 Sonarr</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:8px;font-size:12px;">' +
      '<span>Series:</span><span style="font-weight:500;">' + (s.series_count || 0) + '</span>' +
      '<span>Episodes:</span><span style="font-weight:500;">' + (s.episodes_available || 0) + '/' + (s.total_episodes || 0) + '</span>' +
      '<span>Missing:</span><span style="font-weight:500;color:' + (s.missing_count > 0 ? 'var(--red)' : 'var(--green)') + ';">' + (s.missing_count || 0) + '</span>' +
      '<span>Queue:</span><span style="font-weight:500;">' + (s.queue_count || 0) + '</span>' +
      '</div></div>';
  }
  if (data.radarr && !data.radarr.error) {
    var r = data.radarr;
    html += '<div class="col-card">' +
      '<div style="font-weight:600;font-size:13px;">🎬 Radarr</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:8px;font-size:12px;">' +
      '<span>Movies:</span><span style="font-weight:500;">' + (r.movies_available || 0) + '/' + (r.movie_count || 0) + '</span>' +
      '<span>Missing:</span><span style="font-weight:500;color:' + (r.missing_count > 0 ? 'var(--red)' : 'var(--green)') + ';">' + (r.missing_count || 0) + '</span>' +
      '<span>Queue:</span><span style="font-weight:500;">' + (r.queue_count || 0) + '</span>' +
      '</div></div>';
  }
  if (data.tautulli && !data.tautulli.error) {
    var t = data.tautulli;
    html += '<div class="col-card">' +
      '<div style="font-weight:600;font-size:13px;">▶️ Now Playing</div>' +
      '<div style="font-size:28px;font-weight:700;margin-top:4px;">' + (t.active_streams || 0) + '</div>' +
      '<div style="font-size:12px;color:var(--muted);">active streams</div>' +
      '</div>';
  }
  document.getElementById('notflix-stats').innerHTML = html || '<p class="empty">No services configured</p>';
}

function renderNotflixActivity(events) {
  if (!events || events.length === 0) {
    document.getElementById('notflix-activity').innerHTML = '<p class="empty">No recent activity</p>';
    return;
  }
  var html = '<div class="table-wrap"><table><thead><tr><th>Time</th><th>Source</th><th>Title</th></tr></thead><tbody>';
  events.forEach(function(e) {
    var time = e.ts ? new Date(e.ts).toLocaleString() : '';
    html += '<tr>' +
      '<td class="mono nowrap">' + escHtml(time) + '</td>' +
      '<td style="font-weight:500;">' + escHtml(e.source) + '</td>' +
      '<td>' + escHtml(e.title || '') + '</td>' +
      '</tr>';
  });
  html += '</tbody></table></div>';
  document.getElementById('notflix-activity').innerHTML = html;
}

// Exports
window.loadNotflixPage = loadNotflixPage;
```

Also add to the tab switcher to call `loadNotflixPage()` when the tab is selected.

---

## Phase 5: Ticker Events for Noteworthy Activity

When a new download completes (movie grabbed, episode grabbed), create a ticker event:

In collector.py, after polling history:

```python
# Check for new grabs since last poll
async with pool.acquire() as conn:
    # Store last poll timestamp
    last_row = await conn.fetchrow(
        "SELECT ts FROM events WHERE source = 'notflix' AND type = 'media_snapshot' ORDER BY ts DESC LIMIT 1"
    )

    # If Sonarr grabbed new episodes, create ticker
    if sonarr_data.get("recent_grabs", 0) > 0:
        await conn.execute(
            """INSERT INTO events (source, type, severity, title, ticker, tags)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            "sonarr", "new_content", "info",
            f"{sonarr_data['recent_grabs']} new TV episodes grabbed",
            True, ["notflix", "sonarr", "new"],
        )

    # Same for Radarr
    if radarr_data.get("recent_grabs", 0) > 0:
        await conn.execute(
            """INSERT INTO events (source, type, severity, title, ticker, tags)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            "radarr", "new_content", "info",
            f"{radarr_data['recent_grabs']} new movies grabbed",
            True, ["notflix", "radarr", "new"],
        )
```

---

## Tests (tests/test_notflix.py)

```python
# Test cases:
# 1. test_module_loaded — module auto-discovered
# 2. test_get_status_no_data — returns "no_data" with 200
# 3. test_get_status_with_data — returns seeded snapshot
# 4. test_get_activity — returns recent events filtered by source
# 5. test_health_all_configured — health check returns reachable (mock if needed)
# 6. test_health_unconfigured — returns "not configured" for missing vars
# 7. test_collect_not_configured — returns error dicts for each service
# 8. test_unauthorized — 401 without auth header
```

---

## Docker Compose Changes

Add env vars to `docker-compose.yml` under the `api` service:

```yaml
environment:
  # ... existing vars ...
  - SONARR_URL=${SONARR_URL:-}
  - SONARR_API_KEY=${SONARR_API_KEY:-}
  - RADARR_URL=${RADARR_URL:-}
  - RADARR_API_KEY=${RADARR_API_KEY:-}
  - TAUTULLI_URL=${TAUTULLI_URL:-}
  - TAUTULLI_API_KEY=${TAUTULLI_API_KEY:-}
```

---

## Acceptance Criteria

- [ ] Module auto-discovered and routes registered
- [ ] `GET /api/notflix/status` returns latest snapshot or "no_data"
- [ ] `GET /api/notflix/activity` returns filtered events
- [ ] `GET /api/notflix/health` checks all 3 services
- [ ] Poller runs every 30 minutes, stores results in events table
- [ ] Dashboard tab shows stats cards + recent activity
- [ ] Ticker events fire for new grabs
- [ ] All services gracefully handle "not configured" state
- [ ] 8+ tests passing
- [ ] Docker build + force-recreate picks up changes

---

## Known Pitfalls

| # | Pitfall | Prevention |
|---|---------|------------|
| 1 | Sonarr episode fetch on ALL series = 5000+ API calls | Limit to first 50 series or use aggregate endpoints |
| 2 | Tautulli uses `apikey` query param, not header | Different auth pattern from *arr apps |
| 3 | httpx timeout on slow services | Set 30s timeout on AsyncClient, wrap each poll in try/except |
| 4 | Events table JSONB coercion | `isinstance(meta, str)` check before `json.loads()` |
| 5 | `docker compose restart` doesn't pick up new code | Always `build` + `up -d --force-recreate` |
| 6 | onclick handlers not on `window` | Export `loadNotflixPage` to window |
| 7 | FreshRSS poller interval already at 900s | Add notflix at 1800s in the poller loop list |
| 8 | Credential env vars not in Docker | Add to docker-compose.yml environment section |
