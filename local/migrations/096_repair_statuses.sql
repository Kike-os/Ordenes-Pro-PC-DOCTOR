-- Estados de reparación detallados (1.5.257). Solo añade: no cambia el estado de ninguna orden ni toca el historial (inmutable).
-- Tres estados nuevos (diagnóstico, esperando repuesto, pruebas y control de calidad) y etiquetas más claras para tres existentes;
-- el historial anterior conserva sus etiquetas («En espera», «Procesando», «Aprobación de presupuesto», …) y el código las reconoce.
INSERT OR IGNORE INTO statuses(code,label) VALUES ('diagnostico','Diagnóstico en proceso');
INSERT OR IGNORE INTO statuses(code,label) VALUES ('esperando_repuesto','Esperando repuesto');
INSERT OR IGNORE INTO statuses(code,label) VALUES ('pruebas','Pruebas técnicas y control de calidad');
UPDATE statuses SET label='Diagnóstico en proceso' WHERE code='diagnostico';
UPDATE statuses SET label='En espera de diagnóstico' WHERE code='pendiente';
UPDATE statuses SET label='Reparación en proceso' WHERE code='reparacion';
UPDATE statuses SET label='Pendiente de aprobación de presupuesto' WHERE code='presupuesto';
UPDATE statuses SET label='Revisión por falla recurrente' WHERE code='revision_recurrente';
-- Auditoría de cada cambio de estado: anterior, nuevo, quién, cuándo, motivo y el evento real que lo produjo. No se modifica ni se borra.
CREATE TABLE order_status_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 from_status TEXT NOT NULL DEFAULT '',
 to_status TEXT NOT NULL,
 actor_id INTEGER REFERENCES users(id),
 reason TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX order_status_log_order ON order_status_log(order_id,id);
CREATE TRIGGER order_status_log_no_update BEFORE UPDATE ON order_status_log BEGIN SELECT RAISE(ABORT,'La auditoría de estados no se modifica'); END;
CREATE TRIGGER order_status_log_no_delete BEFORE DELETE ON order_status_log BEGIN SELECT RAISE(ABORT,'La auditoría de estados no se elimina'); END;
-- Avisos al cliente por cambios de estado relevantes: uno por cambio y canal (la clave única impide duplicados). «enviado» solo cuando el
-- servidor de correo o WhatsApp Business lo aceptó; «omitido» explica el motivo (sin canal, sin consentimiento, ya avisado, sin configurar).
CREATE TABLE order_status_notices (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 log_id INTEGER NOT NULL REFERENCES order_status_log(id),
 event TEXT NOT NULL,
 channel TEXT NOT NULL CHECK(channel IN ('correo','whatsapp')),
 status TEXT NOT NULL CHECK(status IN ('pendiente','enviado','fallido','omitido')),
 detail TEXT NOT NULL DEFAULT '',
 attempts INTEGER NOT NULL DEFAULT 0,
 message_id INTEGER REFERENCES order_messages(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(log_id,channel)
);
CREATE INDEX order_status_notices_order ON order_status_notices(order_id,id);
CREATE TRIGGER order_status_notices_no_delete BEFORE DELETE ON order_status_notices BEGIN SELECT RAISE(ABORT,'Un aviso registrado no se elimina'); END;
-- La fecha estimada solo se muestra al cliente cuando el taller la marca como confirmada.
ALTER TABLE orders ADD COLUMN estimated_confirmed INTEGER NOT NULL DEFAULT 0;
