-- Venta de licencias: precio, descuento autorizado y estado de pago INFORMATIVO de cada entrega (no confirma pagos ni toca la caja).
-- Centro de notificaciones: avisos ocultos por cada persona (no se borra nada; se pueden volver a mostrar desde el historial).
ALTER TABLE license_deliveries ADD COLUMN price_cents INTEGER CHECK(price_cents IS NULL OR price_cents>=0);
ALTER TABLE license_deliveries ADD COLUMN discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents>=0);
ALTER TABLE license_deliveries ADD COLUMN payment_status TEXT NOT NULL DEFAULT '' CHECK(payment_status IN ('','pagado','parcial','pendiente','incluido'));
CREATE TABLE notification_hidden (
 user_id INTEGER NOT NULL REFERENCES users(id),
 key TEXT NOT NULL,
 hidden_at TEXT NOT NULL,
 PRIMARY KEY(user_id,key)
);
