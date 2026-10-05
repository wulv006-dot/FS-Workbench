-- Proposed isolated reporting database. No production installation.
CREATE TABLE IF NOT EXISTS collection_runs (
  run_id TEXT PRIMARY KEY,
  source TEXT NOT NULL CHECK(source IN ('ga4','gsc','ads')),
  resource_id TEXT NOT NULL,
  query_version TEXT NOT NULL,
  collected_at_utc TEXT NOT NULL,
  requested_through TEXT NOT NULL,
  verified_through TEXT,
  status TEXT NOT NULL CHECK(status IN ('success','empty','partial','failed')),
  error_code TEXT,
  is_mock INTEGER NOT NULL CHECK(is_mock IN (0,1))
);
CREATE TABLE IF NOT EXISTS metric_rows (
  source TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  source_date TEXT NOT NULL,
  source_timezone TEXT NOT NULL,
  currency TEXT NOT NULL DEFAULT '',
  grain TEXT NOT NULL,
  dimensions_json TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  metric_value TEXT NOT NULL,
  data_state TEXT NOT NULL CHECK(data_state IN ('provisional','final','unknown')),
  run_id TEXT NOT NULL REFERENCES collection_runs(run_id),
  PRIMARY KEY(source,resource_id,source_date,source_timezone,currency,grain,dimensions_json,metric_name)
);
