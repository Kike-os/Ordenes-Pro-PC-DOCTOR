-- Recargo por pago con tarjeta de crédito trasladado al cliente (decisión de administración del 03/11/2026), en los cobros de órdenes y de
-- ventas de licencias (en Ventas va como partida de la proforma). Cada recargo queda ligado al pago con tarjeta que lo originó y se anula
-- con él. Solo AÑADE dos tablas vacías y una columna con valor vacío; no cambia ni borra datos.
CREATE TABLE IF NOT EXISTS order_card_surcharges (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 payment_id INTEGER NOT NULL UNIQUE REFERENCES order_payments(id),
 base_cents INTEGER NOT NULL CHECK(base_cents>0),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 percent_bp INTEGER NOT NULL,
 fixed_cents INTEGER NOT NULL DEFAULT 0,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 voided_at TEXT
);
CREATE INDEX IF NOT EXISTS order_card_surcharges_order ON order_card_surcharges(order_id);
CREATE TRIGGER IF NOT EXISTS order_card_surcharges_no_delete BEFORE DELETE ON order_card_surcharges BEGIN SELECT RAISE(ABORT,'Los recargos no se eliminan: se anulan con su pago.'); END;
-- Ventas de licencias: el pago con tarjeta indica si es de crédito o de débito (vacío en los pagos anteriores).
ALTER TABLE license_sale_payments ADD COLUMN card_kind TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS license_sale_surcharges (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 sale_id INTEGER NOT NULL REFERENCES license_sales(id),
 payment_id INTEGER NOT NULL UNIQUE REFERENCES license_sale_payments(id),
 base_cents INTEGER NOT NULL CHECK(base_cents>0),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 percent_bp INTEGER NOT NULL,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 voided_at TEXT
);
CREATE INDEX IF NOT EXISTS license_sale_surcharges_sale ON license_sale_surcharges(sale_id);
CREATE TRIGGER IF NOT EXISTS license_sale_surcharges_no_delete BEFORE DELETE ON license_sale_surcharges BEGIN SELECT RAISE(ABORT,'Los recargos no se eliminan: se anulan con su pago.'); END;
