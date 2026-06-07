# LamaDB — Smart Notification Routing Spec

> **For Hermes delegate_task:** Self-contained implementation spec. Execute with TDD, following module patterns in AGENTS.md. Use MiniMax-M2.7-highspeed.

**Goal:** Build a notification routing engine that matches events against user-defined rules and dispatches to delivery channels (Telegram, ntfy, webhook). Replaces "all events go everywhere" with configurable per-source/per-severity routing.

**Repo:** `/home/messhias/LamaFiles/projects/lamadb/`
**Tech:** Python 3.12, FastAPI, asyncpg, httpx, Docker Compose

---

## Architecture

```
modules/notifications/
├── __init__.py        # MODULE_NAME, ENABLED, get_router()
├── routes.py          # Rule CRUD + test-fire + channel status
├── models.py          # Pydantic models
├── engine.py          # Rule matching + dispatch logic
└── .state
```

**No poller.** The engine fires reactively when an event is created — via PostgreSQL trigger or an API call that both stores the event AND evaluates rules. MVP uses a simple approach: `POST /api/notifications/fire` endpoint that the event creation code calls.

**Dashboard tab:** "Notifications" in sidebar, showing rules list + channel status.

---

## Data Model

### Migration: `migrations/006_notification_rules.sql`

```sql
-- Notification rules
CREATE TABLE IF NOT EXISTS notification_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT true,
    -- Match conditions (AND logic — all must match)
    match_source TEXT,          -- exact match on events.source (NULL = any)
    match_type TEXT,            -- exact match on events.type
    match_severity TEXT,        -- exact match: info, warn, critical
    match_tags TEXT[] DEFAULT '{}',  -- event must have ALL these tags
    -- Delivery
    channel TEXT NOT NULL,      -- 'telegram', 'ntfy', 'webhook'
    channel_config JSONB DEFAULT '{}',  -- channel-specific config
    -- Priority override
    priority TEXT DEFAULT 'normal',  -- low, normal, high, critical
    -- Cooldown
    cooldown_seconds INT DEFAULT 0,  -- 0 = no cooldown, fire every time
    -- Tracking
    last_fired_at TIMESTAMPTZ,
    fire_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_rules_enabled ON notification_rules (enabled);
CREATE INDEX idx_rules_source ON notification_rules (match_source);

-- Notification log (audit trail)
CREATE TABLE IF NOT EXISTS notification_log (
    id BIGSERIAL PRIMARY KEY,
    rule_id UUID REFERENCES notification_rules(id) ON DELETE SET NULL,
    event_id BIGINT,             -- REFERENCES events(id) — nullable, events may be deleted
    channel TEXT NOT NULL,
    status TEXT NOT NULL,        -- 'sent', 'failed', 'cooldown', 'no_match'
    message TEXT,
    error TEXT,
    fired_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_notif_log_fired ON notification_log (fired_at DESC);
CREATE INDEX idx_notif_log_rule ON notification_log (rule_id);
```

---

## Phase 1: Models (models.py)

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class RuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    match_source: Optional[str] = None
    match_type: Optional[str] = None
    match_severity: Optional[str] = None
    match_tags: list[str] = []
    channel: str  # 'telegram', 'ntfy', 'webhook'
    channel_config: dict = {}
    priority: str = 'normal'
    cooldown_seconds: int = 0

class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    match_source: Optional[str] = None
    match_type: Optional[str] = None
    match_severity: Optional[str] = None
    match_tags: Optional[list[str]] = None
    channel: Optional[str] = None
    channel_config: Optional[dict] = None
    priority: Optional[str] = None
    cooldown_seconds: Optional[int] = None

class RuleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    enabled: bool
    match_source: Optional[str] = None
    match_type: Optional[str] = None
    match_severity: Optional[str] = None
    match_tags: list[str]
    channel: str
    channel_config: dict
    priority: str
    cooldown_seconds: int
    last_fired_at: Optional[datetime] = None
    fire_count: int
    created_at: datetime
    updated_at: datetime

class FireRequest(BaseModel):
    event_id: int
    source: str
    type: str
    severity: str = 'info'
    title: str
    body: Optional[str] = None
    tags: list[str] = []

class FireResponse(BaseModel):
    event_id: int
    rules_matched: int
    notifications_sent: int
    results: list[dict]  # [{rule_id, rule_name, channel, status}]
```

---

## Phase 2: Engine (engine.py)

### Rule Matching

```python
def _rule_matches(rule: dict, event: dict) -> bool:
    """Check if a rule matches an event. All conditions must match (AND logic)."""
    if rule.get("match_source") and rule["match_source"] != event.get("source"):
        return False
    if rule.get("match_type") and rule["match_type"] != event.get("type"):
        return False
    if rule.get("match_severity") and rule["match_severity"] != event.get("severity"):
        return False
    if rule.get("match_tags"):
        event_tags = set(event.get("tags", []))
        required_tags = set(rule["match_tags"])
        if not required_tags.issubset(event_tags):
            return False
    return True
```

### Cooldown Check

```python
async def _check_cooldown(conn, rule: dict) -> bool:
    """Return True if the rule can fire (cooldown has elapsed)."""
    if not rule.get("cooldown_seconds") or rule["cooldown_seconds"] <= 0:
        return True
    if not rule.get("last_fired_at"):
        return True

    elapsed = (datetime.utcnow() - rule["last_fired_at"]).total_seconds()
    return elapsed >= rule["cooldown_seconds"]
```

### Channel Dispatch

```python
async def _dispatch(rule: dict, event: dict) -> dict:
    """Dispatch a notification to the configured channel. Return status dict."""
    channel = rule["channel"]
    config = rule.get("channel_config", {}) or {}
    title = event.get("title", "Notification")
    body = event.get("body", "")

    if channel == "telegram":
        return await _dispatch_telegram(config, title, body)
    elif channel == "ntfy":
        return await _dispatch_ntfy(config, title, body)
    elif channel == "webhook":
        return await _dispatch_webhook(config, event)
    else:
        return {"status": "failed", "error": f"Unknown channel: {channel}"}
```

### Telegram Dispatch

```python
async def _dispatch_telegram(config: dict, title: str, body: str) -> dict:
    """Send to Telegram channel."""
    chat_id = config.get("chat_id", "7521274750")  # default: Ali's home channel
    token = config.get("bot_token")

    if not token:
        # Fall back to env var
        from app.config import settings
        token = getattr(settings, 'telegram_bot_token', None)
    if not token:
        return {"status": "failed", "error": "No Telegram bot token configured"}

    message = f"*{title}*\n{body}" if body else title

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_notification": False,
            },
        )
        if resp.status_code == 200:
            return {"status": "sent"}
        return {"status": "failed", "error": f"Telegram API: {resp.status_code}"}
```

### ntfy Dispatch

```python
async def _dispatch_ntfy(config: dict, title: str, body: str) -> dict:
    """Send to ntfy topic."""
    topic = config.get("topic", "hermes-worker")
    server = config.get("server", "https://ntfy.notflix.no")
    priority = config.get("priority", "default")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{server}/{topic}",
            data=body.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": "loudspeaker",
            },
        )
        if resp.status_code == 200:
            return {"status": "sent"}
        return {"status": "failed", "error": f"ntfy API: {resp.status_code}"}
```

### Webhook Dispatch

```python
async def _dispatch_webhook(config: dict, event: dict) -> dict:
    """POST event to a webhook URL."""
    url = config.get("url")
    if not url:
        return {"status": "failed", "error": "No webhook URL configured"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=event)
        if resp.status_code < 500:
            return {"status": "sent"}
        return {"status": "failed", "error": f"Webhook: {resp.status_code}"}
```

### Main fire() function

```python
async def fire_event(event: dict) -> FireResponse:
    """Match event against rules and dispatch to matching channels."""
    import json
    from datetime import datetime
    from app.db import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        # Load all enabled rules
        rows = await conn.fetch(
            """SELECT * FROM notification_rules WHERE enabled = true
               ORDER BY priority DESC"""
        )

    rules_matched = 0
    notifications_sent = 0
    results = []

    async with pool.acquire() as conn:
        for row in rows:
            rule = dict(row)
            if not _rule_matches(rule, event):
                continue
            rules_matched += 1

            # Check cooldown
            if not await _check_cooldown(conn, rule):
                await conn.execute(
                    """INSERT INTO notification_log (rule_id, event_id, channel, status, message)
                       VALUES ($1, $2, $3, 'cooldown', 'In cooldown')""",
                    rule["id"], event.get("id"), rule["channel"],
                )
                results.append({"rule_id": rule["id"], "rule_name": rule["name"], "channel": rule["channel"], "status": "cooldown"})
                continue

            # Dispatch
            result = await _dispatch(rule, event)
            result["rule_id"] = rule["id"]
            result["rule_name"] = rule["name"]
            result["channel"] = rule["channel"]
            results.append(result)

            # Update rule tracking
            if result.get("status") == "sent":
                await conn.execute(
                    """UPDATE notification_rules
                       SET last_fired_at = now(), fire_count = fire_count + 1, updated_at = now()
                       WHERE id = $1""",
                    rule["id"],
                )
                notifications_sent += 1

            # Log
            await conn.execute(
                """INSERT INTO notification_log (rule_id, event_id, channel, status, message, error)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                rule["id"], event.get("id"), rule["channel"],
                result.get("status"), result.get("message", ""), result.get("error"),
            )

    return FireResponse(
        event_id=event.get("id", 0),
        rules_matched=rules_matched,
        notifications_sent=notifications_sent,
        results=results,
    )
```

---

## Phase 3: Routes (routes.py)

### Rule CRUD

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/notifications/rules` | Create rule |
| GET | `/api/notifications/rules` | List all rules |
| GET | `/api/notifications/rules/{id}` | Get rule by ID |
| PATCH | `/api/notifications/rules/{id}` | Update rule (partial) |
| DELETE | `/api/notifications/rules/{id}` | Delete rule |

Follow the standardized CRUD pattern from `app/core/events.py` — same auth flow, same asyncpg patterns, same `_from_row()` coercion.

### Rule CRUD implementation

```python
@router.post("/rules", response_model=RuleResponse, status_code=201)
async def create_rule(rule: RuleCreate, user: Annotated[AuthUser, Depends(_require_auth)]):
    """Create a notification rule. Requires admin role."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=403)
    
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO notification_rules (name, description, match_source, match_type,
               match_severity, match_tags, channel, channel_config, priority, cooldown_seconds)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               RETURNING *""",
            rule.name, rule.description, rule.match_source, rule.match_type,
            rule.match_severity, rule.match_tags, rule.channel,
            json.dumps(rule.channel_config), rule.priority, rule.cooldown_seconds,
        )
    return _rule_from_row(row)

@router.get("/rules", response_model=list[RuleResponse])
async def list_rules(user: Annotated[AuthUser, Depends(_require_auth)]):
    """List all notification rules."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM notification_rules ORDER BY priority DESC, created_at DESC")
    return [_rule_from_row(r) for r in rows]

@router.get("/rules/{rule_id}", response_model=RuleResponse)
async def get_rule(rule_id: str, user: Annotated[AuthUser, Depends(_require_auth)]):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM notification_rules WHERE id = $1", rule_id)
    if not row:
        raise HTTPException(status_code=404)
    return _rule_from_row(row)

@router.patch("/rules/{rule_id}", response_model=RuleResponse)
async def update_rule(rule_id: str, update: RuleUpdate, user: Annotated[AuthUser, Depends(_require_auth)]):
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=403)
    # Build SET clause dynamically from non-None fields
    # ... standard partial update pattern ...

@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, user: Annotated[AuthUser, Depends(_require_auth)]):
    if user.role not in ("admin",):
        raise HTTPException(status_code=403)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM notification_rules WHERE id = $1", rule_id)
    return {"ok": True}
```

### Fire Endpoint

```python
@router.post("/fire", response_model=FireResponse)
async def fire_notification(
    event: FireRequest,
    user: Annotated[AuthUser, Depends(_require_auth)],
):
    """Evaluate rules against an event and dispatch notifications."""
    if user.role not in ("admin", "agent"):
        raise HTTPException(status_code=403)

    from .engine import fire_event
    return await fire_event(event.model_dump())
```

### Log Endpoint

```python
@router.get("/log")
async def get_log(
    user: Annotated[AuthUser, Depends(_require_auth)],
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get recent notification delivery log."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT nl.*, nr.name as rule_name
               FROM notification_log nl
               LEFT JOIN notification_rules nr ON nl.rule_id = nr.id
               ORDER BY nl.fired_at DESC LIMIT $1""",
            limit,
        )
    return {"log": [_log_from_row(r) for r in rows], "count": len(rows)}
```

### Channel Status

```python
@router.get("/channels")
async def channel_status(user: Annotated[AuthUser, Depends(_require_auth)]):
    """Check which channels are configured and reachable."""
    from app.config import settings
    channels = {}

    # Telegram
    tg_token = getattr(settings, 'telegram_bot_token', None)
    channels["telegram"] = {"configured": bool(tg_token)}

    # ntfy — always reachable (local network)
    channels["ntfy"] = {"configured": bool(settings.ntfy_url)}

    return channels
```

### Seed Default Rules

```python
async def seed_default_rules():
    """Create sensible default notification rules if none exist."""
    pool = get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM notification_rules")
        if count > 0:
            return

    defaults = [
        {
            "name": "Critical alerts → Telegram",
            "match_severity": "critical",
            "channel": "telegram",
            "priority": "critical",
            "channel_config": {"chat_id": "7521274750"},
        },
        {
            "name": "Uptime breaking → ntfy",
            "match_source": "uptime_kuma",
            "match_tags": ["breaking"],
            "channel": "ntfy",
            "priority": "high",
            "channel_config": {"topic": "hermes-worker", "priority": "high"},
        },
        {
            "name": "New media content → Telegram",
            "match_source": "notflix",
            "match_type": "new_content",
            "channel": "telegram",
            "priority": "low",
            "cooldown_seconds": 3600,  # max 1 per hour
        },
    ]

    async with pool.acquire() as conn:
        for d in defaults:
            await conn.execute(
                """INSERT INTO notification_rules (name, description, match_source,
                   match_type, match_severity, match_tags, channel, channel_config, priority, cooldown_seconds)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                d["name"], "", d.get("match_source"), d.get("match_type"),
                d.get("match_severity"), d.get("match_tags", []),
                d["channel"], json.dumps(d.get("channel_config", {})),
                d.get("priority", "normal"), d.get("cooldown_seconds", 0),
            )
```

**Call `seed_default_rules()` in the module's `__init__.py` or in the lifespan startup.**

---

## Phase 4: Dashboard UI

### HTML section (static/index.html)

```html
<!-- Nav button -->
<button class="..." onclick="switchTab('notifications')">Notifications</button>

<!-- Page -->
<section id="page-notifications" class="page" aria-label="Notifications">
  <div class="filter-bar" style="margin-bottom:12px;">
    <span style="flex:1;"></span>
    <button class="btn btn-sm btn-primary" onclick="window.toggleNewRuleForm()">+ New Rule</button>
  </div>

  <!-- New rule form (hidden by default) -->
  <div id="notif-rule-form" style="display:none;margin-bottom:14px;">
    <!-- Form with: name, source, severity, channel dropdown, cooldown -->
  </div>

  <!-- Rules list -->
  <h3>Rules</h3>
  <div id="notif-rules-list"><p class="loading">Loading…</p></div>

  <!-- Delivery log -->
  <h3 style="margin-top:20px;">Recent Deliveries</h3>
  <div id="notif-log"><p class="loading">Loading…</p></div>
</section>
```

### JS functions

```javascript
async function loadNotificationsPage() {
  try {
    var rules = await api('/api/notifications/rules');
    renderNotificationRules(rules);
  } catch(e) {
    document.getElementById('notif-rules-list').innerHTML = '<p class="error">Failed to load</p>';
  }
  try {
    var log = await api('/api/notifications/log?limit=30');
    renderNotificationLog(log.log);
  } catch(e) {}
}

function renderNotificationRules(rules) {
  if (!rules || rules.length === 0) {
    document.getElementById('notif-rules-list').innerHTML = '<p class="empty">No rules defined. Create one to route notifications.</p>';
    return;
  }
  var html = '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Match</th><th>Channel</th><th>Fired</th><th></th></tr></thead><tbody>';
  rules.forEach(function(r) {
    var match = [];
    if (r.match_source) match.push('source=' + r.match_source);
    if (r.match_severity) match.push('severity=' + r.match_severity);
    if (r.match_tags && r.match_tags.length) match.push('tags=[' + r.match_tags.join(',') + ']');
    var label = r.channel === 'telegram' ? '📱 Telegram' : r.channel === 'ntfy' ? '🔔 ntfy' : r.channel;
    html += '<tr>' +
      '<td style="font-weight:500;">' + escHtml(r.name) + '</td>' +
      '<td style="font-size:12px;">' + escHtml(match.join(', ') || 'any') + '</td>' +
      '<td>' + label + '</td>' +
      '<td class="mono" style="font-size:11px;">' + (r.fire_count || 0) + '</td>' +
      '<td>' +
        '<button class="btn btn-sm btn-secondary" onclick="window.toggleRule(\'' + r.id + '\')">' + (r.enabled ? 'Disable' : 'Enable') + '</button>' +
        '<button class="btn btn-sm btn-danger" onclick="window.deleteRule(\'' + r.id + '\')">×</button>' +
      '</td>' +
      '</tr>';
  });
  html += '</tbody></table></div>';
  document.getElementById('notif-rules-list').innerHTML = html;
}

// Export ALL onclick functions to window
window.loadNotificationsPage = loadNotificationsPage;
window.toggleNewRuleForm = toggleNewRuleForm;
window.submitNewRule = submitNewRule;
window.toggleRule = toggleRule;
window.deleteRule = deleteRule;
```

---

## Phase 5: Integration — Fire on Event Creation

Hook the notification engine into the event creation flow. In `app/core/events.py`, after inserting an event, check if it should fire notifications:

```python
# After INSERT INTO events in create_event:
try:
    from modules.notifications.engine import fire_event
    await fire_event({
        "id": event_id,
        "source": event.source,
        "type": event.type,
        "severity": event.severity,
        "title": event.title,
        "body": event.body,
        "tags": event.tags or [],
    })
except ImportError:
    pass  # Module not enabled
except Exception as e:
    logger.warning(f"Notification dispatch failed: {e}")
```

This makes notification routing automatic — any event that matches a rule gets dispatched.

---

## Tests (tests/test_notifications.py)

```python
# Test cases:
# 1. test_create_rule — POST /rules → 201
# 2. test_list_rules — GET /rules → array
# 3. test_get_rule — GET /rules/{id} → single rule
# 4. test_update_rule — PATCH /rules/{id} → partial update
# 5. test_delete_rule — DELETE /rules/{id} → 200
# 6. test_rule_matching_source — rule with match_source matches event with same source
# 7. test_rule_matching_severity — rule matches correct severity
# 8. test_rule_matching_tags — rule with tags only fires on matching tags
# 9. test_rule_non_matching — event that doesn't match should not fire
# 10. test_rule_disabled — disabled rule should not fire
# 11. test_rule_cooldown — cooldown prevents immediate re-fire
# 12. test_fire_endpoint — POST /fire returns results
# 13. test_seed_defaults — default rules created on empty DB
# 14. test_unauthorized — 401 without auth
# 15. test_forbidden_read_role — read role can't create rules
```

---

## Acceptance Criteria

- [ ] Migration 006 creates notification_rules + notification_log tables
- [ ] Rule CRUD fully functional (create, read, update, delete)
- [ ] Engine correctly matches events to rules (AND logic)
- [ ] Cooldown prevents rapid re-fire
- [ ] Telegram dispatch works (uses bot token from env)
- [ ] ntfy dispatch works (uses existing ntfy config)
- [ ] Webhook dispatch works
- [ ] `POST /api/notifications/fire` evaluates rules and dispatches
- [ ] Default rules seeded on first module load
- [ ] Event creation in core triggers notification evaluation
- [ ] Dashboard tab shows rules list + delivery log
- [ ] 15+ tests passing
- [ ] Docker build + force-recreate picks up changes

---

## Known Pitfalls

| # | Pitfall | Prevention |
|---|---------|------------|
| 1 | Telegram bot token not in config | Check `settings.telegram_bot_token` — it's in muninn .env but may not be in LamaDB .env |
| 2 | Telegram Markdown escaping | Strip `*` from user-generated titles to avoid parse errors |
| 3 | `fire_event` called inside DB transaction | Use separate pool acquisition, don't call from within a transaction |
| 4 | Circular import (events.py → notifications engine) | Use late import inside the function, wrapped in try/except ImportError |
| 5 | PATCH endpoint SQL injection | Build SET clause with parameterized queries, not string interpolation |
| 6 | JSONB channel_config coercion | json.dumps on insert, json.loads on read |
| 7 | Cooldown uses server time | `datetime.utcnow()` — fine for MVP, no timezone issues |
| 8 | onclick handlers not on `window` | Export ALL new functions: toggleNewRuleForm, submitNewRule, toggleRule, deleteRule |
| 9 | Default seed idempotency | Check `COUNT(*) > 0` before seeding |
| 10 | Event `tags` field is TEXT[] | asyncpg auto-converts Python lists, no json.dumps needed |
