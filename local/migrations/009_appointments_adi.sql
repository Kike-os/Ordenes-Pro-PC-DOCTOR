CREATE TABLE appointment_services (
 code TEXT PRIMARY KEY, label TEXT NOT NULL, duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 15 AND 240), active INTEGER NOT NULL DEFAULT 1
);
INSERT INTO appointment_services VALUES
 ('diagnostico','Diagnóstico técnico',60,1),('portatiles','Reparación de portátiles',90,1),('computadoras','Reparación de computadoras',90,1),('mantenimiento','Mantenimiento preventivo',90,1),('bios','Programación y recuperación de BIOS',90,1),('electronica','Reparación electrónica',120,1),('impresoras','Servicio para impresoras',90,1),('otros','Otros servicios técnicos',60,1);
CREATE TABLE appointment_hours (weekday INTEGER PRIMARY KEY CHECK(weekday BETWEEN 0 AND 6),start_time TEXT NOT NULL,end_time TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
INSERT INTO appointment_hours VALUES (0,'09:00','17:00',1),(1,'09:00','17:00',1),(2,'09:00','17:00',1),(3,'09:00','17:00',1),(4,'09:00','17:00',1),(5,'09:00','13:00',1),(6,'09:00','13:00',0);
CREATE TABLE appointment_holidays (day TEXT PRIMARY KEY,label TEXT NOT NULL);
CREATE TABLE appointments (
 id INTEGER PRIMARY KEY, public_code TEXT NOT NULL UNIQUE, manage_token_hash TEXT NOT NULL UNIQUE,
 client_id INTEGER REFERENCES clients(id), technician_id INTEGER REFERENCES users(id),
 customer_name TEXT NOT NULL, identification TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL,email TEXT NOT NULL DEFAULT '',
 device_type TEXT NOT NULL,brand TEXT NOT NULL DEFAULT '',model TEXT NOT NULL DEFAULT '',service_code TEXT NOT NULL REFERENCES appointment_services(code),
 description TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',starts_at TEXT NOT NULL,duration_minutes INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'confirmada' CHECK(status IN ('solicitada','confirmada','reprogramada','cancelada','presente','completada','no_asistio')),
 generation INTEGER NOT NULL DEFAULT 1,privacy_consent INTEGER NOT NULL CHECK(privacy_consent=1),communications_consent INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,converted_order_id INTEGER REFERENCES orders(id),
 CHECK(length(customer_name) BETWEEN 2 AND 150),CHECK(length(phone) BETWEEN 7 AND 30),CHECK(length(description) BETWEEN 3 AND 1000)
);
CREATE INDEX appointments_start_status ON appointments(starts_at,status);
CREATE INDEX appointments_technician_start ON appointments(technician_id,starts_at,status);
CREATE TABLE appointment_events (
 id INTEGER PRIMARY KEY,appointment_id INTEGER NOT NULL REFERENCES appointments(id),actor_id INTEGER REFERENCES users(id),event TEXT NOT NULL,
 old_start TEXT NOT NULL DEFAULT '',new_start TEXT NOT NULL DEFAULT '',old_status TEXT NOT NULL DEFAULT '',new_status TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE appointment_notifications (
 id INTEGER PRIMARY KEY,appointment_id INTEGER NOT NULL REFERENCES appointments(id),generation INTEGER NOT NULL,
 event TEXT NOT NULL CHECK(event IN ('confirmation','reminder_24h','reminder_2h','rescheduled','cancelled')),
 channel TEXT NOT NULL CHECK(channel IN ('email','whatsapp')),result TEXT NOT NULL,created_at TEXT NOT NULL,completed_at TEXT NOT NULL DEFAULT '',detail TEXT NOT NULL DEFAULT '',
 UNIQUE(appointment_id,generation,event,channel)
);
CREATE TABLE adi_conversations (
 id INTEGER PRIMARY KEY,token_hash TEXT NOT NULL UNIQUE,mode TEXT NOT NULL DEFAULT 'adi' CHECK(mode IN ('adi','human','closed')),
 assigned_to INTEGER REFERENCES users(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_seen_admin TEXT NOT NULL DEFAULT '',last_seen_client TEXT NOT NULL DEFAULT ''
);
CREATE TABLE adi_messages (
 id INTEGER PRIMARY KEY,conversation_id INTEGER NOT NULL REFERENCES adi_conversations(id),author TEXT NOT NULL CHECK(author IN ('client','adi','operator')),
 author_id INTEGER REFERENCES users(id),visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('public','internal')),
 content TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE INDEX adi_messages_recent ON adi_messages(conversation_id,id);
CREATE TABLE adi_actions (
 id INTEGER PRIMARY KEY,conversation_id INTEGER REFERENCES adi_conversations(id),user_id INTEGER REFERENCES users(id),action TEXT NOT NULL,
 entity_id INTEGER,created_at TEXT NOT NULL,details TEXT NOT NULL DEFAULT ''
);
ALTER TABLE appointments ADD COLUMN request_key TEXT;
CREATE UNIQUE INDEX appointments_request_key ON appointments(request_key) WHERE request_key IS NOT NULL;
