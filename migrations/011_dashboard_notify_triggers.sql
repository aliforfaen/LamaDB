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

-- Trigger: NOTIFY on document UPDATE
CREATE OR REPLACE FUNCTION notify_document_updated()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('document_created', json_build_object(
        'id', NEW.id,
        'title', NEW.title,
        'source_type', NEW.source_type,
        'action', 'updated'
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_document_updated_notify ON documents;
CREATE TRIGGER trg_document_updated_notify
    AFTER UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION notify_document_updated();

-- Trigger: NOTIFY on document DELETE
CREATE OR REPLACE FUNCTION notify_document_deleted()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('document_created', json_build_object(
        'id', OLD.id,
        'title', OLD.title,
        'source_type', OLD.source_type,
        'action', 'deleted'
    )::text);
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_document_deleted_notify ON documents;
CREATE TRIGGER trg_document_deleted_notify
    AFTER DELETE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION notify_document_deleted();
