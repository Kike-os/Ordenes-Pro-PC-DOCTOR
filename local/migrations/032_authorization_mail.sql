-- Constancia de los avisos de autorización enviados al correo administrativo. Un aviso por decisión registrada.
CREATE TABLE order_authorization_mail (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 consent_id INTEGER NOT NULL,
 recipient TEXT NOT NULL DEFAULT '',
 result TEXT NOT NULL CHECK(result IN ('sent','failed','not_configured')),
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX order_authorization_mail_order ON order_authorization_mail(order_id,id);
CREATE UNIQUE INDEX order_authorization_mail_once ON order_authorization_mail(order_id,consent_id) WHERE result='sent';
