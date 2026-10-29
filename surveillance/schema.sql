CREATE TABLE IF NOT EXISTS surveillance_schema (version integer PRIMARY KEY);
INSERT INTO surveillance_schema VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS surveillance_raw (
 id text PRIMARY KEY, venue text NOT NULL, source text NOT NULL, params jsonb NOT NULL,
 received_at timestamptz NOT NULL, status integer NOT NULL, sha256 text NOT NULL, path text NOT NULL
);
CREATE TABLE IF NOT EXISTS surveillance_markets (
 venue text NOT NULL, id text NOT NULL, condition_id text, document jsonb NOT NULL,
 observed_at timestamptz NOT NULL, raw_id text REFERENCES surveillance_raw(id), PRIMARY KEY(venue,id)
);
CREATE INDEX IF NOT EXISTS surveillance_market_condition ON surveillance_markets(venue,condition_id);
CREATE TABLE IF NOT EXISTS surveillance_rules (
 venue text NOT NULL, market_id text NOT NULL, hash text NOT NULL, document jsonb NOT NULL,
 observed_at timestamptz NOT NULL, raw_id text REFERENCES surveillance_raw(id),
 PRIMARY KEY(venue,market_id,hash,observed_at)
);
CREATE TABLE IF NOT EXISTS surveillance_trades (
 venue text NOT NULL, id text NOT NULL, market_id text NOT NULL, outcome text NOT NULL,
 event_time timestamptz NOT NULL, received_at timestamptz NOT NULL,
 document jsonb NOT NULL, raw_id text REFERENCES surveillance_raw(id), PRIMARY KEY(venue,id)
);
DROP INDEX IF EXISTS surveillance_trade_window;
CREATE INDEX IF NOT EXISTS surveillance_trade_replay ON surveillance_trades(venue,market_id,event_time,id);
CREATE TABLE IF NOT EXISTS surveillance_jobs (
 id text PRIMARY KEY, kind text NOT NULL, venue text NOT NULL, payload jsonb NOT NULL,
 checkpoint jsonb NOT NULL DEFAULT '{}', due_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz, lease_token text, failures integer NOT NULL DEFAULT 0,
 enabled boolean NOT NULL DEFAULT true, last_error text, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS surveillance_coverage (
 id bigserial PRIMARY KEY, job_id text, venue text NOT NULL, kind text NOT NULL,
 observed_at timestamptz NOT NULL DEFAULT now(), document jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS surveillance_cases (
 id text PRIMARY KEY, venue text NOT NULL, market_id text NOT NULL, status text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), document jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS surveillance_case_versions (
 case_id text REFERENCES surveillance_cases(id), version integer NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), document jsonb NOT NULL, PRIMARY KEY(case_id,version)
);
CREATE TABLE IF NOT EXISTS surveillance_information (
 id text PRIMARY KEY, venue text NOT NULL, market_id text NOT NULL,
 first_seen_at timestamptz NOT NULL DEFAULT now(), document jsonb NOT NULL,
 raw_id text REFERENCES surveillance_raw(id)
);

CREATE INDEX IF NOT EXISTS surveillance_rules_history ON surveillance_rules(venue,market_id,observed_at DESC);
CREATE INDEX IF NOT EXISTS surveillance_cases_recent ON surveillance_cases(venue,market_id,created_at DESC);
CREATE INDEX IF NOT EXISTS surveillance_raw_path ON surveillance_raw(path);

CREATE INDEX IF NOT EXISTS surveillance_raw_received ON surveillance_raw(received_at);

CREATE INDEX IF NOT EXISTS surveillance_markets_open ON surveillance_markets(venue,id) WHERE document->>'closed'='false';

CREATE TABLE IF NOT EXISTS surveillance_capacity (
 id integer PRIMARY KEY CHECK(id=1), updated_at timestamptz NOT NULL DEFAULT now(), document jsonb NOT NULL
);

-- FIFO receipt eviction checks these foreign keys for every deleted receipt.
CREATE INDEX IF NOT EXISTS surveillance_rules_raw ON surveillance_rules(raw_id);
CREATE INDEX IF NOT EXISTS surveillance_markets_raw ON surveillance_markets(raw_id);
CREATE INDEX IF NOT EXISTS surveillance_trades_raw ON surveillance_trades(raw_id);
CREATE INDEX IF NOT EXISTS surveillance_information_raw ON surveillance_information(raw_id);
