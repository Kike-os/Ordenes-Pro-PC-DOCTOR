CREATE TABLE IF NOT EXISTS order_battery_diagnostics (
    revision_id INTEGER PRIMARY KEY REFERENCES order_battery_revisions(id) ON DELETE CASCADE,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    battery_key TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_battery_diagnostics_order
    ON order_battery_diagnostics(order_id, battery_key, revision_id);
