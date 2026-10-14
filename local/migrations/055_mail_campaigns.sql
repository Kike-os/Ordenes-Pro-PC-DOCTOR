-- Comunicados a clientes desde Mail Pro: campañas, destinatarios (uno por correo, sin duplicados) y bajas de comunicados.
-- Solo crea tablas nuevas: los contactos salen del registro de clientes, no se duplica ningún dato de clientes.
CREATE TABLE mail_campaigns (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 subject TEXT NOT NULL,
 body TEXT NOT NULL,
 template TEXT NOT NULL DEFAULT 'general',
 audience TEXT NOT NULL DEFAULT 'selected' CHECK(audience IN ('selected','all')),
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','queued','sending','done','cancelled')),
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 confirmed_by INTEGER REFERENCES users(id),
 confirmed_at TEXT NOT NULL DEFAULT '',
 finished_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE mail_campaign_recipients (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 campaign_id INTEGER NOT NULL REFERENCES mail_campaigns(id),
 client_id INTEGER REFERENCES clients(id),
 email TEXT NOT NULL,
 name TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent','failed','skipped')),
 delivery_id INTEGER REFERENCES mail_deliveries(id),
 detail TEXT NOT NULL DEFAULT '',
 token_hash TEXT NOT NULL DEFAULT '',
 updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX mail_campaign_recipients_once ON mail_campaign_recipients(campaign_id,email COLLATE NOCASE);
CREATE INDEX mail_campaign_recipients_status ON mail_campaign_recipients(campaign_id,status);
CREATE INDEX mail_campaign_recipients_token ON mail_campaign_recipients(token_hash);
-- Bajas: el cliente pidió no recibir más comunicados. No afecta a los correos de servicio (comprobantes, citas, presupuestos).
CREATE TABLE mail_optouts (
 email TEXT PRIMARY KEY COLLATE NOCASE,
 source TEXT NOT NULL DEFAULT 'enlace',
 created_at TEXT NOT NULL
);
