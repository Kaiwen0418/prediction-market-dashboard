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

-- Sparse five-minute bins. Corrections append versions with actual knowledge time.
CREATE TABLE IF NOT EXISTS surveillance_dirty_bins (
 venue text NOT NULL, market_id text NOT NULL, outcome text NOT NULL, bin_end timestamptz NOT NULL,
 PRIMARY KEY(venue,market_id,outcome,bin_end)
);
CREATE TABLE IF NOT EXISTS surveillance_aggregates (
 venue text NOT NULL, market_id text NOT NULL, outcome text NOT NULL, bin_end timestamptz NOT NULL,
 known_at timestamptz NOT NULL, document jsonb NOT NULL, raw_ids text[] NOT NULL,
 PRIMARY KEY(venue,market_id,outcome,bin_end,known_at)
);
CREATE TABLE IF NOT EXISTS surveillance_walks (
 id text PRIMARY KEY, venue text NOT NULL, market_id text NOT NULL,
 lower_time timestamptz NOT NULL, upper_time timestamptz NOT NULL, known_at timestamptz NOT NULL,
 raw_ids text[] NOT NULL, refs_complete boolean NOT NULL, observed_trades integer NOT NULL DEFAULT -1
);
ALTER TABLE surveillance_walks ADD COLUMN IF NOT EXISTS observed_trades integer NOT NULL DEFAULT -1;
CREATE INDEX IF NOT EXISTS surveillance_walk_window ON surveillance_walks(venue,market_id,upper_time);
CREATE TABLE IF NOT EXISTS surveillance_wallet_profiles (
 id text PRIMARY KEY, case_id text NOT NULL, wallet text NOT NULL,
 admitted_at timestamptz NOT NULL DEFAULT now(), known_at timestamptz,
 document jsonb NOT NULL, raw_ids text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS surveillance_profile_admission ON surveillance_wallet_profiles(admitted_at);
CREATE INDEX IF NOT EXISTS surveillance_aggregate_raw ON surveillance_aggregates USING gin(raw_ids);
CREATE INDEX IF NOT EXISTS surveillance_walk_raw ON surveillance_walks USING gin(raw_ids);
CREATE INDEX IF NOT EXISTS surveillance_profile_raw ON surveillance_wallet_profiles USING gin(raw_ids);
INSERT INTO surveillance_schema VALUES (2) ON CONFLICT DO NOTHING;


-- Live five-minute triage counters, never used as historical replay scores.
CREATE TABLE IF NOT EXISTS surveillance_scout (
 venue text NOT NULL, market_id text NOT NULL, bucket timestamptz NOT NULL,
 known_at timestamptz NOT NULL, fills bigint NOT NULL, cash numeric NOT NULL,
 last_event timestamptz NOT NULL, PRIMARY KEY(venue,market_id,bucket)
);
CREATE INDEX IF NOT EXISTS surveillance_scout_recent ON surveillance_scout(venue,bucket);
CREATE INDEX IF NOT EXISTS surveillance_dirty_time ON surveillance_dirty_bins(bin_end);
INSERT INTO surveillance_schema VALUES(3) ON CONFLICT DO NOTHING;

ALTER TABLE surveillance_markets ADD COLUMN IF NOT EXISTS metadata_raw_ids text[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS surveillance_market_metadata_raw ON surveillance_markets USING gin(metadata_raw_ids);

ALTER TABLE surveillance_raw ADD COLUMN IF NOT EXISTS response_headers jsonb NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS surveillance_observations (
 id text PRIMARY KEY,venue text NOT NULL,market_id text,
 lower_time timestamptz NOT NULL,upper_time timestamptz NOT NULL,
 known_at timestamptz NOT NULL,raw_ids text[] NOT NULL,refs_complete boolean NOT NULL
);
CREATE INDEX IF NOT EXISTS surveillance_observation_window ON surveillance_observations(venue,market_id,upper_time);
CREATE INDEX IF NOT EXISTS surveillance_observation_raw ON surveillance_observations USING gin(raw_ids);
CREATE TABLE IF NOT EXISTS surveillance_wallet_daily (
 wallet text NOT NULL,market_id text NOT NULL,outcome text NOT NULL,outcome_label text NOT NULL,day date NOT NULL,
 known_at timestamptz NOT NULL,first_event timestamptz NOT NULL,last_event timestamptz NOT NULL,
 fills bigint NOT NULL,buy_cash numeric NOT NULL,sell_cash numeric NOT NULL,
 buy_shares numeric NOT NULL,sell_shares numeric NOT NULL,max_fill_cash numeric NOT NULL,
 raw_ids text[] NOT NULL,refs_complete boolean NOT NULL,
 PRIMARY KEY(wallet,market_id,outcome,day)
);
CREATE INDEX IF NOT EXISTS surveillance_wallet_daily_recent ON surveillance_wallet_daily(known_at);
CREATE INDEX IF NOT EXISTS surveillance_wallet_daily_raw ON surveillance_wallet_daily USING gin(raw_ids);
CREATE TABLE IF NOT EXISTS surveillance_wallet_events (
 wallet text NOT NULL,event_key text NOT NULL,known_at timestamptz NOT NULL,
 document jsonb NOT NULL,raw_ids text[] NOT NULL,PRIMARY KEY(wallet,event_key,known_at)
);
CREATE INDEX IF NOT EXISTS surveillance_wallet_events_raw ON surveillance_wallet_events USING gin(raw_ids);
CREATE INDEX IF NOT EXISTS surveillance_trade_wallet ON surveillance_trades(venue,(document->>'wallet'),event_time);
INSERT INTO surveillance_schema VALUES(4) ON CONFLICT DO NOTHING;

-- Small indexed provenance arrays replace correlated scans over the full tape.
ALTER TABLE surveillance_cases ADD COLUMN IF NOT EXISTS evidence_raw_ids text[] NOT NULL DEFAULT '{}';
ALTER TABLE surveillance_cases ADD COLUMN IF NOT EXISTS evidence_observation_ids text[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS surveillance_cases_evidence_observation ON surveillance_cases USING gin(evidence_observation_ids);
ALTER TABLE surveillance_cases ADD COLUMN IF NOT EXISTS evidence_indexed boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS surveillance_cases_created ON surveillance_cases(created_at);
CREATE INDEX IF NOT EXISTS surveillance_cases_evidence_raw ON surveillance_cases USING gin(evidence_raw_ids);
CREATE INDEX IF NOT EXISTS surveillance_cases_unindexed ON surveillance_cases(id) WHERE NOT evidence_indexed;
CREATE OR REPLACE FUNCTION surveillance_index_case_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE refs text[];
BEGIN
    SELECT ARRAY(SELECT DISTINCT r FROM (
        SELECT NEW.document->>'rules_raw_id' AS r
        UNION ALL SELECT jsonb_array_elements_text(COALESCE(NEW.document->'replay_raw_ids','[]'))
        UNION ALL SELECT value#>>'{}' FROM jsonb_path_query(NEW.document,'$.**.raw_id') value
    ) candidates WHERE r IS NOT NULL) INTO refs;
    -- Only legacy documents without explicit raw provenance need fill-ID lookup.
    IF jsonb_array_length(COALESCE(NEW.document->'replay_raw_ids','[]'))=0 THEN
        SELECT refs||ARRAY(SELECT DISTINCT t.raw_id FROM
            jsonb_array_elements_text(COALESCE(NEW.document->'replay_input_ids','[]')) rid
            JOIN surveillance_trades t ON t.venue=NEW.venue AND t.id=rid.value) INTO refs;
    END IF;
    NEW.evidence_observation_ids=ARRAY(SELECT jsonb_array_elements_text(COALESCE(NEW.document->'observation_ids','[]')));
    IF TG_OP='UPDATE' THEN
        refs=refs||OLD.evidence_raw_ids;
        NEW.evidence_observation_ids=NEW.evidence_observation_ids||OLD.evidence_observation_ids;
    END IF;
    NEW.evidence_observation_ids=ARRAY(SELECT DISTINCT rid FROM unnest(NEW.evidence_observation_ids) rid);
    SELECT ARRAY(SELECT DISTINCT r FROM unnest(refs) r WHERE r IS NOT NULL) INTO NEW.evidence_raw_ids;
    NEW.evidence_indexed=true;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS surveillance_case_evidence ON surveillance_cases;
CREATE TRIGGER surveillance_case_evidence BEFORE INSERT OR UPDATE OF document ON surveillance_cases
    FOR EACH ROW EXECUTE FUNCTION surveillance_index_case_evidence();
INSERT INTO surveillance_schema VALUES(5) ON CONFLICT DO NOTHING;
