# Secret Storage Module — Design Spec

**Date:** 2026-06-12  
**Status:** Approved  
**Phase:** Core infrastructure + Secret Storage module for LamaDB

---

## Overview

A secret, API key, OAuth credential, and login storage system accessible to AI agents. Secrets are encrypted at rest using PostgreSQL `pgcrypto`, governed by a new first-class **Groups** access model, exposed via REST and MCP, with a full dashboard management UI. Agents can discover secrets (metadata only) without access, then request permission through a formal approval workflow.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    LamaDB Core                       │
│  users + api_keys + auth + groups (NEW)             │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────┐    ┌────────────────────────────┐ │
│  │   groups     │    │         secrets             │ │
│  │  (core-ish)  │◄───│        (module)             │ │
│  │              │    │                              │ │
│  │  • groups    │    │  • secrets (pgcrypto)       │ │
│  │  • members   │    │  • secret_access            │ │
│  │              │    │  • access_requests           │ │
│  │  REST API    │    │  • audit_log                 │ │
│  │  Dashboard   │    │  • REST API + MCP tools      │ │
│  │              │    │  • Dashboard pages           │ │
│  └──────────────┘    └────────────────────────────┘ │
│                                                     │
│  ┌─────────────────────────────────────────────────┐│
│  │  AuthUser (enriched with groups)                ││
│  │  Group-scoped API keys                          ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘

Future consumers of groups: kanban, notifications, agent_board, documents...
```

---

## Database Schema

### Core — Groups Infrastructure (migration 015)

Two new tables. Created in the main migration sequence, not module-specific.

```sql
-- Extension (needed for pgcrypto, rest of secret module)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Named collections of users
CREATE TABLE groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Many-to-many membership
CREATE TABLE user_group_memberships (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',   -- 'owner' | 'admin' | 'member'
    added_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, group_id)
);
```

### API Key Group Scoping (migration 015)

Extend `api_keys` scopes to support group-based access filtering:

```sql
-- scopes TEXT[] can now contain 'group:<name>' entries
-- e.g. scopes = '{kanban,group:admin-bots}'
-- Auto-filters list endpoints based on key's group membership
```

No schema change needed — `scopes` is already `TEXT[]`. The auth enrichment layer parses `group:` prefixed entries and filters endpoint responses accordingly.

### Auth Enrichment (app/auth.py)

`AuthUser` gains a new field:

```python
class AuthUser:
    user_id: str | None
    name: str
    role: str          # admin | agent | read
    scopes: list[str]
    groups: list[str]  # NEW — populated from user_group_memberships
```

Populated after authentication via a single query:

```sql
SELECT g.name FROM groups g
JOIN user_group_memberships ugm ON g.id = ugm.group_id
WHERE ugm.user_id = $1
```

### Secrets Module Tables (migration 016)

```sql
-- The encrypted secret store
CREATE TABLE secrets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,                          -- "OpenAI API Key"
    service TEXT NOT NULL,                       -- "openai", "github", "minimax"
    description TEXT,
    secret_type TEXT NOT NULL,                   -- api_key | oauth | login | token | custom
    -- Encrypted value columns (BYTEA, pgcrypto)
    encrypted_value BYTEA NOT NULL,              -- primary secret
    encrypted_extra_1 BYTEA,                     -- client_id / username / extra field
    encrypted_extra_2 BYTEA,                     -- overflow / freeform field
    -- Metadata
    priority TEXT NOT NULL DEFAULT 'primary',    -- primary | secondary | fallback
    tags TEXT[] DEFAULT '{}',                    -- e.g. {production, paid}
    owner_user_id UUID REFERENCES users(id),
    owner_group_id UUID REFERENCES groups(id),
    -- Lifecycle
    expires_at TIMESTAMPTZ,                      -- null = never
    last_revealed_at TIMESTAMPTZ,                -- updated on each reveal
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Access grants beyond owners
CREATE TABLE secret_access (
    id BIGSERIAL PRIMARY KEY,
    secret_id UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    grantee_type TEXT NOT NULL,                  -- 'user' | 'group'
    grantee_id UUID NOT NULL,                    -- user_id or group_id
    access_level TEXT NOT NULL DEFAULT 'read',   -- 'read' | 'read_write'
    granted_by UUID REFERENCES users(id),
    granted_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (secret_id, grantee_type, grantee_id)
);

-- Formal access request workflow
CREATE TABLE secret_access_requests (
    id BIGSERIAL PRIMARY KEY,
    secret_id UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    requester_user_id UUID NOT NULL REFERENCES users(id),
    requested_level TEXT NOT NULL DEFAULT 'read',
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending | approved | rejected
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Audit trail for every security-relevant action
CREATE TABLE secret_audit_log (
    id BIGSERIAL PRIMARY KEY,
    secret_id UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    action TEXT NOT NULL,                        -- create | update | delete | reveal | grant | revoke | request | approve | reject
    details TEXT,
    ip_address TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Encryption Function (SECURITY DEFINER, in migration 016)

```sql
CREATE OR REPLACE FUNCTION reveal_secret_value(
    p_secret_id UUID,
    p_requesting_user_id UUID
) RETURNS TEXT AS $$
DECLARE
    raw_value TEXT;
BEGIN
    -- Decrypt using the server-side master key
    SELECT pgp_sym_decrypt(encrypted_value, current_setting('secrets.encryption_key'))
    INTO raw_value FROM secrets WHERE id = p_secret_id;
    
    IF raw_value IS NULL THEN
        RAISE EXCEPTION 'Decryption failed for secret %', p_secret_id;
    END IF;
    
    -- Audit log the reveal
    INSERT INTO secret_audit_log (secret_id, user_id, action, details)
    VALUES (p_secret_id, p_requesting_user_id, 'reveal', 'decrypted via reveal_secret_value()');
    
    -- Update last revealed timestamp
    UPDATE secrets SET last_revealed_at = now() WHERE id = p_secret_id;
    
    RETURN raw_value;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

### Master Key Setup (in migration 016)

```sql
-- Generate once, persist in PostgreSQL config
DO $$ 
BEGIN
    IF current_setting('secrets.encryption_key', true) IS NULL THEN
        PERFORM set_config('secrets.encryption_key', 
            encode(gen_random_bytes(32), 'hex'), false);
    END IF;
END $$;
```

The key lives in `postgresql.auto.conf`. Never exposed via any API, never in app code, never in env vars.

### SSE NOTIFY Triggers (in migration 016)

```sql
-- Notify dashboard on secret changes
CREATE OR REPLACE FUNCTION notify_secret_change() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('secret_updated', json_build_object(
        'id', COALESCE(NEW.id, OLD.id),
        'action', TG_OP
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER secret_notify_trigger
    AFTER INSERT OR UPDATE OR DELETE ON secrets
    FOR EACH ROW EXECUTE FUNCTION notify_secret_change();

-- Similarly for secret_access_requests
CREATE TRIGGER secret_request_notify_trigger
    AFTER INSERT OR UPDATE ON secret_access_requests
    FOR EACH ROW EXECUTE FUNCTION notify_secret_change();
```

---

## Encryption & Security

### What's Encrypted

| Column | Encrypted | Reason |
|--------|-----------|--------|
| `name`, `service`, `description` | **No** | Metadata needed for discovery and listing |
| `secret_type`, `priority`, `tags` | **No** | Filtering/sorting metadata |
| `encrypted_value` | **Yes** | The actual credential |
| `encrypted_extra_1` | **Yes** | e.g. client_id, username |
| `encrypted_extra_2` | **Yes** | Overflow/freeform |
| `owner_*`, `expires_at`, `last_revealed_at` | **No** | Access routing and lifecycle tracking |

### Hard Security Rules

1. **Never log plaintext values.** Audit log stores action + user + timestamp, never the value.
2. **Never return decrypted values in list endpoints.** Only the dedicated `reveal` path decrypts.
3. **Never cache the reveal endpoint.** No `@cached` decorator — cache invalidation can't track encryption state.
4. **Mask in error messages.** If decryption fails, say "decryption error" — not "invalid key" or "key mismatch."
5. **Reveal values are transient.** App code receives the decrypted string, returns it to the caller, and discards it. Not stored in memory or intermediate structures.
6. **Master key is DB-only.** `secrets.encryption_key` exists only as a PostgreSQL server setting. Zero copies in app config, env vars, or files.
7. **Reveal endpoint requires explicit authorization.** Access check runs BEFORE decryption. If denied, the function body never executes.

### Key Rotation (Phase 2)

Future schema addition: `secrets.key_version INT DEFAULT 1`. Rotation procedure:
1. Set new `secrets.encryption_key` (with version suffix)
2. Background task: decrypt with old key, re-encrypt with new key, bump version
3. Update `reveal_secret_value()` to read the version and select the correct key
4. Drop old key once all secrets are migrated

---

## Fixed Schema with Types

### Type Definitions

| Type | Primary Field (`encrypted_value`) | Extra 1 (`encrypted_extra_1`) | Extra 2 (`encrypted_extra_2`) |
|------|----------------------------------|-------------------------------|-------------------------------|
| `api_key` | The API key itself | *(unused)* | *(unused)* |
| `oauth` | Client Secret | Client ID | *(unused)* |
| `login` | Password | Username | *(unused)* |
| `token` | The token | Token Type (Bearer/Basic/Custom) | *(unused)* |
| `custom` | Primary value | Freeform extra | Freeform extra |

### Priority Values

| Priority | Meaning |
|----------|---------|
| `primary` | Default, main credential for a service |
| `secondary` | Backup/fallback credential |
| `fallback` | Explicitly marked fallback |
| *(future)* | Extensible via string values |

### Query Patterns

```
# By service
GET /api/secrets?service=openai

# By type
GET /api/secrets?secret_type=api_key

# By priority
GET /api/secrets?priority=primary

# By tag
GET /api/secrets?tag=production

# Only secrets I can reveal
GET /api/secrets?accessible=true

# Expiring soon (within 30 days)
GET /api/secrets?expiring_soon=true

# Expired
GET /api/secrets?expired=true

# By group ownership
GET /api/secrets?group=admin-bots

# Combined
GET /api/secrets?service=openai&secret_type=api_key&tag=production&accessible=true
```

---

## Access Control Model

### Ownership

A secret is owned by EITHER:
- A specific user (`owner_user_id`)
- A group (`owner_group_id`)

If group-owned, all group members with `admin` or `owner` role have full access.

### Explicit Grants

`secret_access` table grants specific users or groups access to a secret they don't own. Levels:
- `read` — can reveal the value
- `read_write` — can also edit/delete the secret

### Group-Scoped API Keys

`api_keys.scopes` supports `group:<name>` entries. When an API key has a group scope, list endpoints auto-filter to only show secrets visible to that group. An agent with `scopes: ['group:dev-team']` can't even discover secrets owned by `admin-bots`.

### Access Check Logic

```
can_reveal(secret, auth_user):
    IF auth_user.role == 'admin'              → ALLOW
    IF auth_user.user_id == secret.owner_user_id  → ALLOW
    IF secret.owner_group_id in auth_user.groups  → ALLOW  
    IF explicit grant exists for user or group     → ALLOW
    → DENY (403, suggest /request endpoint)

can_manage(secret, auth_user):
    same as above, but explicit grant must be 'read_write'
```

---

## API Design

### REST Endpoints — Secrets (`/api/secrets`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/secrets` | admin, agent | Create secret (encrypts on write) |
| `GET` | `/api/secrets` | any | List secrets (metadata only — no values) |
| `GET` | `/api/secrets/{id}` | any | Single secret metadata |
| `PATCH` | `/api/secrets/{id}` | owner/admin | Update metadata or re-encrypt value |
| `DELETE` | `/api/secrets/{id}` | owner/admin | Delete + cascade access/requests/logs |
| `GET` | `/api/secrets/{id}/reveal` | access-granted | Decrypt and return value (audit logged) |

### REST Endpoints — Access Control

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/secrets/{id}/access` | owner/admin | Grant user or group access |
| `DELETE` | `/api/secrets/{id}/access/{grant_id}` | owner/admin | Revoke access |
| `GET` | `/api/secrets/{id}/access` | owner/admin | List who has access |

### REST Endpoints — Access Requests

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/secrets/{id}/request` | any | Submit access request |
| `GET` | `/api/secrets/requests` | admin, owner | List pending requests (filterable) |
| `PATCH` | `/api/secrets/requests/{req_id}` | admin, owner | Approve or reject |

### REST Endpoints — Groups (core, `/api/groups`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/groups` | admin | Create group |
| `GET` | `/api/groups` | any | List groups |
| `GET` | `/api/groups/{id}` | any | Single group + member list |
| `PATCH` | `/api/groups/{id}` | admin, group owner | Update group metadata |
| `DELETE` | `/api/groups/{id}` | admin | Delete group |
| `POST` | `/api/groups/{id}/members` | admin, group owner | Add user to group |
| `DELETE` | `/api/groups/{id}/members/{user_id}` | admin, group owner | Remove user from group |
| `PATCH` | `/api/groups/{id}/members/{user_id}` | admin, group owner | Change member role |

### Bulk Operations (Phase 2 deferred)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/secrets/bulk/grant` | admin | Grant group access to multiple secrets |
| `POST` | `/api/secrets/bulk/delete` | admin | Delete multiple secrets by service/tag |

### Import Endpoint (Phase 2 deferred)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/secrets/import` | admin | Import from .env or 1Password CSV |

### MCP Tools (4 tools)

| Tool Name | Handler | Description |
|-----------|---------|-------------|
| `list_secrets` | `modules.secrets.mcp:list_secrets` | List all secrets visible to caller (metadata only — no values). Supports filters: `service`, `secret_type`, `tag`, `accessible` |
| `get_secret_metadata` | `modules.secrets.mcp:get_secret_metadata` | Get full metadata for one secret by ID |
| `reveal_secret` | `modules.secrets.mcp:reveal_secret` | Decrypt and return a secret value (requires access grant or ownership). Audit logged. |
| `request_secret_access` | `modules.secrets.mcp:request_secret_access` | Request access to a secret visible in list but not yet accessible. Requires reason text. |

Agent interaction flow through MCP:

```
1. list_secrets(service="openai")
   → [{id: "abc", name: "OpenAI API Key", accessible: false}, ...]
   
2. request_secret_access(secret_id="abc", reason="Building LamaDB embedding feature")
   → {status: "pending", request_id: "req-123"}
   
3. Human approves via dashboard (or admin agent, Phase 2)
   
4. reveal_secret(secret_id="abc")
   → {value: "sk-...", type: "api_key"}   [audit logged]
```

---

## Dashboard / Frontend

### Sidebar

New category "Security" with three entries:

```
📊 Overview
📄 Documents
🔍 Search
📡 Events
...
🔐 Security
   ├─ 🔑 Secrets
   ├─ 📋 Access Requests
   └─ 👥 Groups
```

### Secrets Page (`static/js/pages/secrets.js`)

**Table view:**
- Columns: Name, Service, Type, Priority, Tags, Owner, Expires, Last Used
- Filters: service dropdown (auto-populated from DB), type, priority, tags, accessible toggle
- Yellow badge: "Expires in 7d"
- Red badge: "Expired"
- Gray text: "Never used" for un-revealed secrets

**Detail panel (slides in from right):**
- Metadata section (name, service, description, type, priority, tags, expiration)
- Access list section: table of grantees with grant/revoke buttons
- Reveal section (collapsible):
  - Click "Reveal" → decrypted value appears in a `<input type="text" readonly>` field
  - Copy button alongside: uses `navigator.clipboard.writeText()` with "Copied!" toast
  - Auto-masked after 30 seconds (field clears, requires re-reveal)
  - Each reveal is audit logged
- Edit button → inline form (same as create, below)
- Delete button with confirmation

**Create/Edit form:**
- Name, Service (autocomplete from existing values), Description, Tags
- Type selector (dropdown: API Key, OAuth, Login, Token, Custom)
- Dynamic value fields based on type:
  - `api_key` → one field labeled "API Key"
  - `oauth` → "Client ID" + "Client Secret"
  - `login` → "Username" + "Password"
  - `token` → "Token" + "Token Type" (dropdown: Bearer/Basic/Custom)
  - `custom` → "Value" + "Extra 1" + "Extra 2"
- Priority selector (primary/secondary/fallback)
- Owner selector: radio toggle between User (dropdown) and Group (dropdown)
- Expiration date picker (optional)

### Access Requests Page (`static/js/pages/access_requests.js`)

**Queue view:**
- Columns: Requester, Secret, Reason, Requested, Status, Actions
- Filter tabs: Pending | Approved | Rejected
- Actions: Approve (auto-creates `secret_access` grant + audit log), Reject (audit logs)
- Approving an `access_request` automatically:
  1. Inserts into `secret_access`
  2. Updates request `status = 'approved'`
  3. Logs to `secret_audit_log`

### Groups Page (`static/js/pages/groups.js`)

**Table view:**
- Columns: Name, Description, Member Count, Created
- Click row → detail panel with member list
- "New Group" button → simple form (name, description)
- Detail panel: member table (user name, role, joined date), add member button (user selector), remove button

### SSE Real-Time Updates

`LISTEN secret_updated` and `LISTEN secret_request_updated` channels for live dashboard refresh on create/update/delete/approve/reject actions.

### Frontend Patterns

- Uses existing LamaDB CSS variables and component library
- Follows existing IIFE + `window.export` pattern for onclick handlers
- Follows existing SSE callback pattern (`window._sseCallbacks['secret_updated']`)
- Copy-to-clipboard uses `navigator.clipboard.writeText()` with toast notification
- Theme-aware (light/dark) via existing CSS variable overrides
- Mobile responsive via existing grid/stack patterns

---

## Files to Create / Modify

```
lamadb/
├── migrations/
│   ├── 015_groups_core.sql          # NEW: pgcrypto EXT, groups, user_group_memberships
│   └── 016_secrets_module.sql       # NEW: 4 tables, NOTIFY triggers, reveal_secret_value(), master key
├── modules/
│   ├── groups/                       # NEW: core-ish module for group management
│   │   ├── __init__.py              # MODULE_NAME="groups", ENABLED=True, get_router()
│   │   ├── routes.py                # 8 REST endpoints
│   │   └── models.py                # GroupCreate, GroupResponse, MemberAdd, MemberUpdate
│   └── secrets/                      # NEW: secrets storage module
│       ├── __init__.py              # MODULE_NAME="secrets", ENABLED=True, get_router(), MODULE_MCP_TOOLS
│       ├── routes.py                # ~17 REST endpoints
│       ├── models.py                # SecretCreate, SecretResponse, SecretReveal, AccessGrant, AccessRequest, etc.
│       ├── access.py                # can_reveal(), can_manage(), grant_access(), revoke_access()
│       ├── crypto.py                # encrypt_secret(), decrypt_secret() — thin wrappers around pgcrypto
│       └── mcp.py                   # 4 MCP tool handlers
├── app/
│   ├── main.py                      # MODIFY: add SSE pg_listener channels (secret_updated, secret_request_updated)
│   └── auth.py                      # MODIFY: enrich AuthUser with groups list
├── static/
│   └── js/
│       ├── pages/
│       │   ├── secrets.js           # NEW: Secrets management page (~200 lines)
│       │   ├── access_requests.js   # NEW: Access request queue (~100 lines)
│       │   └── groups.js            # NEW: Groups management page (~120 lines)
│       └── app.js                   # MODIFY: add sidebar entries, import new pages
└── tests/
    ├── test_groups.py               # NEW: ~10 tests (group CRUD, membership, auth enrichment)
    └── test_secrets.py              # NEW: ~20 tests (CRUD, encryption, access control, requests, audit)
```

### Module Bootstrap Pattern

```python
# modules/secrets/__init__.py
MODULE_NAME = "secrets"
MODULE_DESCRIPTION = "Encrypted secret, API key, and credential storage for agents"
MODULE_VERSION = "1.0.0"
ENABLED = True

MODULE_MCP_TOOLS = [
    {"name": "list_secrets", "handler": "modules.secrets.mcp:list_secrets",
     "description": "List all secrets visible to you (metadata only — no values). Filter by service, type, tags, accessibility."},
    {"name": "get_secret_metadata", "handler": "modules.secrets.mcp:get_secret_metadata",
     "description": "Get full metadata for a specific secret by ID."},
    {"name": "reveal_secret", "handler": "modules.secrets.mcp:reveal_secret",
     "description": "Decrypt and return a secret value. Requires access grant or ownership. Audit logged."},
    {"name": "request_secret_access", "handler": "modules.secrets.mcp:request_secret_access",
     "description": "Request access to a secret you can see but cannot reveal. Provide a reason for the request."},
]

def get_router():
    from .routes import router
    return router
```

---

## Phase 2 — Deferred Features

These are documented for forward compatibility. Not built in v1.

### Auth Broker & Gateway

The `secret_access` table and `reveal_secret_value()` function are the foundation. Future broker:
- `secret_access.expires_at` for TTL grants (add column later)
- Proxy inject service: intercepts LLM API calls, fetches and injects credentials
- Usage counter on secrets to track which credentials are most active

### Secret Health Check / Validation

- `secrets.validation_url TEXT` column (optional)
- Background poller (`secrets/collector.py`) pings validation URL with decrypted key
- Dashboard health dot: green (2xx), red (failure), gray (no URL set)
- Follows existing poller pattern (like Dozzle, Hermes, HA)
- Each check is audit logged as `action = 'health_check'`

### Bulk Operations

- `POST /api/secrets/bulk/grant` — grant a group access to multiple secrets at once
- `POST /api/secrets/bulk/delete` — delete all secrets for a given service or tag
- Checkbox selection in dashboard + batch action dropdown

### Import

- `POST /api/secrets/import` — accepts structured JSON payload
- Supports formats: 1Password CSV, .env key=value, generic JSON array
- Auto-maps common field names to LamaDB secret types
- Dry-run mode: preview what would be imported before committing

### Agent-Based Approval

- Admin agents (like Hermes on Opus) call `approve_access_request` MCP tool
- Optional auto-approval rules: "if requester is in group X and secret is type Y, auto-approve"
- Notification dispatch on new requests (via existing notifications module)
- MCP tool: `approve_access_request` and `reject_access_request`

### Key Rotation

- `secrets.key_version INT` column
- Background rotation task: decrypt with old key, re-encrypt with new, bump version
- Multiple active `secrets.encryption_key_v{version}` PostgreSQL settings
- Gradual migration — no downtime

---

## Testing Strategy

### tests/test_groups.py (~10 tests)

- `test_create_group` — basic CRUD
- `test_list_groups` — includes member count
- `test_add_remove_member` — user-group membership
- `test_member_role_change` — promote/demote
- `test_auth_enrichment` — AuthUser.groups populated correctly
- `test_group_scoped_api_key` — key with `group:dev-team` scope only sees appropriate secrets
- `test_unauthorized_group_management` — agent/read roles can't create groups

### tests/test_secrets.py (~20 tests)

- `test_create_secret_api_key` — create, verify metadata returned (no values)
- `test_create_secret_oauth` — extra fields populated
- `test_reveal_secret_as_owner` — decrypt and verify value
- `test_reveal_secret_as_granted_user` — access grant works
- `test_reveal_secret_denied` — 403 without access
- `test_reveal_secret_audit_logged` — audit row created
- `test_list_secrets_metadata_only` — no values in list response
- `test_list_secrets_filter_service` — query parameters work
- `test_list_secrets_filter_accessible` — only shows secrets user can reveal
- `test_list_secrets_filter_tags` — tag filtering
- `test_list_secrets_filter_expired` — expiration filter
- `test_group_owned_secret` — group members can access
- `test_group_scoped_list` — api key with group scope sees filtered results
- `test_access_request_submit` — creates pending request
- `test_access_request_approve` — creates secret_access grant + logs
- `test_access_request_reject` — sets status, no access granted
- `test_update_secret_re_encrypt` — changing value encrypts properly
- `test_delete_secret_cascade` — access, requests, logs all cleaned up
- `test_priority_filtering` — primary/secondary/fallback filtering
- `test_last_revealed_updated` — timestamp updates on reveal

---

## Dependencies

- **PostgreSQL:** `pgcrypto` extension (built-in, just needs `CREATE EXTENSION`)
- **Python:** No new dependencies beyond existing stack (fastapi, asyncpg, pydantic)
- **Frontend:** No new JS libraries (vanilla JS, existing CSS variables)
- **Docker:** No changes to Dockerfile or docker-compose.yml
- **Env vars:** None new — master key lives in PostgreSQL, not env

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Losing the master key = losing all secrets | Key persists in `postgresql.auto.conf` across PG restarts. DB backup includes it. |
| pgcrypto performance on large volumes | Each reveal is a single-row BYTEA decrypt — negligible overhead. No bulk decrypt paths. |
| Plaintext leaking via PG logs | `log_statement` and `log_min_duration_statement` may capture the `pgp_sym_encrypt()` call with the value as a parameter. Mitigation: use the SECURITY DEFINER function pattern where the value is passed as a bound parameter, not inline SQL. |
| Group concept adoption risk | If no other module uses groups, they're still useful for secrets alone. Low downside. |
| Migration ordering | 015 must run before 016 (groups referenced by secrets). Migration runner is sequential — already handled. |
| Static files stale | Same as all LamaDB modules — rebuild image after static changes. |
