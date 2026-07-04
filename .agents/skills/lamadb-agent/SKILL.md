# LamaDB Agent

## When to Use

You are an agent operating inside LamaDB's agent infrastructure. Reach for these tools when you need to:

- **Log progress / status** as you work ("log that I started X", "record a warning")
- **Send messages** to other agents ("tell Muninn the build is green", "ping the watcher")
- **Read your task inbox** from the agent board
- **Look up context** in the wiki (Obsidian vault, synced via CouchDB LiveSync)
- **Capture scratchpad notes** (quick durable notes that show up in wiki search)

**Don't use these for:** long-form documents (use `agent_documents`), full task tracking (use the kanban skill), or secrets (use `lamadb-admin`).

## Connection

- Worker endpoint (recommended): `http://lamadb:8000/mcp/worker`
- Admin endpoint: `http://lamadb:8000/mcp/admin`
- Auth header: `Authorization: Bearer <api_key>`
- Protocol: JSON-RPC 2.0
- `user_id` is injected from the API key — don't pass it

## Tools

### `agent_events` — event bus

The event bus is the durable, queryable log of things-that-happened. It also drives the notification system: events with `severity="critical"` are dispatched to ntfy (push notifications to the phone).

| Action | Purpose | Required params | Optional params |
|--------|---------|-----------------|-----------------|
| `create` | Log a new event | `source`, `event_type`, `title` | `severity` (default `info`), `body`, `metadata`, `tags` |
| `list` | Read recent events | — | `source`, `event_type`, `severity`, `limit` (default 50) |

**Severity levels:** `info` (default, no notifications), `warning` (logged, no push), `critical` (logged AND pushes via ntfy to the operator's phone — use sparingly).

**`event_type`:** the MCP schema parameter name. Common values: `progress`, `error`, `complete`, `blocker`, `note`, `scratchpad_created`. (Renamed from `type_` to avoid the Python builtin collision.)

**`source`:** should be your agent name (e.g. `muninn`, `noodle`, `claude-flash`). This is what shows up in the dashboard's "Recent System Errors" widget and the source filter dropdown.

### `agent_messages` — agent-to-agent inbox

| Action | Purpose | Required params | Optional params |
|--------|---------|-----------------|-----------------|
| `list_tasks` | Read open tasks/messages in the agent board | — | `status`, `priority`, `limit` (default 50) |
| `send` | Send a message to another agent's inbox | `to_agent`, `subject` | `body`, `message_type`, `metadata` |

**`to_agent`:** the recipient's user name (string). The `from_agent` is hardcoded to `mcp` in the current implementation — the message is attributed to "mcp" regardless of which API key sent it. Don't rely on `from_agent` for identity.

**`message_type`:** categorizes the message. Defaults to `info`. Other observed values: `task`, `alert`, `query`.

**`list_tasks` vs `list` on `agent_events`:** these are different tables. `list_tasks` returns rows from `agent_tasks` (work items in the agent board). `agent_events list` returns rows from `events` (durable log). Use the right one for the question you're asking.

### `agent_wiki` — Obsidian vault + scratchpad

The wiki is an Obsidian vault synced from CouchDB (via LiveSync V2 with HKDF/AES-GCM decryption). Pages are stored as documents with `source_type='wiki'`.

| Action | Purpose | Required params | Optional params |
|--------|---------|-----------------|-----------------|
| `search` | pg_trgm search over wiki page titles + content | `q` | `limit` (default 20) |
| `scratch` | Save a durable note to the documents table | `content` | `title` (default `"Scratchpad"`) |

**Scratchpad behavior:** `scratch` creates a document with `source_type='scratchpad'` AND fires a `wiki.scratchpad_created` event so it shows up in the ticker. The note is searchable via `agent_documents` and `agent_wiki`.

**`search` is keyword-based (pg_trgm), not semantic.** It works best on title and exact-term matches. For natural-language search, use `agent_documents` (which has vector embeddings).

## Workflows

### Log a progress event

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_events",
  "arguments":{
    "action":"create",
    "source":"<your-agent-name>",
    "event_type":"progress",
    "title":"Started investigating /api/search latency",
    "body":"Pulled slow query log, suspecting missing index on events.created_at",
    "tags":["perf","search"]
  }}}
```

### Log a critical alert (push to phone)

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_events",
  "arguments":{
    "action":"create",
    "source":"<your-agent-name>",
    "event_type":"error",
    "severity":"critical",
    "title":"LamaDB API returning 500s on /mcp/admin",
    "body":"Error rate 100% for last 3 minutes. pgsql pool exhausted.",
    "metadata":{"endpoint":"/mcp/admin","error_rate":1.0},
    "tags":["outage","mcp"]
  }}}
```

**Reserve `critical` for things that need a human NOW.** Every critical event pings the phone. If you fire 5 in a row from a runaway loop, you're waking the operator at 3am for nothing.

### Send a message to another agent

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_messages",
  "arguments":{
    "action":"send",
    "to_agent":"muninn",
    "subject":"Wiki sync stuck at seq 12345",
    "body":"Last 3 retries failed with 504 from CouchDB. /api/wiki/sync-state confirms stuck. Worth checking CouchDB health?",
    "message_type":"alert"
  }}}
```

### Check your message inbox

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_messages",
  "arguments":{
    "action":"list_tasks",
    "status":"open",
    "priority":"high",
    "limit":20
  }}}
```

### Look something up in the wiki

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_wiki",
  "arguments":{
    "action":"search",
    "q":"deployment runbook",
    "limit":10
  }}}
```

### Drop a quick note to yourself

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_wiki",
  "arguments":{
    "action":"scratch",
    "title":"Hypothesis: HNSW index not used for queries under 5 rows",
    "content":"Saw 800ms latency on a search returning 3 docs. Plan was seq scan. Maybe Postgres skipping HNSW below threshold. Try SET enable_seqscan=off to confirm."
  }}}
```

## Gotchas

- **`event_type` not `type`.** The MCP schema for `create` event has the parameter named `event_type` (renamed from `type_` to avoid shadowing the Python builtin). Easy to mistype — don't write `type` or `type_`, write `event_type`.
- **`source` is your agent name string, not a UUID.** It's a free-form text column. Use something stable and recognizable — it shows up in the dashboard's "Recent System Errors" widget and the source filter dropdown.
- **`severity="critical"` triggers a phone notification.** Use it for things that genuinely need human attention right now. Routine progress is `info`. Concerns that should be visible but don't need a push are `warning`.
- **`send_agent_message` always sets `from_agent='mcp'`.** Don't trust the `from_agent` field in the response — it's a constant. To identify who sent the message, look at the API key's audit log on the server side.
- **`list_tasks` ≠ `events list`.** Different tables (`agent_tasks` vs `events`). Pick the right one for the question.
- **Wiki search is keyword-based (pg_trgm), not semantic.** "How do I deploy LamaDB?" won't find "deployment runbook" — try the actual terms. For semantic search across documents, use `agent_documents` (see lamadb-docs skill).
- **Scratchpad creates a document AND an event.** Two writes per `scratch` call. The event title is `"Scratchpad: <title>"`, the body is the first 200 chars of content. Useful for "what did I write recently" via `agent_events list source=wiki event_type=scratchpad_created`.
- **No `update` on events or messages.** Events are append-only. Messages you sent can't be edited or recalled — the only way to "correct" is to send a follow-up.
- **`metadata` must be a JSON object (or omitted).** Passing a string, number, or array will fail Pydantic validation. The dispatcher serializes it via `json.dumps` after the handler coerces the dict.
- **JSON-RPC result wrapping:** `tools/call` returns `result.content[0].text` as a JSON string. Parse that string. The outer envelope is JSON-RPC metadata.
- **Event `id` is a bigint, not a UUID.** The `create` response returns `id` as an integer (BIGSERIAL from the events table). Don't expect a UUID format.
- **Default `limit` on `list` is 50 events.** If you need more, set `limit` explicitly. The schema accepts any positive integer.
- **No pagination cursors.** Both `list` and `list_tasks` do `ORDER BY ts DESC LIMIT N`. If the latest 50 events aren't what you need, narrow with `source`/`severity`/`event_type` filters.
