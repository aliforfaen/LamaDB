# LamaDB Documents

## When to Use

You need to interact with the **core documents table** — the universal storage layer for structured and unstructured data in LamaDB. Reach for these tools when the user asks you to:

- Search the knowledge base ("find docs about X", "what do we know about Y?")
- Store results ("save this", "remember that", "log it as a document")
- Read a specific document by ID
- Update an existing document
- Pull the full API reference when you need it

The documents table is the canonical place for free-form content: notes, agent outputs, research results, anything that doesn't fit the kanban/event/wiki models.

**Don't use documents for:** kanban tasks (use lamadb-kanban), short-lived progress logs (use `agent_events`), wiki page search (use `agent_wiki`).

## Connection

- Worker endpoint: `http://lamadb:8000/mcp/worker`
- Admin endpoint: `http://lamadb:8000/mcp/admin`
- Auth header: `Authorization: Bearer <api_key>`
- Protocol: JSON-RPC 2.0

## Document model

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | Auto-generated on create |
| `source_type` | string | **You set this.** Describes where the doc came from. Conventional values: `wiki`, `scratchpad`, `agent_feed`, `kanban_export`, your own agent name |
| `title` | string | Required, indexed (pg_trgm similarity) |
| `content` | string | Indexed (pg_trgm similarity), up to 500 chars returned by `search` |
| `tags` | string[] | GIN-indexed, exact-match filterable via REST `?tag=foo` |
| `metadata` | JSONB | Free-form structured data |
| `embedding` | vector(384) | Auto-generated on create/update via sentence-transformers (all-MiniLM-L6-v2). First call takes ~5-10s while the model loads |
| `created_at`, `updated_at` | timestamptz | Auto-managed |

## Tools

### `agent_documents` — document CRUD

| Action | Purpose | Required params | Optional params |
|--------|---------|-----------------|-----------------|
| `search` | pg_trgm similarity search on title + content | `q` | `limit` (default 10) |
| `get` | Fetch one doc with its outgoing links | `id` | — |
| `create` | Insert a new document (auto-embeds) | `title`, `source_type` | `content`, `tags`, `metadata` |
| `update` | Modify fields of an existing doc (re-embeds if title/content changed) | `id` | `title`, `source_type`, `content`, `tags`, `metadata` |

**`search` is keyword-based (pg_trgm), not semantic.** It computes `similarity(title, $1) + similarity(content, $1)` and ranks. Natural language queries work OK but exact terms work better. The `embedding` column is for vector search via the REST `/api/search` endpoint — that semantic path is not exposed through MCP.

**`get` includes links.** The response includes a `links` array with `target_id`, `target_title`, `link_type`, and `context` for every outgoing `document_links` row. Useful for traversing the doc graph.

**`create` triggers async embedding.** The handler returns immediately after the INSERT; a fire-and-forget task generates the 384-dim vector. You don't wait for it.

**`update` only changes provided fields.** All params except `id` are optional. Passing `null` or omitting a field leaves it untouched. The handler returns `{"error": "No fields to update"}` if you pass only `id`.

### `lamadb_docs` — full API reference (passthrough tool)

This is **not** a consolidated dispatcher — there's no `action` parameter. The `topic` parameter selects which doc to load.

| Param | Purpose | Default |
|-------|---------|---------|
| `topic` | Which doc to return | `"api"` |

Currently the only supported topic is `api`, which returns the full contents of `AGENTS_API.md` (the agent-facing API reference). Use it when you need exact endpoint shapes, field names, or auth model details.

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"lamadb_docs",
  "arguments":{"topic":"api"}}}
```

## Workflows

### Search the knowledge base

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_documents",
  "arguments":{
    "action":"search",
    "q":"postgres connection pool tuning",
    "limit":5
  }}}
```

The response is `{"results": [...], "count": N, "query": "..."}`. Each result is truncated to 500 chars of content; use `get` with the ID to fetch the full text.

### Fetch a full document

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_documents",
  "arguments":{"action":"get","id":"<uuid>"}}}
```

The response includes the doc plus a `links` array. If the ID is wrong, you get `{"error": "Document <id> not found"}` — no exception.

### Save research results

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_documents",
  "arguments":{
    "action":"create",
    "title":"HNSW index skip threshold investigation (2026-06-17)",
    "source_type":"muninn",
    "content":"Reproduced 800ms latency on 3-doc search. Confirmed via EXPLAIN ANALYZE that pg chose seq scan over HNSW. With SET enable_seqscan=off, query dropped to 12ms. Threshold appears to be ~5 rows. Workaround: force index for small queries, or accept the seq scan as cheaper for tiny result sets.",
    "tags":["perf","postgres","search","investigation"],
    "metadata":{
      "related_issue":"task-uuid-1234",
      "query_count":3,
      "mitigation":"SET enable_seqscan=off"
    }
  }}}
```

### Update a document

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"agent_documents",
  "arguments":{
    "action":"update",
    "id":"<uuid>",
    "tags":["perf","postgres","search","investigation","resolved"],
    "metadata":{"resolution":"seq scan is correct for small result sets"}
  }}}
```

Only `tags` and `metadata` change here — title and content are left alone, so no re-embedding is triggered.

### Get the full API reference

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"lamadb_docs",
  "arguments":{"topic":"api"}}}
```

The `content` field in the response is the entire `AGENTS_API.md` file as a string. It's large — use this when you genuinely need the reference, not as a routine "what does this do" lookup.

## Gotchas

- **`id` is a UUID string.** All `get`/`update` paths need it. Search results include the ID in each result row.
- **`source_type` is your responsibility to set meaningfully.** The handler accepts any string. The dashboard uses it as a filter facet, and semantic search by vector uses it implicitly. Conventional values: `wiki`, `scratchpad`, `agent_feed`, your agent name. Don't use `"unknown"` or `""` — you'll never find it later.
- **`tags` is a string array, not comma-separated.** Pass `["perf","search"]`, not `"perf,search"`. The GIN index requires the array form.
- **`metadata` must be a JSON object.** Strings, numbers, and arrays fail validation. Pass `{"key":"value"}` or omit.
- **`update` requires at least one field besides `id`.** Calling `update` with only `id` returns `{"error": "No fields to update"}` — not an exception, just an error dict.
- **`search` returns truncated content (500 chars).** Use `get` for the full text. Don't try to extract details from a search result's content field.
- **`search` is pg_trgm, not semantic.** "How do I tune Postgres?" won't necessarily find "postgres performance tuning" unless the query terms overlap. The vector embedding exists in the column but is not queried through MCP — for semantic search use the REST endpoint `/api/search`.
- **Embeddings are fire-and-forget.** `create` returns before the embedding is generated. The first call after a container start takes 5-10s (model load) and happens out-of-band. If you create a doc and immediately search by vector, it may not appear yet.
- **`update` re-embeds if title OR content changed.** Re-embedding is also fire-and-forget. Don't poll for it.
- **No `delete` action.** Documents can't be removed via MCP. If you need to, use the REST API or ask a human.
- **`lamadb_docs` is a passthrough tool, not consolidated.** There's no `action` parameter on it. The only parameter is `topic`. The schema has `topic` default `"api"`.
- **`lamadb_docs` returns the doc as a `content` string field in JSON.** It can be large. If the response is truncated, the tool itself doesn't paginate — the underlying file is what it is.
- **JSON-RPC result wrapping:** `tools/call` returns `result.content[0].text` as a JSON string. Parse that string. For `lamadb_docs`, you'll need to parse the outer envelope, then parse the inner JSON, then read the `content` field — it's three layers of JSON.
- **The `metadata` field in search results is NOT returned.** `search` returns `id`, `source_type`, `title`, truncated `content`, `tags`, `score`, `created_at` — but not `metadata`. Use `get` to see metadata.
- **No pagination on `search`.** Returns at most `limit` rows (default 10). If you need the next page, narrow the query.
