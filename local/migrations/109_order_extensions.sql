-- 1.5.294 · Prórrogas del plazo de retiro (permanencia en taller). Solo crea tablas nuevas (vacías); no cambia ni borra datos existentes.
-- Una prórroga nunca sobrescribe a otra: la nueva queda «vigente» y la anterior pasa a «reemplazada»; revocar también es un cambio de
-- estado con su motivo. Los datos de origen (plazo anterior, nuevo plazo, días, motivo, responsable, quién y cuándo) no se editan.
-- No toca la orden (número, estado, firmas, documentos, presupuestos) ni ningún cobro: el plazo efectivo se calcula al consultarlo.
CREATE TABLE IF NOT EXISTS order_extensions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 original_due TEXT NOT NULL,
 previous_due TEXT NOT NULL,
 new_due TEXT NOT NULL,
 days INTEGER NOT NULL CHECK(days BETWEEN 1 AND 365),
 reason_code TEXT NOT NULL CHECK(reason_code IN ('cliente_solicita','espera_pago','viaje_cliente','espera_repuesto','coordinacion_retiro','otro')),
 reason TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 authorized_by TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'vigente' CHECK(status IN ('vigente','reemplazada','revocada')),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 closed_by INTEGER REFERENCES users(id),
 closed_at TEXT NOT NULL DEFAULT '',
 close_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS order_extensions_order ON order_extensions(order_id,id);
CREATE INDEX IF NOT EXISTS order_extensions_live ON order_extensions(status,new_due);
CREATE TRIGGER IF NOT EXISTS order_extensions_no_delete BEFORE DELETE ON order_extensions BEGIN SELECT RAISE(ABORT,'Las prórrogas no se eliminan'); END;
CREATE TRIGGER IF NOT EXISTS order_extensions_fixed BEFORE UPDATE OF order_id,original_due,previous_due,new_due,days,reason_code,reason,notes,authorized_by,created_by,created_at ON order_extensions
BEGIN SELECT RAISE(ABORT,'Los datos de una prórroga no se modifican: otorga una nueva o revócala'); END;
CREATE TRIGGER IF NOT EXISTS order_extensions_once BEFORE UPDATE OF status ON order_extensions WHEN OLD.status!='vigente' BEGIN SELECT RAISE(ABORT,'La prórroga ya no está vigente'); END;
-- Avisos al cliente por prórroga (otorgada y recordatorios): uno por prórroga, tipo, etapa y canal; con su resultado y reintentos.
CREATE TABLE IF NOT EXISTS order_extension_notices (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 extension_id INTEGER NOT NULL REFERENCES order_extensions(id),
 order_id INTEGER NOT NULL REFERENCES orders(id),
 kind TEXT NOT NULL CHECK(kind IN ('otorgada','recordatorio')),
 stage INTEGER NOT NULL DEFAULT 0,
 channel TEXT NOT NULL CHECK(channel IN ('correo','whatsapp')),
 recipient TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('pendiente','enviando','enviado','error','omitido','en_cola')),
 attempts INTEGER NOT NULL DEFAULT 0,
 detail TEXT NOT NULL DEFAULT '',
 message_ref TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(extension_id,kind,stage,channel)
);
CREATE INDEX IF NOT EXISTS order_extension_notices_order ON order_extension_notices(order_id,id);
CREATE TRIGGER IF NOT EXISTS order_extension_notices_no_delete BEFORE DELETE ON order_extension_notices BEGIN SELECT RAISE(ABORT,'Los avisos de prórroga no se eliminan'); END;
