CREATE TABLE IF NOT EXISTS order_battery_images (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    sha256 TEXT NOT NULL,
    mime TEXT NOT NULL,
    data BLOB NOT NULL,
    UNIQUE(order_id, sha256)
);

CREATE TABLE IF NOT EXISTS order_battery_revisions (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    previous_id INTEGER REFERENCES order_battery_revisions(id),
    status TEXT NOT NULL CHECK(status IN ('pendiente','evaluada','no_evaluada')),
    health_bp INTEGER CHECK(health_bp BETWEEN 0 AND 10000),
    reason TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    image_id INTEGER REFERENCES order_battery_images(id),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    CHECK((status='evaluada' AND health_bp IS NOT NULL) OR (status<>'evaluada' AND health_bp IS NULL)),
    CHECK(status<>'no_evaluada' OR length(trim(reason))>0)
);

CREATE INDEX IF NOT EXISTS order_battery_revisions_order ON order_battery_revisions(order_id, id DESC);
