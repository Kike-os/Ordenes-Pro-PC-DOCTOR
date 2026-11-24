-- ADI 3.0 · fase 2: compromisos de pago. Solo crea tablas: no modifica órdenes, pagos, saldos, facturas ni vencimientos.
-- Un compromiso registra lo que el cliente aceptó (con evidencia); su cumplimiento se calcula con los pagos confirmados de la orden.
CREATE TABLE IF NOT EXISTS payment_commitments (
 id INTEGER PRIMARY KEY,
 client_id INTEGER NOT NULL REFERENCES clients(id),
 order_id INTEGER NOT NULL REFERENCES orders(id),
 invoice_id INTEGER REFERENCES invoices(id),
 balance_cents INTEGER NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
 committed_at TEXT NOT NULL,
 due_date TEXT NOT NULL,
 method TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 evidence TEXT NOT NULL,
 evidence_source TEXT NOT NULL CHECK(evidence_source IN ('presencial','telefono','mensaje','correo','whatsapp')),
 status TEXT NOT NULL DEFAULT 'activo' CHECK(status IN ('activo','reprogramado','cancelado','en_revision')),
 replaces_id INTEGER REFERENCES payment_commitments(id),
 approved_by INTEGER REFERENCES users(id),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS payment_commitments_order ON payment_commitments(order_id, id);
CREATE INDEX IF NOT EXISTS payment_commitments_due ON payment_commitments(status, due_date);
CREATE TABLE IF NOT EXISTS payment_commitment_events (
 id INTEGER PRIMARY KEY,
 commitment_id INTEGER NOT NULL REFERENCES payment_commitments(id),
 kind TEXT NOT NULL CHECK(kind IN ('registrado','reprogramado','cancelado','en_revision','revision_cerrada')),
 detail TEXT NOT NULL DEFAULT '',
 user_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS payment_commitment_events_c ON payment_commitment_events(commitment_id, id);
