-- 017_groups_core.sql
-- Groups as a first-class LamaDB concept.
-- Creates groups, user_group_memberships tables. Enables pgcrypto (needed by secrets module later).

-- Extension for column-level encryption (used by secrets module, migration 018)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Named collections of users
CREATE TABLE IF NOT EXISTS groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Many-to-many membership with roles
CREATE TABLE IF NOT EXISTS user_group_memberships (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    added_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, group_id)
);

-- Index for auth enrichment: fast lookup of groups for a user
CREATE INDEX IF NOT EXISTS idx_ugm_user_id ON user_group_memberships(user_id);

-- Index for listing members of a group
CREATE INDEX IF NOT EXISTS idx_ugm_group_id ON user_group_memberships(group_id);
