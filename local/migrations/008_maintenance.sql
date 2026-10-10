ALTER TABLE orders ADD COLUMN delivered_at TEXT NOT NULL DEFAULT '';
CREATE TABLE maintenance (
 id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
 delivered_at TEXT NOT NULL,due_date TEXT NOT NULL,profile TEXT NOT NULL DEFAULT 'office',
 state TEXT NOT NULL DEFAULT 'scheduled' CHECK(state IN ('scheduled','appointment','completed','cancelled')),
 generation INTEGER NOT NULL DEFAULT 1,consent TEXT NOT NULL DEFAULT 'unknown' CHECK(consent IN ('unknown','accepted','declined')),
 consent_at TEXT NOT NULL DEFAULT '',consent_actor INTEGER REFERENCES users(id),updated_at TEXT NOT NULL,
 unsubscribe_token TEXT NOT NULL UNIQUE
);
CREATE TABLE maintenance_notifications (
 id INTEGER PRIMARY KEY,maintenance_id INTEGER NOT NULL REFERENCES maintenance(id),generation INTEGER NOT NULL,
 channel TEXT NOT NULL CHECK(channel IN ('admin','email','whatsapp')),result TEXT NOT NULL,
 created_at TEXT NOT NULL,completed_at TEXT NOT NULL DEFAULT '',detail TEXT NOT NULL DEFAULT '',
 UNIQUE(maintenance_id,generation,channel)
);
