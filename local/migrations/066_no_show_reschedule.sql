-- Inasistencias automáticas y reagendamiento por enlace privado. Solo añade columnas y una tabla: no cambia ninguna cita existente.
ALTER TABLE appointments ADD COLUMN reschedules INTEGER NOT NULL DEFAULT 0;
ALTER TABLE appointments ADD COLUMN reschedule_origin TEXT NOT NULL DEFAULT '';
CREATE TABLE appointment_reschedule_links (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 appointment_id INTEGER NOT NULL REFERENCES appointments(id),
 token_hash TEXT NOT NULL UNIQUE,
 reason TEXT NOT NULL DEFAULT 'inasistencia',
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 used_at TEXT NOT NULL DEFAULT '',
 revoked_at TEXT NOT NULL DEFAULT '',
 mail_status TEXT NOT NULL DEFAULT 'pendiente',
 mail_detail TEXT NOT NULL DEFAULT '',
 mail_attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX appointment_reschedule_links_appointment ON appointment_reschedule_links(appointment_id,id);
