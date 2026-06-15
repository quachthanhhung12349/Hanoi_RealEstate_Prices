PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS listing (
    listing_id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    source_site TEXT NOT NULL DEFAULT 'batdongsan.com.vn',
    listing_type TEXT,
    search_category TEXT,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_detail_requested_at TEXT,
    last_detail_scraped_at TEXT,
    status TEXT NOT NULL DEFAULT 'new' CHECK (
        status IN ('new', 'queued', 'done', 'failed', 'inactive')
    ),
    failure_count INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS listing_current (
    listing_id TEXT PRIMARY KEY,
    title TEXT,
    title_normalized TEXT,
    price_raw TEXT,
    price_value_vnd REAL,
    price_value_billion_vnd REAL,
    price_per_m2_raw TEXT,
    price_per_m2_value_million_vnd REAL,
    bedrooms TEXT,
    area_raw TEXT,
    area_m2 REAL,
    front_length_m REAL,
    road_size_m REAL,
    direction TEXT,
    balcony_direction TEXT,
    floors INTEGER,
    toilets INTEGER,
    legal_status TEXT,
    published_at TEXT,
    expired_at TEXT,
    ad_type TEXT,
    raw_district TEXT,
    last_scraped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    content_hash TEXT,
    FOREIGN KEY (listing_id) REFERENCES listing (listing_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS address (
    listing_id TEXT PRIMARY KEY,
    full_address TEXT,
    address_line_1 TEXT,
    address_line_2 TEXT,
    ward TEXT,
    district TEXT,
    city TEXT,
    latitude REAL,
    longitude REAL,
    location_source TEXT,
    last_geocoded_at TEXT,
    FOREIGN KEY (listing_id) REFERENCES listing (listing_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS listing_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT NOT NULL,
    scraped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    price_raw TEXT,
    price_value_vnd REAL,
    price_per_m2_raw TEXT,
    price_per_m2_value_million_vnd REAL,
    expired_at TEXT,
    ad_type TEXT,
    is_active INTEGER CHECK (is_active IN (0, 1)),
    content_hash TEXT,
    FOREIGN KEY (listing_id) REFERENCES listing (listing_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scrape_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT,
    stage TEXT NOT NULL CHECK (stage IN ('discover', 'detail', 'parse', 'dashboard')),
    error_type TEXT,
    error_message TEXT,
    happened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    retryable INTEGER NOT NULL DEFAULT 1 CHECK (retryable IN (0, 1)),
    FOREIGN KEY (listing_id) REFERENCES listing (listing_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_listing_status ON listing (status);
CREATE INDEX IF NOT EXISTS idx_listing_active_status ON listing (is_active, status);
CREATE INDEX IF NOT EXISTS idx_listing_last_seen ON listing (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_listing_last_scraped ON listing (last_detail_scraped_at);
CREATE INDEX IF NOT EXISTS idx_listing_current_published_at ON listing_current (published_at);
CREATE INDEX IF NOT EXISTS idx_listing_current_expired_at ON listing_current (expired_at);
CREATE INDEX IF NOT EXISTS idx_address_district ON address (district);
CREATE INDEX IF NOT EXISTS idx_address_city ON address (city);
CREATE INDEX IF NOT EXISTS idx_address_lat_lon ON address (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_history_listing_scraped ON listing_history (listing_id, scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_errors_stage_time ON scrape_errors (stage, happened_at DESC);

CREATE VIEW IF NOT EXISTS listing_dashboard_view AS
SELECT
    l.listing_id,
    l.url,
    l.status,
    l.is_active,
    l.first_seen_at,
    l.last_seen_at,
    lc.title,
    lc.price_value_billion_vnd,
    lc.price_per_m2_value_million_vnd,
    lc.area_m2,
    lc.direction,
    lc.legal_status,
    lc.published_at,
    lc.expired_at,
    a.full_address,
    a.district,
    a.city,
    a.latitude,
    a.longitude
FROM listing l
LEFT JOIN listing_current lc ON lc.listing_id = l.listing_id
LEFT JOIN address a ON a.listing_id = l.listing_id;
