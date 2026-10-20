-- Ventas de licencias independientes de las órdenes técnicas: pedido con número propio (VLIC-AAAAMMDD-0001), carrito de varios productos,
-- pagos (completos, parciales o por confirmar, con comprobante) y entrega. El estado comercial (pago) y el de entrega van por separado.
-- Solo añade tablas y dos columnas: no cambia ninguna licencia, cliente, orden ni entrega existente.
CREATE TABLE license_sales (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL UNIQUE,
 client_id INTEGER NOT NULL REFERENCES clients(id),
 order_id INTEGER REFERENCES orders(id),
 payment_status TEXT NOT NULL DEFAULT 'pendiente' CHECK(payment_status IN ('pendiente','parcial','pagado','cancelado')),
 delivery_status TEXT NOT NULL DEFAULT 'pendiente' CHECK(delivery_status IN ('pendiente','entregado','cancelado')),
 subtotal_cents INTEGER NOT NULL CHECK(subtotal_cents>=0),
 discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents>=0),
 total_cents INTEGER NOT NULL CHECK(total_cents>=0),
 notes TEXT NOT NULL DEFAULT '',
 delivery_id INTEGER REFERENCES license_deliveries(id),
 delivered_at TEXT NOT NULL DEFAULT '',
 delivered_by INTEGER REFERENCES users(id),
 cancelled_at TEXT NOT NULL DEFAULT '',
 cancelled_by INTEGER REFERENCES users(id),
 cancel_reason TEXT NOT NULL DEFAULT '',
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 CHECK(discount_cents<=subtotal_cents AND total_cents=subtotal_cents-discount_cents)
);
CREATE INDEX license_sales_client ON license_sales(client_id,id);
CREATE INDEX license_sales_created ON license_sales(created_at);

CREATE TABLE license_sale_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 sale_id INTEGER NOT NULL REFERENCES license_sales(id),
 product_id INTEGER NOT NULL REFERENCES catalog_items(id),
 product_name TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 50),
 unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents>=0),
 discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents>=0 AND discount_cents<=unit_price_cents*quantity),
 position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX license_sale_items_sale ON license_sale_items(sale_id,position);

-- Cada clave queda ligada a la venta y a la partida que la reservó o la recibió.
ALTER TABLE license_units ADD COLUMN sale_id INTEGER REFERENCES license_sales(id);
ALTER TABLE license_units ADD COLUMN sale_item_id INTEGER REFERENCES license_sale_items(id);
CREATE INDEX license_units_sale ON license_units(sale_id,status);

-- Pagos: solo los confirmados cuentan para el estado «Pagado». Un pago no se borra ni cambia de importe: se anula con motivo.
CREATE TABLE license_sale_payments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 sale_id INTEGER NOT NULL REFERENCES license_sales(id),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 method TEXT NOT NULL CHECK(method IN ('efectivo','transferencia','deposito','tarjeta','otro')),
 reference TEXT NOT NULL DEFAULT '',
 paid_on TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('por_confirmar','confirmado','anulado')),
 notes TEXT NOT NULL DEFAULT '',
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 confirmed_by INTEGER REFERENCES users(id),
 confirmed_at TEXT NOT NULL DEFAULT '',
 voided_by INTEGER REFERENCES users(id),
 voided_at TEXT NOT NULL DEFAULT '',
 void_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX license_sale_payments_sale ON license_sale_payments(sale_id,id);
CREATE TRIGGER license_sale_payments_fixed BEFORE UPDATE ON license_sale_payments
 WHEN NEW.amount_cents!=OLD.amount_cents OR NEW.method!=OLD.method OR NEW.sale_id!=OLD.sale_id OR NEW.paid_on!=OLD.paid_on OR OLD.status='anulado'
  OR (OLD.status='confirmado' AND NEW.status NOT IN ('confirmado','anulado'))
 BEGIN SELECT RAISE(ABORT,'Un pago registrado no se modifica: se anula con motivo'); END;
CREATE TRIGGER license_sale_payments_no_delete BEFORE DELETE ON license_sale_payments BEGIN SELECT RAISE(ABORT,'Los pagos no se eliminan'); END;

-- Comprobante del pago (transferencia o depósito): JPG, PNG o PDF, solo para administración.
CREATE TABLE license_payment_receipts (
 payment_id INTEGER PRIMARY KEY REFERENCES license_sale_payments(id),
 name TEXT NOT NULL DEFAULT '',
 mime TEXT NOT NULL CHECK(mime IN ('application/pdf','image/png','image/jpeg')),
 data BLOB NOT NULL,
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id)
);

-- Historial de cada venta (creación, pagos, entrega, cancelación): no se modifica ni se elimina.
CREATE TABLE license_sale_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 sale_id INTEGER NOT NULL REFERENCES license_sales(id),
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX license_sale_events_sale ON license_sale_events(sale_id,id);
CREATE TRIGGER license_sale_events_fixed BEFORE UPDATE ON license_sale_events BEGIN SELECT RAISE(ABORT,'El historial de ventas no se modifica'); END;
CREATE TRIGGER license_sale_events_no_delete BEFORE DELETE ON license_sale_events BEGIN SELECT RAISE(ABORT,'El historial de ventas no se elimina'); END;
CREATE TRIGGER license_sales_no_delete BEFORE DELETE ON license_sales BEGIN SELECT RAISE(ABORT,'Las ventas no se eliminan: se cancelan'); END;
CREATE TRIGGER license_sale_items_fixed BEFORE UPDATE ON license_sale_items BEGIN SELECT RAISE(ABORT,'Las partidas de una venta no se modifican'); END;
CREATE TRIGGER license_sale_items_no_delete BEFORE DELETE ON license_sale_items BEGIN SELECT RAISE(ABORT,'Las partidas de una venta no se eliminan'); END;
