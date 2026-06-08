-- NOTIFY triggers for document and monitor_status INSERTs
-- Drives real-time dashboard updates via SSE pg_listener

-- Trigger: NOTIFY on document INSERT
CREATE OR REPLACE FUNCTION notify_document_created()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('document_created', json_build_object(
        'id', NEW.id,
        'title', NEW.title,
        'source_type', NEW.source_type
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_document_created_notify ON documents;
CREATE TRIGGER trg_document_created_notify
    AFTER INSERT ON documents
    FOR EACH ROW
    EXECUTE FUNCTION notify_document_created();

-- Trigger: NOTIFY on monitor_status INSERT
CREATE OR REPLACE FUNCTION notify_monitor_status_update()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('monitor_status', json_build_object(
        'monitor_id', NEW.monitor_id,
        'monitor_name', NEW.monitor_name,
        'status', NEW.status,
        'received_at', NEW.received_at
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_monitor_status_notify ON monitor_status;
CREATE TRIGGER trg_monitor_status_notify
    AFTER INSERT ON monitor_status
    FOR EACH ROW
    EXECUTE FUNCTION notify_monitor_status_update();
