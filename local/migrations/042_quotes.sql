-- Presupuestos profesionales: catálogo de servicios y productos, presupuestos versionados por orden con estado por ítem,
-- enlaces privados de aprobación, evidencia de la aceptación del cliente e historial. Solo crea tablas nuevas: el presupuesto
-- que ya tenían las órdenes (order_budget y order_budget_lines) no se modifica.
CREATE TABLE catalog_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL CHECK(category IN ('servicio','licencia','seguridad','repuesto','otro')),
 price_cents INTEGER NOT NULL CHECK(price_cents>=0),
 taxed INTEGER NOT NULL DEFAULT 1 CHECK(taxed IN (0,1)),
 available INTEGER NOT NULL DEFAULT 1 CHECK(available IN (0,1)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE TABLE quotes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 version INTEGER NOT NULL CHECK(version>=1),
 code TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL CHECK(status IN ('borrador','enviado','aprobado','parcial','rechazado','modificacion','cancelado')),
 tax_rate_bp INTEGER NOT NULL CHECK(tax_rate_bp BETWEEN 0 AND 3000),
 valid_until TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 conditions TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 sent_at TEXT NOT NULL DEFAULT '',
 sent_to TEXT NOT NULL DEFAULT '',
 decided_at TEXT NOT NULL DEFAULT '',
 decided_by TEXT NOT NULL DEFAULT '',
 UNIQUE(order_id,version)
);
CREATE INDEX quotes_order ON quotes(order_id,version);
CREATE TABLE quote_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 quote_id INTEGER NOT NULL REFERENCES quotes(id),
 position INTEGER NOT NULL,
 catalog_id INTEGER REFERENCES catalog_items(id),
 description TEXT NOT NULL,
 category TEXT NOT NULL CHECK(category IN ('servicio','licencia','seguridad','repuesto','otro')),
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 999),
 unit_cents INTEGER NOT NULL CHECK(unit_cents>=0),
 taxed INTEGER NOT NULL CHECK(taxed IN (0,1)),
 status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','aprobado','rechazado','cancelado'))
);
CREATE INDEX quote_items_quote ON quote_items(quote_id,position);
CREATE TABLE quote_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 quote_id INTEGER NOT NULL REFERENCES quotes(id),
 actor_id INTEGER REFERENCES users(id),
 actor TEXT NOT NULL DEFAULT '',
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX quote_events_quote ON quote_events(quote_id,id);
CREATE TRIGGER quote_events_no_update BEFORE UPDATE ON quote_events BEGIN SELECT RAISE(ABORT,'El historial del presupuesto no se modifica'); END;
CREATE TRIGGER quote_events_no_delete BEFORE DELETE ON quote_events BEGIN SELECT RAISE(ABORT,'El historial del presupuesto no se elimina'); END;
CREATE TABLE quote_links (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 quote_id INTEGER NOT NULL REFERENCES quotes(id),
 token_hash TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 revoked_at TEXT NOT NULL DEFAULT '',
 verified_at TEXT NOT NULL DEFAULT '',
 passkey_hash TEXT NOT NULL DEFAULT '',
 failed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE quote_acceptances (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 quote_id INTEGER NOT NULL UNIQUE REFERENCES quotes(id),
 signer_name TEXT NOT NULL,
 method TEXT NOT NULL,
 signature TEXT NOT NULL DEFAULT '',
 evidence TEXT NOT NULL,
 evidence_hash TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TRIGGER quote_acceptances_no_update BEFORE UPDATE ON quote_acceptances BEGIN SELECT RAISE(ABORT,'La evidencia de aceptación no se modifica'); END;
CREATE TRIGGER quote_acceptances_no_delete BEFORE DELETE ON quote_acceptances BEGIN SELECT RAISE(ABORT,'La evidencia de aceptación no se elimina'); END;
