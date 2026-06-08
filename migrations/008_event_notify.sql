-- PostgreSQL NOTIFY trigger on events table for real-time dashboard SSE.
-- Uses bare CREATE OR REPLACE FUNCTION (no nested DO blocks required).

CREATE OR REPLACE FUNCTION notify_event_created()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('event_created', json_build_object(
        'id', NEW.id,
        'ts', NEW.ts,
        'source', NEW.source,
        'type', NEW.type,
        'severity', NEW.severity,
        'title', NEW.title
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_event_created_notify ON events;
CREATE TRIGGER trg_event_created_notify
    AFTER INSERT ON events
    FOR EACH ROW
    EXECUTE FUNCTION notify_event_created();

-- Also add NOTIFY for agent_tasks status changes

CREATE OR REPLACE FUNCTION notify_task_updated()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        PERFORM pg_notify('task_update', json_build_object(
            'id', NEW.id,
            'status', NEW.status,
            'title', NEW.title,
            'claimed_by', NEW.claimed_by
        )::text);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_task_updated_notify ON agent_tasks;
CREATE TRIGGER trg_task_updated_notify
    AFTER UPDATE ON agent_tasks
    FOR EACH ROW
    EXECUTE FUNCTION notify_task_updated();
