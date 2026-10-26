-- Facturación electrónica (SRI, esquema offline). Solo añade tablas: no modifica clientes, órdenes, presupuestos, pagos ni licencias.
-- Configuración fiscal de la empresa: una sola fila. La emisión empieza desactivada y en ambiente de pruebas (1).
CREATE TABLE invoice_settings (
 id INTEGER PRIMARY KEY CHECK(id=1),
 ruc TEXT NOT NULL DEFAULT '',
 legal_name TEXT NOT NULL DEFAULT '',
 trade_name TEXT NOT NULL DEFAULT '',
 head_office_address TEXT NOT NULL DEFAULT '',
 branch_address TEXT NOT NULL DEFAULT '',
 establishment TEXT NOT NULL DEFAULT '001' CHECK(length(establishment)=3),
 emission_point TEXT NOT NULL DEFAULT '001' CHECK(length(emission_point)=3),
 keeps_accounts TEXT NOT NULL DEFAULT '' CHECK(keeps_accounts IN ('','SI','NO')),
 special_taxpayer TEXT NOT NULL DEFAULT '',
 regime TEXT NOT NULL DEFAULT '' CHECK(regime IN ('','general','rimpe_emprendedor','rimpe_negocio_popular')),
 withholding_agent TEXT NOT NULL DEFAULT '',
 environment TEXT NOT NULL DEFAULT '1' CHECK(environment IN ('1','2')),
 updated_at TEXT NOT NULL DEFAULT '',
 updated_by INTEGER REFERENCES users(id)
);
INSERT INTO invoice_settings(id) VALUES (1);
-- Secuenciales por ambiente, establecimiento, punto de emisión y tipo de comprobante: nunca se repiten ni retroceden.
CREATE TABLE invoice_sequences (
 environment TEXT NOT NULL,
 establishment TEXT NOT NULL,
 emission_point TEXT NOT NULL,
 doc_type TEXT NOT NULL,
 last_number INTEGER NOT NULL DEFAULT 0 CHECK(last_number>=0),
 PRIMARY KEY(environment,establishment,emission_point,doc_type)
);
-- Comprobantes. Un borrador no tiene número; el secuencial y la clave de acceso se asignan al confirmar la emisión.
CREATE TABLE invoices (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 doc_type TEXT NOT NULL DEFAULT '01',
 status TEXT NOT NULL DEFAULT 'borrador' CHECK(status IN ('borrador','pendiente','enviado','autorizado','rechazado','descartado')),
 environment TEXT NOT NULL DEFAULT '1' CHECK(environment IN ('1','2')),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('orden','venta_licencia')),
 source_id INTEGER NOT NULL,
 order_id INTEGER REFERENCES orders(id),
 quote_id INTEGER REFERENCES quotes(id),
 license_sale_id INTEGER REFERENCES license_sales(id),
 client_id INTEGER REFERENCES clients(id),
 buyer_id_type TEXT NOT NULL DEFAULT '' CHECK(buyer_id_type IN ('','04','05','06','07','08')),
 buyer_id TEXT NOT NULL DEFAULT '',
 buyer_name TEXT NOT NULL DEFAULT '',
 buyer_address TEXT NOT NULL DEFAULT '',
 buyer_email TEXT NOT NULL DEFAULT '',
 buyer_phone TEXT NOT NULL DEFAULT '',
 consumer_final INTEGER NOT NULL DEFAULT 0 CHECK(consumer_final IN (0,1)),
 subtotal_cents INTEGER NOT NULL DEFAULT 0,
 discount_cents INTEGER NOT NULL DEFAULT 0,
 tax_cents INTEGER NOT NULL DEFAULT 0,
 total_cents INTEGER NOT NULL DEFAULT 0,
 establishment TEXT NOT NULL DEFAULT '',
 emission_point TEXT NOT NULL DEFAULT '',
 sequential INTEGER,
 access_key TEXT UNIQUE,
 issue_date TEXT NOT NULL DEFAULT '',
 authorization_number TEXT NOT NULL DEFAULT '',
 authorized_at TEXT NOT NULL DEFAULT '',
 sri_messages TEXT NOT NULL DEFAULT '[]',
 xml_unsigned TEXT NOT NULL DEFAULT '',
 xml_signed TEXT NOT NULL DEFAULT '',
 xml_authorized TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 emitted_by INTEGER REFERENCES users(id),
 emitted_at TEXT NOT NULL DEFAULT '',
 UNIQUE(environment,establishment,emission_point,doc_type,sequential)
);
-- Una sola factura vigente por operación (orden o venta): un borrador descartado no cuenta.
CREATE UNIQUE INDEX invoices_one_per_source ON invoices(source_kind,source_id,environment) WHERE status!='descartado';
CREATE INDEX invoices_status ON invoices(status,created_at);
CREATE TABLE invoice_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 position INTEGER NOT NULL,
 code TEXT NOT NULL,
 description TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_price_micros INTEGER NOT NULL CHECK(unit_price_micros>=0),
 discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents>=0),
 base_cents INTEGER NOT NULL CHECK(base_cents>=0),
 tax_code TEXT NOT NULL,
 tax_rate_bp INTEGER NOT NULL,
 tax_cents INTEGER NOT NULL CHECK(tax_cents>=0),
 total_cents INTEGER NOT NULL,
 source_item_id INTEGER,
 catalog_id INTEGER
);
CREATE TABLE invoice_payments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 method TEXT NOT NULL,
 sri_code TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0)
);
-- Historial inmutable: quién creó, revisó, emitió y qué respondió el SRI.
CREATE TABLE invoice_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 actor TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE TRIGGER invoice_events_no_update BEFORE UPDATE ON invoice_events BEGIN SELECT RAISE(ABORT,'El historial de facturación no se modifica'); END;
CREATE TRIGGER invoice_events_no_delete BEFORE DELETE ON invoice_events BEGIN SELECT RAISE(ABORT,'El historial de facturación no se elimina'); END;
-- Un comprobante autorizado no se modifica ni se elimina (solo se anula o corrige con los documentos que el SRI admite).
CREATE TRIGGER invoices_authorized_locked BEFORE UPDATE ON invoices WHEN OLD.status='autorizado' BEGIN SELECT RAISE(ABORT,'Un comprobante autorizado no se modifica'); END;
CREATE TRIGGER invoices_no_delete BEFORE DELETE ON invoices BEGIN SELECT RAISE(ABORT,'Los comprobantes no se eliminan'); END;
CREATE TRIGGER invoice_items_locked BEFORE UPDATE ON invoice_items WHEN (SELECT status FROM invoices WHERE id=OLD.invoice_id) NOT IN ('borrador') BEGIN SELECT RAISE(ABORT,'Las partidas de un comprobante emitido no se modifican'); END;
CREATE TRIGGER invoice_items_no_delete BEFORE DELETE ON invoice_items WHEN (SELECT status FROM invoices WHERE id=OLD.invoice_id) NOT IN ('borrador') BEGIN SELECT RAISE(ABORT,'Las partidas de un comprobante emitido no se eliminan'); END;
