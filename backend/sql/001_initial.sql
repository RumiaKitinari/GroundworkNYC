CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS gw_sources (
    source text NOT NULL,
    source_id text NOT NULL,
    vintage text NOT NULL,
    observed_at text NOT NULL,
    geom geometry(Geometry,4326) NOT NULL,
    properties jsonb NOT NULL,
    PRIMARY KEY (source, source_id, vintage)
);
CREATE INDEX IF NOT EXISTS gw_sources_geom ON gw_sources USING gist (geom);
CREATE TABLE IF NOT EXISTS gw_snapshots (
    id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS gw_hexes (
    snapshot text NOT NULL REFERENCES gw_snapshots(id),
    layer text NOT NULL,
    resolution integer NOT NULL CHECK (resolution IN (7,8,9)),
    cell_id text NOT NULL,
    parent_id text,
    geom geometry(Polygon,4326) NOT NULL,
    properties jsonb NOT NULL,
    PRIMARY KEY (snapshot, layer, cell_id)
);
CREATE INDEX IF NOT EXISTS gw_hexes_geom ON gw_hexes USING gist (geom);
CREATE INDEX IF NOT EXISTS gw_hexes_layer ON gw_hexes(snapshot,layer,resolution);
CREATE TABLE IF NOT EXISTS gw_models (
    version text PRIMARY KEY,
    metadata jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS gw_predictions (
    snapshot text NOT NULL REFERENCES gw_snapshots(id),
    layer text NOT NULL,
    cell_id text NOT NULL,
    model_version text NOT NULL REFERENCES gw_models(version),
    payload jsonb NOT NULL,
    PRIMARY KEY(snapshot,layer,cell_id,model_version),
    FOREIGN KEY(snapshot,layer,cell_id) REFERENCES gw_hexes(snapshot,layer,cell_id)
);
CREATE TABLE IF NOT EXISTS gw_active (
    layer text PRIMARY KEY,
    snapshot text NOT NULL REFERENCES gw_snapshots(id),
    activated_at timestamptz NOT NULL DEFAULT now()
);
