-- Agent tasks (coordination queue)
CREATE TABLE IF NOT EXISTS agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    task_type TEXT NOT NULL DEFAULT 'general',
    priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'pending',
    created_by TEXT,
    claimed_by TEXT,
    assigned_to TEXT,
    metadata JSONB DEFAULT '{}',
    result JSONB DEFAULT '{}',
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON agent_tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON agent_tasks (priority);
CREATE INDEX IF NOT EXISTS idx_tasks_claimed_by ON agent_tasks (claimed_by);

-- Agent messages (agent-to-agent communication)
CREATE TABLE IF NOT EXISTS agent_messages (
    id BIGSERIAL PRIMARY KEY,
    from_agent TEXT NOT NULL,
    to_agent TEXT,
    subject TEXT NOT NULL,
    body TEXT,
    message_type TEXT NOT NULL DEFAULT 'info',
    parent_id BIGINT REFERENCES agent_messages(id),
    metadata JSONB DEFAULT '{}',
    read BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_to ON agent_messages (to_agent);
CREATE INDEX IF NOT EXISTS idx_messages_unread ON agent_messages (to_agent) WHERE NOT read;

-- Notification trigger: NOTIFY on new task (uses DO block to avoid migration split issues)
DO $$
BEGIN
    -- Create the notification function
    CREATE OR REPLACE FUNCTION notify_agent_task()
    RETURNS TRIGGER AS $$
    BEGIN
        PERFORM pg_notify('agent_task', json_build_object(
            'id', NEW.id,
            'title', NEW.title,
            'priority', NEW.priority,
            'task_type', NEW.task_type
        )::text);
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    -- Create the trigger
    DROP TRIGGER IF EXISTS trg_agent_task_notify ON agent_tasks;
    CREATE TRIGGER trg_agent_task_notify
        AFTER INSERT ON agent_tasks
        FOR EACH ROW
        EXECUTE FUNCTION notify_agent_task();
END;
$$;