-- Estado de lectura de las notificaciones, propio de cada usuario.
CREATE TABLE notification_reads(
 user_id INTEGER NOT NULL REFERENCES users(id), key TEXT NOT NULL, read_at TEXT NOT NULL,
 PRIMARY KEY(user_id,key));
