-- Políticas comerciales (venta, cambios, devoluciones y garantías) con versiones, su vínculo con cada factura y el registro de envío de
-- los documentos de la factura. Solo AÑADE tablas: las facturas existentes no se modifican. No se incluye ningún texto de políticas:
-- el texto corporativo lo carga administración desde Facturación › Configuración, con su validación legal registrada.
CREATE TABLE sales_policies (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope TEXT NOT NULL CHECK(scope IN ('fisico','digital')),
 code TEXT NOT NULL CHECK(length(code) BETWEEN 2 AND 40),
 version TEXT NOT NULL CHECK(length(version) BETWEEN 1 AND 20),
 title TEXT NOT NULL CHECK(length(title) BETWEEN 5 AND 200),
 body TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'borrador' CHECK(status IN ('borrador','vigente','archivada')),
 legal_validated_by TEXT NOT NULL DEFAULT '',
 legal_validated_at TEXT NOT NULL DEFAULT '',
 published_by INTEGER REFERENCES users(id),
 published_at TEXT NOT NULL DEFAULT '',
 archived_at TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id),
 updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX sales_policies_version ON sales_policies(scope,version);
CREATE UNIQUE INDEX sales_policies_current ON sales_policies(scope) WHERE status='vigente';
-- Una versión publicada no cambia nunca (las facturas ya emitidas conservan exactamente su texto); solo puede pasar a archivada.
CREATE TRIGGER sales_policies_frozen BEFORE UPDATE ON sales_policies WHEN OLD.status!='borrador' AND (NEW.body!=OLD.body OR NEW.title!=OLD.title OR NEW.version!=OLD.version
 OR NEW.code!=OLD.code OR NEW.scope!=OLD.scope OR NEW.legal_validated_by!=OLD.legal_validated_by OR NEW.legal_validated_at!=OLD.legal_validated_at OR (OLD.status='archivada' AND NEW.status!='archivada'))
 BEGIN SELECT RAISE(ABORT,'Una versión publicada de las políticas no se modifica'); END;
CREATE TRIGGER sales_policies_no_delete BEFORE DELETE ON sales_policies WHEN OLD.status!='borrador' BEGIN SELECT RAISE(ABORT,'Las versiones publicadas de las políticas no se eliminan'); END;
-- Política vigente asociada a cada factura al emitirla (una por factura y alcance). No cambia después.
CREATE TABLE invoice_policies (
 invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 policy_id INTEGER NOT NULL REFERENCES sales_policies(id),
 scope TEXT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(invoice_id,scope)
);
CREATE TRIGGER invoice_policies_no_update BEFORE UPDATE ON invoice_policies BEGIN SELECT RAISE(ABORT,'La política asociada a una factura no cambia'); END;
CREATE TRIGGER invoice_policies_no_delete BEFORE DELETE ON invoice_policies BEGIN SELECT RAISE(ABORT,'La política asociada a una factura no se elimina'); END;
-- Envíos de los documentos de una factura: al cliente (una sola vez por factura, con reintentos controlados), reenvíos manuales y
-- pruebas a la dirección autorizada. Cada intento queda registrado con su resultado.
CREATE TABLE invoice_mail (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 kind TEXT NOT NULL CHECK(kind IN ('cliente','reenvio','prueba')),
 recipient TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('enviando','enviado','error','sin_confirmacion')),
 attempts INTEGER NOT NULL DEFAULT 1,
 attachments TEXT NOT NULL DEFAULT '[]',
 policy_id INTEGER REFERENCES sales_policies(id),
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX invoice_mail_once ON invoice_mail(invoice_id) WHERE kind='cliente';
CREATE INDEX invoice_mail_invoice ON invoice_mail(invoice_id,id);
CREATE TRIGGER invoice_mail_no_delete BEFORE DELETE ON invoice_mail BEGIN SELECT RAISE(ABORT,'El registro de envíos no se elimina'); END;
