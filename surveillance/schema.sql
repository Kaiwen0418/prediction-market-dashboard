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
CREATE INDEX IF NOT EXISTS surveillance_trade_window ON surveillance_trades(venue,market_id,event_time);
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
