-- Inventario de Licencias Digitales. Solo crea tablas nuevas: el catálogo, los presupuestos, los pagos y las órdenes no se modifican.
-- Producto = elemento del catálogo (categoría «licencia» o «seguridad», con su logo en catalog_images). Debajo, una unidad por cada
-- cuenta o serial, con su estado. Las credenciales se guardan cifradas (clave fuera de la base) y nunca en claro.
CREATE TABLE license_products (
 item_id INTEGER PRIMARY KEY REFERENCES catalog_items(id),
 kind TEXT NOT NULL CHECK(kind IN ('m365','windows_office','antivirus','otro')),
 supplier TEXT NOT NULL DEFAULT '',
 purchase_cents INTEGER CHECK(purchase_cents IS NULL OR purchase_cents>=0),
 term TEXT NOT NULL DEFAULT '',
 devices INTEGER CHECK(devices IS NULL OR devices BETWEEN 1 AND 1000),
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE TABLE license_batches (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL REFERENCES catalog_items(id),
 supplier TEXT NOT NULL DEFAULT '',
 unit_cost_cents INTEGER CHECK(unit_cost_cents IS NULL OR unit_cost_cents>=0),
 purchased_at TEXT NOT NULL DEFAULT '',
 invoice TEXT NOT NULL DEFAULT '',
 quantity INTEGER NOT NULL CHECK(quantity>=1),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE TABLE license_deliveries (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 client_id INTEGER REFERENCES clients(id),
 status TEXT NOT NULL CHECK(status IN ('pago_confirmado','autorizada','anulada')),
 payment_confirmed_by INTEGER NOT NULL REFERENCES users(id),
 payment_confirmed_at TEXT NOT NULL,
 balance_cents INTEGER NOT NULL,
 authorized_by INTEGER REFERENCES users(id),
 authorized_at TEXT NOT NULL DEFAULT '',
 token_hash TEXT UNIQUE,
 token_expires_at TEXT NOT NULL DEFAULT '',
 code_hash TEXT NOT NULL DEFAULT '',
 code_expires_at TEXT NOT NULL DEFAULT '',
 code_failures INTEGER NOT NULL DEFAULT 0,
 reveal_count INTEGER NOT NULL DEFAULT 0,
 last_revealed_at TEXT NOT NULL DEFAULT '',
 voided_by INTEGER REFERENCES users(id),
 voided_at TEXT NOT NULL DEFAULT '',
 void_reason TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX license_deliveries_order ON license_deliveries(order_id,id);
CREATE TABLE license_units (
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
 secret TEXT NOT NULL CHECK(secret LIKE 'lic1:%'),
 fingerprint TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'disponible' CHECK(status IN ('disponible','reservada','entregada','anulada','vencida')),
 activated INTEGER NOT NULL DEFAULT 0 CHECK(activated IN (0,1)),
 quote_id INTEGER REFERENCES quotes(id),
 quote_item_id INTEGER REFERENCES quote_items(id),
 order_id INTEGER REFERENCES orders(id),
 client_id INTEGER REFERENCES clients(id),
 delivery_id INTEGER REFERENCES license_deliveries(id),
 reserved_at TEXT NOT NULL DEFAULT '',
 delivered_at TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 CHECK(status NOT IN ('reservada','entregada') OR (quote_item_id IS NOT NULL AND order_id IS NOT NULL))
);
CREATE INDEX license_units_product ON license_units(product_id,status,id);
CREATE INDEX license_units_item ON license_units(quote_item_id,status);
CREATE INDEX license_units_order ON license_units(order_id,status);
CREATE TRIGGER license_units_code_assign AFTER INSERT ON license_units WHEN NEW.code IS NULL
 BEGIN UPDATE license_units SET code='LIC-'||printf('%06d',NEW.id) WHERE id=NEW.id; END;
CREATE TRIGGER license_units_no_delete BEFORE DELETE ON license_units
 BEGIN SELECT RAISE(ABORT,'Las licencias no se eliminan: se anulan'); END;
-- Una licencia entregada no vuelve a venderse ni cambia de cliente, credenciales o estado.
CREATE TRIGGER license_units_delivered_fixed BEFORE UPDATE ON license_units
 WHEN OLD.status='entregada' AND (NEW.status!='entregada' OR NEW.secret!=OLD.secret OR NEW.fingerprint!=OLD.fingerprint OR NEW.client_id IS NOT OLD.client_id
  OR NEW.order_id IS NOT OLD.order_id OR NEW.quote_item_id IS NOT OLD.quote_item_id OR NEW.product_id!=OLD.product_id)
 BEGIN SELECT RAISE(ABORT,'Una licencia entregada no se modifica'); END;
CREATE TRIGGER license_units_void_final BEFORE UPDATE OF status ON license_units WHEN OLD.status='anulada' AND NEW.status!='anulada'
 BEGIN SELECT RAISE(ABORT,'Una licencia anulada no vuelve al inventario'); END;
CREATE TABLE license_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 unit_id INTEGER REFERENCES license_units(id),
 product_id INTEGER REFERENCES catalog_items(id),
 delivery_id INTEGER REFERENCES license_deliveries(id),
 order_id INTEGER REFERENCES orders(id),
 client_id INTEGER REFERENCES clients(id),
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 actor TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX license_events_unit ON license_events(unit_id,id);
CREATE INDEX license_events_delivery ON license_events(delivery_id,id);
CREATE TRIGGER license_events_fixed BEFORE UPDATE ON license_events BEGIN SELECT RAISE(ABORT,'El historial de licencias no se modifica'); END;
CREATE TRIGGER license_events_no_delete BEFORE DELETE ON license_events BEGIN SELECT RAISE(ABORT,'El historial de licencias no se elimina'); END;
