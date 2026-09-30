-- storage-aggregator: схема БД (Postgres)

CREATE TABLE IF NOT EXISTS operator_sites (
    id              SERIAL PRIMARY KEY,
    domain          TEXT UNIQUE NOT NULL,
    operator_name   TEXT,
    city            TEXT,
    phone           TEXT,
    email           TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | crawled | failed
    raw_extracted   JSONB,
    crawled_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS storages (
    id              SERIAL PRIMARY KEY,
    source          TEXT NOT NULL,             -- dgis | avito | site
    source_id       TEXT NOT NULL,              -- id записи в источнике (id 2ГИС, id объявления Avito, ...)
    category        TEXT,                       -- self_storage | warehouse_rental | logistics | wholesale | industrial
    city            TEXT NOT NULL,
    region          TEXT,
    name            TEXT,
    address         TEXT,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    operator_name   TEXT,
    operator_site_id INTEGER REFERENCES operator_sites(id),
    phone           TEXT,
    price_from      NUMERIC,
    box_sizes       TEXT,                       -- свободный текст: "1-20 м³" и т.п.
    rubrics         TEXT,
    raw_json        JSONB,
    duplicate_of    INTEGER REFERENCES storages(id),  -- заполняется dedupe.py
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_storages_city ON storages (city);
CREATE INDEX IF NOT EXISTS idx_storages_category ON storages (category);
CREATE INDEX IF NOT EXISTS idx_storages_geo ON storages (lat, lon);
CREATE INDEX IF NOT EXISTS idx_storages_duplicate_of ON storages (duplicate_of);
