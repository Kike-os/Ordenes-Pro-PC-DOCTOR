-- Licencias Pro: productos con línea, edición y modalidad; unidades con datos de activación (enlace e instrucciones); venta directa a un
-- cliente (con o sin orden), devoluciones autorizadas y comprobante de compra. Las tres tablas de unidades, entregas e historial se
-- reconstruyen para relajar restricciones (una entrega ya no exige orden); los registros existentes se copian tal cual.
ALTER TABLE license_products ADD COLUMN line TEXT NOT NULL DEFAULT 'otros' CHECK(line IN ('antivirus','microsoft','sistema','ofimatica','utilitarios','otros'));
ALTER TABLE license_products ADD COLUMN model TEXT NOT NULL DEFAULT 'otra' CHECK(model IN ('suscripcion','perpetua','otra'));
ALTER TABLE license_products ADD COLUMN edition TEXT NOT NULL DEFAULT '';
-- Vigencia: duración (mensual, anual, bianual, trianual, perpetua o personalizada en meses) y desde cuándo se cuenta: la activación real,
-- la compra o una fecha fija indicada por el proveedor. Clave compartida: cuántos clientes pueden recibir la misma clave (0 = ninguno).
ALTER TABLE license_products ADD COLUMN duration TEXT NOT NULL DEFAULT 'anual' CHECK(duration IN ('mensual','anual','bianual','trianual','perpetua','personalizada'));
ALTER TABLE license_products ADD COLUMN duration_months INTEGER CHECK(duration_months IS NULL OR duration_months BETWEEN 1 AND 120);
ALTER TABLE license_products ADD COLUMN validity_mode TEXT NOT NULL DEFAULT 'activacion' CHECK(validity_mode IN ('activacion','compra','fija'));
ALTER TABLE license_products ADD COLUMN shared_seats INTEGER NOT NULL DEFAULT 0 CHECK(shared_seats BETWEEN 0 AND 100);
UPDATE license_products SET line=CASE kind WHEN 'antivirus' THEN 'antivirus' WHEN 'm365' THEN 'microsoft' WHEN 'windows_office' THEN 'microsoft' ELSE 'otros' END;

CREATE TABLE license_deliveries_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER REFERENCES orders(id),
 client_id INTEGER REFERENCES clients(id),
 kind TEXT NOT NULL DEFAULT 'orden' CHECK(kind IN ('orden','directa')),
 status TEXT NOT NULL CHECK(status IN ('pago_confirmado','autorizada','anulada')),
 payment_confirmed_by INTEGER NOT NULL REFERENCES users(id),
 payment_confirmed_at TEXT NOT NULL,
 balance_cents INTEGER NOT NULL DEFAULT 0,
 authorized_by INTEGER REFERENCES users(id),
 authorized_at TEXT NOT NULL DEFAULT '',
 token_hash TEXT UNIQUE,
 token_expires_at TEXT NOT NULL DEFAULT '',
 code_hash TEXT NOT NULL DEFAULT '',
 code_expires_at TEXT NOT NULL DEFAULT '',
 code_failures INTEGER NOT NULL DEFAULT 0,
 reveal_count INTEGER NOT NULL DEFAULT 0,
 last_revealed_at TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 voided_by INTEGER REFERENCES users(id),
 voided_at TEXT NOT NULL DEFAULT '',
 void_reason TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 CHECK(order_id IS NOT NULL OR client_id IS NOT NULL)
);
INSERT INTO license_deliveries_new(id,order_id,client_id,kind,status,payment_confirmed_by,payment_confirmed_at,balance_cents,authorized_by,authorized_at,token_hash,token_expires_at,code_hash,code_expires_at,code_failures,reveal_count,last_revealed_at,voided_by,voided_at,void_reason,created_at,updated_at)
 SELECT id,order_id,client_id,'orden',status,payment_confirmed_by,payment_confirmed_at,balance_cents,authorized_by,authorized_at,token_hash,token_expires_at,code_hash,code_expires_at,code_failures,reveal_count,last_revealed_at,voided_by,voided_at,void_reason,created_at,updated_at FROM license_deliveries;

CREATE TABLE license_units_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT UNIQUE,
 product_id INTEGER NOT NULL REFERENCES catalog_items(id),
 batch_id INTEGER REFERENCES license_batches(id),
 kind TEXT NOT NULL CHECK(kind IN ('m365','windows_office','antivirus','otro')),
 edition TEXT NOT NULL DEFAULT '',
 license_type TEXT NOT NULL DEFAULT '',
 manufacturer TEXT NOT NULL DEFAULT '',
 version TEXT NOT NULL DEFAULT '',
 devices INTEGER CHECK(devices IS NULL OR devices BETWEEN 1 AND 1000),
 term TEXT NOT NULL DEFAULT '',
 purchased_at TEXT NOT NULL DEFAULT '',
 activated_at TEXT NOT NULL DEFAULT '',
 expires_at TEXT NOT NULL DEFAULT '',
 download_url TEXT NOT NULL DEFAULT '',
 instructions TEXT NOT NULL DEFAULT '',
 seat INTEGER NOT NULL DEFAULT 1,
 renewed_from INTEGER REFERENCES license_units_new(id),
 renewed_to INTEGER REFERENCES license_units_new(id),
 secret TEXT NOT NULL CHECK(secret LIKE 'lic1:%'),
 fingerprint TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'disponible' CHECK(status IN ('disponible','reservada','entregada','anulada','vencida')),
 activated INTEGER NOT NULL DEFAULT 0 CHECK(activated IN (0,1)),
 quote_id INTEGER REFERENCES quotes(id),
 quote_item_id INTEGER REFERENCES quote_items(id),
 order_id INTEGER REFERENCES orders(id),
 client_id INTEGER REFERENCES clients(id),
 delivery_id INTEGER REFERENCES license_deliveries_new(id),
 reserved_at TEXT NOT NULL DEFAULT '',
 delivered_at TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 CHECK(status NOT IN ('reservada','entregada') OR client_id IS NOT NULL OR order_id IS NOT NULL)
);
INSERT INTO license_units_new(id,code,product_id,batch_id,kind,edition,license_type,manufacturer,version,devices,term,purchased_at,activated_at,expires_at,secret,fingerprint,status,activated,quote_id,quote_item_id,order_id,client_id,delivery_id,reserved_at,delivered_at,notes,created_by,created_at,updated_at)
 SELECT id,code,product_id,batch_id,kind,edition,license_type,manufacturer,version,devices,term,purchased_at,activated_at,expires_at,secret,fingerprint,status,activated,quote_id,quote_item_id,order_id,client_id,delivery_id,reserved_at,delivered_at,notes,created_by,created_at,updated_at FROM license_units;

CREATE TABLE license_events_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 unit_id INTEGER REFERENCES license_units_new(id),
 product_id INTEGER REFERENCES catalog_items(id),
 delivery_id INTEGER REFERENCES license_deliveries_new(id),
 order_id INTEGER REFERENCES orders(id),
 client_id INTEGER REFERENCES clients(id),
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 actor TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
INSERT INTO license_events_new SELECT id,unit_id,product_id,delivery_id,order_id,client_id,event,detail,actor_id,actor,created_at FROM license_events;

DROP TABLE license_events;
DROP TABLE license_units;
DROP TABLE license_deliveries;
ALTER TABLE license_deliveries_new RENAME TO license_deliveries;
ALTER TABLE license_units_new RENAME TO license_units;
ALTER TABLE license_events_new RENAME TO license_events;

CREATE INDEX license_deliveries_order ON license_deliveries(order_id,id);
CREATE INDEX license_deliveries_client ON license_deliveries(client_id,id);
CREATE INDEX license_units_product ON license_units(product_id,status,id);
CREATE INDEX license_units_item ON license_units(quote_item_id,status);
CREATE INDEX license_units_order ON license_units(order_id,status);
CREATE INDEX license_units_client ON license_units(client_id,status);
CREATE INDEX license_events_unit ON license_events(unit_id,id);
CREATE INDEX license_events_delivery ON license_events(delivery_id,id);
CREATE TRIGGER license_units_code_assign AFTER INSERT ON license_units WHEN NEW.code IS NULL
 BEGIN UPDATE license_units SET code='LIC-'||printf('%06d',NEW.id) WHERE id=NEW.id; END;
CREATE TRIGGER license_units_no_delete BEFORE DELETE ON license_units
 BEGIN SELECT RAISE(ABORT,'Las licencias no se eliminan: se anulan'); END;
-- Una licencia entregada no vuelve a venderse ni cambia de cliente, credenciales o producto. Solo puede anularse (devolución autorizada)
-- o marcarse como activada.
CREATE TRIGGER license_units_delivered_fixed BEFORE UPDATE ON license_units
 WHEN OLD.status='entregada' AND (NEW.status NOT IN ('entregada','anulada') OR NEW.secret!=OLD.secret OR NEW.fingerprint!=OLD.fingerprint OR NEW.client_id IS NOT OLD.client_id
  OR NEW.order_id IS NOT OLD.order_id OR NEW.quote_item_id IS NOT OLD.quote_item_id OR NEW.product_id!=OLD.product_id)
 BEGIN SELECT RAISE(ABORT,'Una licencia entregada no se modifica'); END;
CREATE TRIGGER license_units_void_final BEFORE UPDATE OF status ON license_units WHEN OLD.status='anulada' AND NEW.status!='anulada'
 BEGIN SELECT RAISE(ABORT,'Una licencia anulada no vuelve al inventario'); END;
CREATE TRIGGER license_events_fixed BEFORE UPDATE ON license_events BEGIN SELECT RAISE(ABORT,'El historial de licencias no se modifica'); END;
CREATE TRIGGER license_events_no_delete BEFORE DELETE ON license_events BEGIN SELECT RAISE(ABORT,'El historial de licencias no se elimina'); END;

-- Comprobante de compra de un lote (PDF o imagen), privado: solo administración lo descarga.
CREATE TABLE license_receipts (
 batch_id INTEGER PRIMARY KEY REFERENCES license_batches(id),
 name TEXT NOT NULL DEFAULT '',
 mime TEXT NOT NULL CHECK(mime IN ('application/pdf','image/png','image/jpeg','image/webp')),
 data BLOB NOT NULL,
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id)
);

-- Renovaciones: cada una queda registrada con el período anterior y el nuevo; la licencia anterior nunca se borra.
CREATE TABLE license_renewals (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 unit_id INTEGER NOT NULL REFERENCES license_units(id),
 new_unit_id INTEGER REFERENCES license_units(id),
 client_id INTEGER REFERENCES clients(id),
 previous_expires_at TEXT NOT NULL DEFAULT '',
 starts_at TEXT NOT NULL,
 expires_at TEXT NOT NULL DEFAULT '',
 duration TEXT NOT NULL,
 duration_months INTEGER,
 cost_cents INTEGER CHECK(cost_cents IS NULL OR cost_cents>=0),
 price_cents INTEGER CHECK(price_cents IS NULL OR price_cents>=0),
 key_changed INTEGER NOT NULL DEFAULT 0 CHECK(key_changed IN (0,1)),
 notes TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX license_renewals_unit ON license_renewals(unit_id,id);
CREATE TRIGGER license_renewals_fixed BEFORE UPDATE ON license_renewals BEGIN SELECT RAISE(ABORT,'El historial de renovaciones no se modifica'); END;
CREATE TRIGGER license_renewals_no_delete BEFORE DELETE ON license_renewals BEGIN SELECT RAISE(ABORT,'El historial de renovaciones no se elimina'); END;
-- Avisos de vencimiento ya emitidos (30, 15, 7 y 1 días antes y el día del vencimiento): uno por licencia, fecha y anticipación.
CREATE TABLE license_alerts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 unit_id INTEGER NOT NULL REFERENCES license_units(id),
 expires_at TEXT NOT NULL,
 days INTEGER NOT NULL CHECK(days IN (30,15,7,1,0)),
 mail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 UNIQUE(unit_id,expires_at,days)
);
-- Notificaciones de renovación a clientes: una por licencia, vencimiento y anticipación (sin duplicados), con su resultado real.
-- El estado de entrega (aceptado por el servidor, entregado, rebotado) sale del seguimiento de correos vinculado (archive_id).
CREATE TABLE license_notices (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 unit_id INTEGER NOT NULL REFERENCES license_units(id),
 client_id INTEGER REFERENCES clients(id),
 expires_at TEXT NOT NULL,
 days INTEGER NOT NULL CHECK(days BETWEEN 0 AND 90),
 recipient TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','enviado','error','omitido','cancelado')),
 attempts INTEGER NOT NULL DEFAULT 0,
 last_error TEXT NOT NULL DEFAULT '',
 archive_id INTEGER REFERENCES mail_archive(id),
 manual INTEGER NOT NULL DEFAULT 0 CHECK(manual IN (0,1)),
 created_at TEXT NOT NULL,
 sent_at TEXT NOT NULL DEFAULT '',
 next_retry_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX license_notices_once ON license_notices(unit_id,expires_at,days) WHERE manual=0;
CREATE INDEX license_notices_recent ON license_notices(id);
-- Clientes que no desean recibir avisos de renovación por correo.
CREATE TABLE license_notice_optout (
 client_id INTEGER PRIMARY KEY REFERENCES clients(id),
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id)
);
