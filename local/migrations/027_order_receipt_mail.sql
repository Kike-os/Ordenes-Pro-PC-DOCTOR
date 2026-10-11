CREATE TABLE order_receipt_mail (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 mode TEXT NOT NULL CHECK(mode IN ('auto','manual')),
 recipient TEXT NOT NULL DEFAULT '',
 result TEXT NOT NULL CHECK(result IN ('sent','failed','no_email','not_configured')),
 detail TEXT NOT NULL DEFAULT '',
 document_sha256 TEXT NOT NULL DEFAULT '',
 policies_version TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX order_receipt_mail_order ON order_receipt_mail(order_id,id);
