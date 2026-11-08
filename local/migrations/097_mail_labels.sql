-- Etiquetas de Mail Pro (1.5.260). Solo añade dos tablas: no cambia correos, órdenes ni clientes. Se guardan por Message-ID, así el mensaje
-- conserva sus etiquetas aunque cambie de carpeta. Cuatro etiquetas iniciales; administración puede crear o eliminar otras.
CREATE TABLE mail_labels (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 color TEXT NOT NULL DEFAULT 'azul',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX mail_labels_name ON mail_labels(lower(name));
CREATE TABLE mail_message_labels (
 message_id TEXT NOT NULL,
 label_id INTEGER NOT NULL REFERENCES mail_labels(id),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 PRIMARY KEY(message_id,label_id)
);
CREATE INDEX mail_message_labels_label ON mail_message_labels(label_id);
INSERT INTO mail_labels(name,color,created_at) VALUES ('Urgente','rojo','2026-11-07T00:00:00-05:00'),('Cliente','azul','2026-11-07T00:00:00-05:00'),
 ('Proveedor','violeta','2026-11-07T00:00:00-05:00'),('Facturación','verde','2026-11-07T00:00:00-05:00');
