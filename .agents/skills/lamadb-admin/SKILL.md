# LamaDB Admin — Secrets

## When to Use

You need to access a **secret** stored in LamaDB's secrets vault — API keys, tokens, passwords, certificates, or generic credentials. Reach for these tools when the user asks you to:

- List what's in the vault ("what secrets do we have for service X?")
- Reveal a secret value ("give me the API key for service Y")
- Request access to a secret you can see but can't decrypt
- Inspect metadata for a specific secret

**This is admin-only.** The `admin_secrets` tool is `toolset="admin"`, so it lives on `/mcp/admin` only. The worker endpoint (`/mcp/worker`) does **not** expose it. If you're running as a worker agent and call this tool, you'll get a "Tool not available on this endpoint" error.

**Audit logged.** Every `reveal` call is recorded. Every `request_access` is recorded. The vault knows who looked at what.

## Connection

- Admin endpoint: `http://lamadb:8000/mcp/admin` (the only place `admin_secrets` is available)
- Auth header: `Authorization: Bearer <admin_api_key>` (or an agent key with `secrets` scope and admin-equivalent grants)
- Protocol: JSON-RPC 2.0
- `user_id` is injected from the API key

## Secret model

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | Auto-generated |
| `name` | string | Human-readable name |
| `service` | string | Service the secret is for (e.g. `github`, `stripe`, `lamadb-postgres`) |
| `description` | string | Optional free-form |
| `secret_type` | enum | `api_key`, `token`, `password`, `certificate`, `generic` |
| `priority` | enum | `low`, `medium`, `high`, `critical` |
| `tags` | string[] | GIN-indexed |
| `owner_user_id` | UUID | User who owns the secret (can always reveal) |
| `owner_group_id` | UUID | Group that owns the secret (all members can reveal) |
| `expires_at` | timestamptz | Optional expiry |
| `last_revealed_at` | timestamptz | Updated on every successful reveal |
| `encrypted_value` | bytea | The actual encrypted secret |
| `encrypted_extra_1`, `encrypted_extra_2` | bytea | Optional side-channel data (e.g. cert + key) |

## Access model

Three tiers, checked in order during `reveal`:

1. **Admin role** — any admin user can reveal any secret
2. **Direct ownership** — `owner_user_id` matches your user_id
3. **Group ownership** — you're in the group that owns the secret (`owner_group_id`)
4. **Explicit user grant** — there's a row in `secret_access` with `grantee_type='user'`, `grantee_id=<your user_id>`
5. **Explicit group grant** — there's a row in `secret_access` with `grantee_type='group'`, and you're in that group

`list` shows you *all* secrets with an `accessible: true|false` flag for each. You can see metadata for everything; you can only `reveal` the ones you have access to.

## Tools

### `admin_secrets` — secrets vault

| Action | Purpose | Required params | Optional params |
|--------|---------|-----------------|-----------------|
| `list` | List visible secrets (metadata only) | — | `service`, `secret_type`, `tag`, `accessible` (bool) |
| `metadata` | Get full metadata for one secret | `secret_id` | — |
| `reveal` | Decrypt and return a secret value | `secret_id` | — |
| `request_access` | Submit a request to gain reveal access | `secret_id`, `reason` | — |

**Note the public param name:** the public MCP API exposes the secret identifier as `secret_id`. Internally the handlers accept `id`; the consolidated dispatcher renames it. You only ever write `secret_id` in JSON-RPC arguments.

## Workflows

### Discover what's available

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"admin_secrets",
  "arguments":{"action":"list"}}}
```

Returns an array of secret objects with `id`, `name`, `service`, `secret_type`, `tags`, owner info, and an `accessible: bool` flag.

Filter to a specific service:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"admin_secrets",
  "arguments":{"action":"list","service":"github"}}}
```

Filter to only secrets you can actually reveal:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"admin_secrets",
  "arguments":{"action":"list","accessible":true}}}
```

### Get full metadata for a secret

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"admin_secrets",
  "arguments":{"action":"metadata","secret_id":"<uuid>"}}}
```

Returns the full row including `description`, owner IDs, expiry, `last_revealed_at`, `created_at`, `updated_at`. Throws `ValueError` (returned as JSON-RPC error) if the secret doesn't exist. **Does not decrypt the value.**

### Reveal a secret you have access to

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"admin_secrets",
  "arguments":{"action":"reveal","secret_id":"<uuid>"}}}
```

Returns `{"id", "value", "extra_1", "extra_2", "secret_type"}`. The `value` is the decrypted plaintext. `extra_1`/`extra_2` are populated for secrets with side-channel data (e.g. certificates where you need the cert AND the key).

**Audit:** every reveal updates `last_revealed_at` on the row. There is a separate audit log per reveal. Don't reveal secrets you don't need.

**Errors:**
- `Secret '<id>' not found` — bad UUID or already deleted
- `You do not have access to reveal secret '<name>'. Use request_secret_access to ask for permission.` — see next workflow

### Request access to a secret

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
  "name":"admin_secrets",
  "arguments":{
    "action":"request_access",
    "secret_id":"<uuid>",
    "reason":"Need to rotate the Stripe webhook signing key. Current key in prod may be compromised (see task #4321)."
  }}}
```

Returns `{"status": "pending", "request_id": <uuid>, "message": "..."}`. An admin reviews the request and either grants (creating a row in `secret_access`) or denies it.

**Duplicate requests are no-ops.** If you already have a pending request for the same secret, the response is `{"status": "already_pending", "message": "..."}` — no new row is created.

## Gotchas

- **This tool is admin-only.** It only exists on `/mcp/admin`. The worker endpoint (`/mcp/worker`) returns "Tool 'admin_secrets' is not available on this endpoint" if you try to call it. If you're a worker agent that legitimately needs secret access, the workflow is: discover via REST, request access, wait for an admin to grant it.
- **`secret_id` (public) vs `id` (internal).** The MCP schema exposes the parameter as `secret_id` for clarity. The underlying handler accepts `id`. You write `secret_id` in your JSON-RPC args. Don't try to be clever and pass `id` — the dispatcher will pass it through but the schema validation might reject it.
- **`list` shows metadata for ALL secrets, not just accessible ones.** Every row gets an `accessible: bool` flag. This is by design — you need to know what exists before you can request access. Don't confuse "I can see it" with "I can reveal it".
- **`reveal` is audit logged.** Don't reveal secrets in a tight loop or for debugging. The `last_revealed_at` timestamp updates and the request is recorded server-side.
- **`request_access` requires a `reason`.** Pass a real reason — "I need it" is not useful. The reason is shown to the admin who reviews the request. Reference a task ID, incident, or specific use case.
- **Pending requests are deduped.** If you call `request_access` twice for the same secret, the second call returns `already_pending` instead of creating a duplicate row. Use this to retry safely.
- **`reveal` returns `value` as a plain string.** For `secret_type=certificate`, you also get `extra_1` and `extra_2` (e.g. cert body and key). For `secret_type=api_key`, those are usually `null`.
- **No `create`, `update`, or `delete` actions.** You can't manage the vault via MCP — only read and request. Use the REST API (`/api/secrets/...`) for write operations.
- **Errors come back as exceptions.** The `metadata` and `reveal` handlers raise `ValueError` for missing secrets and `PermissionError` for forbidden reveals. The MCP dispatcher catches these and returns them as JSON-RPC error responses (code -32603 for internal, or the exception's message in `error.message`). Check the response shape, not just `result`.
- **`accessible=true` is cached per-call.** Each `list` call recomputes the `accessible` flag based on the current user's groups and grants at call time. If you were just added to a group, the next `list` call will reflect it.
- **Group membership is name-based in the handler.** When you grant a group access via `secret_access`, the grantee_id is the group's UUID. The handler looks up your group memberships by name then by ID — if a group was renamed after you were added, the membership check still works because it joins on `ugm.group_id`.
- **Admin role is determined by `api_keys.role`.** The handler checks `SELECT role FROM api_keys WHERE user_id = $1 AND active = true LIMIT 1`. If you have multiple keys with different roles, the first active one wins. If you're an admin on one key and an agent on another, results may vary.
- **The `value` field in `reveal` response is the actual secret in plaintext.** Don't log it, don't echo it to chat, don't put it in events. If you need to use it, use it once and discard.
- **JSON-RPC result wrapping:** `tools/call` returns `result.content[0].text` as a JSON string. Parse that string to get the actual payload.
- **No batch operations.** Reveal one secret at a time. If you need N secrets, call reveal N times — but consider whether you really need all of them.
