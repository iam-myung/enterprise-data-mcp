-- SPEC §11.2 audit_events rollback (Step 7.1)
DROP TABLE IF EXISTS audit_events;
DROP INDEX IF EXISTS idx_audit_events_trace_id;
