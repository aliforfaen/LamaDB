# Hermes API — Analytics & Statistics Endpoints

> **Discovered:** 2026-06-07 | **Hermes version:** 0.16.0 (desktop release 2026.6.5)
> **Auth:** `X-Hermes-Session-Token: <token>` (extracted from dashboard HTML `__HERMES_SESSION_TOKEN__`)
> **Dashboard:** `http://dev-vm:9119` | **Gateway health:** `http://dev-vm:8643/health`

> ⚠️ The docs in `hermes-api.html` are stale — the API shifted on desktop release.
> All endpoints are at `/api/` (not `/api/v1/`).

---

## Core Stats Endpoints

### `GET /api/status`
Server status + gateway health + platform connectivity.

```json
{
  "version": "0.16.0",
  "release_date": "2026.6.5",
  "hermes_home": "/home/messhias/.hermes/profiles/muninn",
  "config_version": 27,
  "latest_config_version": 27,
  "gateway_running": true,
  "gateway_pid": 862639,
  "gateway_state": "running",
  "gateway_platforms": {
    "telegram": { "state": "connected", "updated_at": "2026-06-06T21:09:54" },
    "api_server": { "state": "connected", "updated_at": "2026-06-06T21:09:54" }
  },
  "active_sessions": 0,
  "auth_required": false,
  "auth_providers": ["basic"]
}
```

### `GET /api/sessions/stats`
Aggregate session + message counts, broken down by source.

```json
{
  "total": 186,
  "active_store": 186,
  "archived": 0,
  "messages": 9937,
  "by_source": {
    "tui": 17,
    "telegram": 12,
    "cli": 9,
    "cron": 106
  }
}
```

### `GET /api/system/stats`
Host system metrics — CPU, memory, disk, process info.

```json
{
  "os": "Linux",
  "hostname": "dev-vm",
  "hermes_version": "0.16.0",
  "cpu_count": 8,
  "memory": { "total": 8325505024, "available": 5348786176, "used": 2976718848, "percent": 35.8 },
  "disk": { "total": 103240134656, "used": 73921392640, "free": 24577933312, "percent": 75.0 },
  "cpu_percent": 1.3,
  "load_avg": [0.03, 0.04, 0.05],
  "uptime_seconds": 739509,
  "process": { "pid": 843611, "rss": 291028992, "num_threads": 12 }
}
```

### `GET /api/sessions/empty/count`
Count of sessions with no messages.

```json
{ "count": 2 }
```

---

## Session Data (Token/Cost Analytics)

### `GET /api/sessions?limit=N`
Returns session list with per-session token usage and cost tracking.

**Key fields per session:**
| Field | Type | Description |
|---|---|---|
| `id` | string | Session ID (timestamp-based) |
| `source` | string | `tui`, `telegram`, `cli`, `cron` |
| `model` | string | Model used (e.g. `deepseek-v4-pro`) |
| `message_count` | int | Messages in session |
| `tool_call_count` | int | Tool invocations |
| `input_tokens` | int | Input tokens consumed |
| `output_tokens` | int | Output tokens generated |
| `cache_read_tokens` | int | Tokens read from cache |
| `cache_write_tokens` | int | Tokens written to cache |
| `reasoning_tokens` | int | Reasoning/chain-of-thought tokens |
| `estimated_cost_usd` | float | Estimated cost |
| `actual_cost_usd` | float/null | Actual cost (if available) |
| `cost_status` | string | `unknown`, `billed`, etc. |
| `billing_provider` | string | Provider handling billing |
| `api_call_count` | int | API calls made |
| `started_at` | float | Unix timestamp |
| `ended_at` | float/null | Unix timestamp |
| `end_reason` | string | `tui_close`, etc. |
| `title` | string/null | Auto-generated session title |
| `preview` | string | First message preview |
| `rewind_count` | int | Times conversation was rewound |
| `archived` | bool | Whether session is archived |
| `is_active` | bool | Currently active |

---

## Model & Provider Analytics

### `GET /api/model/info`
Current model configuration and capabilities.

```json
{
  "model": "deepseek-v4-pro",
  "provider": "opencode-go",
  "auto_context_length": 1000000,
  "effective_context_length": 1000000,
  "capabilities": {
    "supports_tools": true,
    "supports_vision": false,
    "supports_reasoning": true,
    "context_window": 1000000,
    "max_output_tokens": 384000,
    "model_family": "deepseek-thinking"
  }
}
```

### `GET /api/model/options`
All available providers and their models.

```json
{
  "providers": [
    {
      "slug": "opencode-go",
      "name": "OpenCode Go",
      "is_current": true,
      "models": ["minimax-m3", "deepseek-v4-pro", "mimo-v2.5-pro", ...],
      "total_models": 18
    }
  ]
}
```

### `GET /api/model/auxiliary`
Auxiliary model assignments (vision, compression, web extract, etc.).

```json
{
  "tasks": [
    { "task": "vision", "provider": "openrouter", "model": "google/gemini-3-flash-preview" },
    { "task": "web_extract", "provider": "openrouter", "model": "google/gemini-3-flash-preview" },
    { "task": "compression", "provider": "openrouter", "model": "google/gemini-3-flash-preview" },
    { "task": "title_generation", "provider": "auto", "model": "" }
  ]
}
```

### `GET /api/credentials/pool`
API key pool status per provider — request counts, key health.

```json
{
  "providers": [
    {
      "provider": "opencode-go",
      "entries": [
        { "id": "4a6666", "label": "OPENCODE_GO_API_KEY", "last_status": "ok", "request_count": 0 }
      ]
    }
  ]
}
```

---

## Infrastructure Analytics

### `GET /api/profiles`
Agent profiles with skill counts and gateway status.

```json
{
  "profiles": [
    {
      "name": "muninn",
      "model": "deepseek-v4-pro",
      "provider": "opencode-go",
      "skill_count": 108,
      "gateway_running": true
    }
  ]
}
```

### `GET /api/profiles/active`
Currently active profile.

```json
{ "active": "muninn", "current": "muninn" }
```

### `GET /api/skills`
Installed skills with enable/disable state.

### `GET /api/tools/toolsets`
Available toolsets with enabled/configured/available state. 27 toolsets discovered.

### `GET /api/mcp/servers`
MCP server connections (stdio + http transports).

### `GET /api/mcp/catalog`
Available MCP servers in the catalog (installable).

### `GET /api/memory`
Memory provider status (hindsight, holographic, honcho, byterover).

### `GET /api/curator`
Session curator config — auto-archival settings.

```json
{
  "enabled": true,
  "paused": false,
  "interval_hours": 168,
  "last_run_at": "2026-06-05T17:04:26",
  "stale_after_days": 30,
  "archive_after_days": 90
}
```

### `GET /api/messaging/platforms`
Platform connectivity (Telegram, API server, etc.).

### `GET /api/portal`
Portal/subscription status and feature availability.

### `GET /api/ops/hooks`
Registered lifecycle hooks. Valid events:
- `on_session_start`, `on_session_end`, `on_session_finalize`, `on_session_reset`
- `pre_llm_call`, `post_llm_call`, `pre_tool_call`, `post_tool_call`
- `pre_api_request`, `post_api_request`, `api_request_error`
- `pre_approval_request`, `post_approval_response`
- `pre_gateway_dispatch`
- `subagent_start`, `subagent_stop`
- `transform_llm_output`, `transform_terminal_output`, `transform_tool_result`

---

## Summary: What's Useful for LamaDB Polling

| Endpoint | Data | LamaDB Use |
|---|---|---|
| `/api/status` | Version, gateway health, platform state | Health events, uptime tracking |
| `/api/sessions/stats` | Total sessions/messages, by_source | Dashboard ticker, RSS summaries |
| `/api/system/stats` | CPU/memory/disk/process | System health events |
| `/api/sessions?limit=N` | Per-session token usage, cost, tool calls | Token analytics documents, cost tracking |
| `/api/model/info` | Current model, capabilities | Config document |
| `/api/credentials/pool` | Key health, request counts | Provider health events |
| `/api/profiles` | Agent profiles, skill counts | Agent inventory documents |
| `/api/tools/toolsets` | Tool availability | Capability tracking |
| `/api/mcp/servers` | MCP connections | Integration health |
| `/api/curator` | Auto-archival status | Maintenance events |
