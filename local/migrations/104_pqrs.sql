-- 1.5.278 · PQRS (peticiones, quejas, reclamos y sugerencias). Solo crea tablas nuevas y añade una columna a la cola de WhatsApp.
-- Conservación: los casos, su historial, sus adjuntos y sus avisos no se borran (decisión de administración del 11/11/2026); las cargas
-- de adjuntos que nunca llegaron a enviarse se limpian a las 24 h porque no forman parte de ningún caso.

-- Secuencia anual de códigos PQRS-AAAA-NNNN: cada reserva de número ocurre dentro de la transacción exclusiva de la petición.
CREATE TABLE IF NOT EXISTS pqrs_sequence (
 year INTEGER PRIMARY KEY,
 last INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pqrs_cases (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL UNIQUE,
 request_key TEXT NOT NULL UNIQUE,
 track_hash TEXT NOT NULL,
 category TEXT NOT NULL CHECK(category IN ('peticion','queja','reclamo','sugerencia')),
 status TEXT NOT NULL DEFAULT 'recibida' CHECK(status IN ('recibida','en_revision','asignada','esperando_cliente','en_solucion','respondida','cerrada')),
 priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('baja','normal','alta','urgente')),
 language TEXT NOT NULL DEFAULT 'es-EC' CHECK(language IN ('es-EC','en-US')),
 name TEXT NOT NULL,
 email TEXT NOT NULL,
 phone TEXT NOT NULL,
 site TEXT NOT NULL DEFAULT '',
 subject TEXT NOT NULL,
 description TEXT NOT NULL,
 order_code TEXT NOT NULL DEFAULT '',
 order_id INTEGER REFERENCES orders(id),
 order_verified INTEGER NOT NULL DEFAULT 0,
 client_id INTEGER REFERENCES clients(id),
 privacy_consent INTEGER NOT NULL CHECK(privacy_consent=1),
 whatsapp_consent INTEGER NOT NULL DEFAULT 0,
 assigned_to INTEGER REFERENCES users(id),
 resolution TEXT NOT NULL DEFAULT '',
 ip_hash TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 first_response_at TEXT NOT NULL DEFAULT '',
 closed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS pqrs_cases_status ON pqrs_cases(status,id);
CREATE INDEX IF NOT EXISTS pqrs_cases_assigned ON pqrs_cases(assigned_to,id);
CREATE INDEX IF NOT EXISTS pqrs_cases_created ON pqrs_cases(created_at);
CREATE TRIGGER IF NOT EXISTS pqrs_cases_no_delete BEFORE DELETE ON pqrs_cases BEGIN SELECT RAISE(ABORT,'Una PQRS registrada no se elimina'); END;
CREATE TRIGGER IF NOT EXISTS pqrs_cases_fixed BEFORE UPDATE OF code,request_key,category,name,email,phone,subject,description,created_at ON pqrs_cases
BEGIN SELECT RAISE(ABORT,'Los datos enviados por el cliente no se modifican'); END;

-- Historial: cambios de estado, asignaciones, prioridad, respuestas al cliente (públicas), notas internas y mensajes del cliente.
CREATE TABLE IF NOT EXISTS pqrs_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 case_id INTEGER NOT NULL REFERENCES pqrs_cases(id),
 kind TEXT NOT NULL CHECK(kind IN ('creada','estado','asignacion','prioridad','respuesta','nota','mensaje_cliente','cierre','reapertura')),
 public INTEGER NOT NULL DEFAULT 0,
 body TEXT NOT NULL DEFAULT '',
 old_value TEXT NOT NULL DEFAULT '',
 new_value TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pqrs_events_case ON pqrs_events(case_id,id);
CREATE TRIGGER IF NOT EXISTS pqrs_events_no_delete BEFORE DELETE ON pqrs_events BEGIN SELECT RAISE(ABORT,'El historial de una PQRS no se elimina'); END;
CREATE TRIGGER IF NOT EXISTS pqrs_events_no_update BEFORE UPDATE ON pqrs_events BEGIN SELECT RAISE(ABORT,'El historial de una PQRS no se modifica'); END;

-- Cargas de adjuntos del formulario público (por partes de 2,5 MiB: Vercel no admite más de 4,5 MB por petición).
CREATE TABLE IF NOT EXISTS pqrs_uploads (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 token TEXT NOT NULL UNIQUE,
 draft TEXT NOT NULL,
 name TEXT NOT NULL,
 size INTEGER NOT NULL,
 sha256 TEXT NOT NULL,
 parts INTEGER NOT NULL,
 mime TEXT NOT NULL DEFAULT '',
 thumb TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'subiendo' CHECK(status IN ('subiendo','lista','usada')),
 case_id INTEGER REFERENCES pqrs_cases(id),
 ip_hash TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pqrs_uploads_draft ON pqrs_uploads(draft);
CREATE INDEX IF NOT EXISTS pqrs_uploads_case ON pqrs_uploads(case_id);
CREATE TABLE IF NOT EXISTS pqrs_upload_parts (
 upload_id INTEGER NOT NULL REFERENCES pqrs_uploads(id),
 idx INTEGER NOT NULL,
 data TEXT NOT NULL,
 PRIMARY KEY(upload_id,idx)
);
-- Un adjunto que ya pertenece a una PQRS no se borra (solo se limpian cargas abandonadas que nunca se enviaron).
CREATE TRIGGER IF NOT EXISTS pqrs_uploads_keep BEFORE DELETE ON pqrs_uploads WHEN OLD.status='usada' BEGIN SELECT RAISE(ABORT,'Un adjunto de una PQRS no se elimina'); END;

-- Avisos de cada caso (correo al cliente; WhatsApp va por su propia cola) con el resultado real de cada intento.
CREATE TABLE IF NOT EXISTS pqrs_notifications (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 case_id INTEGER NOT NULL REFERENCES pqrs_cases(id),
 event TEXT NOT NULL,
 channel TEXT NOT NULL CHECK(channel IN ('email')),
 recipient TEXT NOT NULL DEFAULT '',
 result TEXT NOT NULL CHECK(result IN ('pendiente','enviado','fallido','sin_configurar','sin_destinatario')),
 detail TEXT NOT NULL DEFAULT '',
 attempts INTEGER NOT NULL DEFAULT 0,
 event_id INTEGER REFERENCES pqrs_events(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pqrs_notifications_case ON pqrs_notifications(case_id,id);
CREATE TRIGGER IF NOT EXISTS pqrs_notifications_no_delete BEFORE DELETE ON pqrs_notifications BEGIN SELECT RAISE(ABORT,'El registro de un aviso no se elimina'); END;

-- WhatsApp Business: los avisos de una PQRS se identifican por su caso (no tienen orden ni cita).
ALTER TABLE whatsapp_outbox ADD COLUMN pqrs_id INTEGER REFERENCES pqrs_cases(id);
