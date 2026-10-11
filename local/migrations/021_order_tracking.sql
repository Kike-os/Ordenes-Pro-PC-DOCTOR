CREATE TABLE order_tracking_links (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 token TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 revoked_at TEXT NOT NULL DEFAULT '',
 revoked_by INTEGER REFERENCES users(id)
);
CREATE INDEX order_tracking_links_order ON order_tracking_links(order_id,id);
