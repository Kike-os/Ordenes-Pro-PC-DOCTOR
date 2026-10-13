-- Servicio «Retiro de Equipos» (15 minutos, editable en la configuración de la agenda) y vínculo opcional de la cita con la orden a retirar.
-- Origen del cliente (por ejemplo, registrado desde una cita). Solo añade un servicio y columnas: lo existente no cambia.
INSERT OR IGNORE INTO appointment_services(code,label,duration_minutes,active) VALUES ('retiro','Retiro de Equipos',15,1);
ALTER TABLE appointments ADD COLUMN pickup_order_id INTEGER REFERENCES orders(id);
ALTER TABLE clients ADD COLUMN origin TEXT NOT NULL DEFAULT '';
