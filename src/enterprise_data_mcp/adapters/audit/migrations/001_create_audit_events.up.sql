-- SPEC §11.2 audit_events (append-only upgrade; Step 7.1)
CREATE TABLE audit_events (
  id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  caller_id TEXT NOT NULL,
  policy_profile TEXT NOT NULL,
  transport TEXT NOT NULL,
  operation TEXT NOT NULL,
  dataset_id TEXT,
  status TEXT NOT NULL,
  error_code TEXT,
  row_count INTEGER,
  duration_ms INTEGER NOT NULL,
  created_at_utc TEXT NOT NULL,
  finished_at_utc TEXT
);

CREATE INDEX idx_audit_events_trace_id ON audit_events (trace_id);
