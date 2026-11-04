-- Langboard stage 1: full §5.3 data model (researches/report.md).
-- Times: TEXT ISO-8601 UTC ('Z'). Money: REAL. Token counts: nullable INTEGER.

CREATE TABLE credential (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('api_key','subscription','coding_plan','proxy')),
  label TEXT NOT NULL,
  external_id TEXT,
  key_type TEXT,            -- zai: standard | coding_plan | team
  archived_at TEXT,
  UNIQUE (provider, label)
);

CREATE TABLE connection (
  id TEXT PRIMARY KEY,
  credential_id TEXT NOT NULL REFERENCES credential(id),
  base_url TEXT,
  protocol TEXT CHECK (protocol IN ('openai','anthropic','responses')),
  key_type TEXT,
  UNIQUE (credential_id, base_url)
);

CREATE TABLE usage_event (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_event_id TEXT NOT NULL,
  credential_id TEXT NOT NULL REFERENCES credential(id),
  connection_id TEXT REFERENCES connection(id),
  provider TEXT NOT NULL,
  device_id TEXT,
  client_name TEXT,
  client_version TEXT,
  model_raw TEXT,
  canonical_model TEXT,
  ts_utc TEXT NOT NULL,
  received_at_utc TEXT NOT NULL,
  attempt_no INTEGER NOT NULL DEFAULT 1,
  streaming INTEGER,
  incomplete INTEGER NOT NULL DEFAULT 0,
  tokens_source TEXT CHECK (tokens_source IN ('provider_response','client_telemetry','proxy','estimated')),
  accuracy TEXT CHECK (accuracy IN ('verified','unverified')),
  input_tokens INTEGER,
  output_tokens INTEGER,
  total_tokens INTEGER,
  uncached_input_tokens INTEGER,
  cached_read_tokens INTEGER,
  cache_write_tokens INTEGER,
  cache_write_ttl_5m_tokens INTEGER,
  cache_write_ttl_1h_tokens INTEGER,
  cache_write_ttl_30m_tokens INTEGER,
  cache_write_ttl_12h_tokens INTEGER,
  cache_hit_tokens INTEGER,
  cache_miss_tokens INTEGER,
  reasoning_tokens INTEGER,
  UNIQUE (source, source_event_id)
);

CREATE INDEX idx_usage_event_ts ON usage_event (ts_utc);
CREATE INDEX idx_usage_event_cred ON usage_event (credential_id, ts_utc, model_raw);

CREATE TABLE raw_usage (
  usage_event_id TEXT PRIMARY KEY REFERENCES usage_event(id),
  provider_ids TEXT,
  payload TEXT NOT NULL
);

CREATE TABLE provider_aggregate (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  credential_id TEXT REFERENCES credential(id),
  bucket_start_utc TEXT NOT NULL,
  bucket_width TEXT NOT NULL,
  model TEXT,
  source TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  version INTEGER NOT NULL,
  payload TEXT NOT NULL,
  UNIQUE (provider, credential_id, bucket_start_utc, model, source, version)
);

CREATE TABLE reconciliation_result (
  id TEXT PRIMARY KEY,
  credential_id TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  local_total INTEGER,
  provider_total INTEGER,
  matched INTEGER,
  unattributed INTEGER,
  reason_class TEXT,
  computed_at TEXT NOT NULL
);

CREATE TABLE price_snapshot (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  canonical_model TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  currency TEXT NOT NULL,
  input_price REAL,
  cached_read_price REAL,
  cache_write_price REAL,
  cache_write_ttl_5m_price REAL,
  cache_write_ttl_1h_price REAL,
  output_price REAL,
  UNIQUE (provider, canonical_model, valid_from)
);

CREATE TABLE cost_entry (
  id TEXT PRIMARY KEY,
  credential_id TEXT REFERENCES credential(id),
  ts_utc TEXT NOT NULL,
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  kind TEXT CHECK (kind IN ('usage_fee','subscription_fee','credit','refund','topup')),
  source TEXT CHECK (source IN ('provider_costs_api','balance_api','console','manual')),
  usd_equivalent REAL,
  fx_rate_snapshot TEXT
);

CREATE TABLE quota_observation (
  id TEXT PRIMARY KEY,
  credential_id TEXT NOT NULL,
  ts_utc TEXT NOT NULL,
  kind TEXT CHECK (kind IN ('percent_window','credits','balance_usd','balance_cny','messages')),
  value REAL NOT NULL,
  window TEXT,
  raw TEXT,
  is_official INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE model_alias (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  pattern TEXT NOT NULL,
  canonical_model TEXT NOT NULL,
  valid_from TEXT,
  valid_to TEXT,
  UNIQUE (provider, pattern)
);

CREATE TABLE collect_runs (
  id TEXT PRIMARY KEY,
  connection_label TEXT,
  source TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT,
  http_code INTEGER,
  error TEXT,
  events_written INTEGER
);
