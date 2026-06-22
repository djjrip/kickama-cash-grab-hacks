-- Analytics dashboard sharding schema.
--
-- This migration keeps the dashboard write path append-only while making the
-- tenant and workspace shard boundaries explicit. New deployments can route
-- analytics events by shard_key and create additional HASH partitions without
-- changing dashboard query semantics.

CREATE TABLE IF NOT EXISTS analytics_events_sharded (
    id              BIGSERIAL,
    tenant_id       text NOT NULL,
    workspace_id    text NOT NULL,
    event_name      text NOT NULL,
    occurred_at     timestamptz NOT NULL,
    shard_key       integer GENERATED ALWAYS AS (
        mod(abs(hashtext(tenant_id || ':' || workspace_id)), 32)
    ) STORED,
    properties      jsonb NOT NULL DEFAULT '{}',
    ingested_at     timestamptz NOT NULL DEFAULT NOW(),
    PRIMARY KEY (shard_key, occurred_at, id)
) PARTITION BY HASH (shard_key);

CREATE TABLE IF NOT EXISTS analytics_events_shard_00
    PARTITION OF analytics_events_sharded
    FOR VALUES WITH (MODULUS 4, REMAINDER 0);

CREATE TABLE IF NOT EXISTS analytics_events_shard_01
    PARTITION OF analytics_events_sharded
    FOR VALUES WITH (MODULUS 4, REMAINDER 1);

CREATE TABLE IF NOT EXISTS analytics_events_shard_02
    PARTITION OF analytics_events_sharded
    FOR VALUES WITH (MODULUS 4, REMAINDER 2);

CREATE TABLE IF NOT EXISTS analytics_events_shard_03
    PARTITION OF analytics_events_sharded
    FOR VALUES WITH (MODULUS 4, REMAINDER 3);

CREATE INDEX IF NOT EXISTS idx_analytics_events_sharded_dashboard
    ON analytics_events_sharded (tenant_id, workspace_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_analytics_events_sharded_name_time
    ON analytics_events_sharded (event_name, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_analytics_events_sharded_properties
    ON analytics_events_sharded USING GIN (properties);

CREATE OR REPLACE VIEW analytics_dashboard_events AS
SELECT
    tenant_id,
    workspace_id,
    event_name,
    occurred_at,
    shard_key,
    properties
FROM analytics_events_sharded;
