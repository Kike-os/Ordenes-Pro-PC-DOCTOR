-- Seguimiento de entrega de correos: un registro por destinatario de cada envío y su historial técnico de eventos.
-- Solo crea tablas nuevas; no modifica mail_archive ni mail_outbox. Los eventos son inmutables: no se editan ni se borran.
CREATE TABLE mail_deliveries (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 archive_id INTEGER REFERENCES mail_archive(id),
 outbox_key TEXT NOT NULL DEFAULT '',
 message_id TEXT NOT NULL DEFAULT '',
 kind TEXT NOT NULL DEFAULT 'manual',
 subject TEXT NOT NULL DEFAULT '',
 recipient TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'cola' CHECK(status IN ('cola','enviando','enviado','entregado','demorado','rebotado','fallido','abierto','desconocido')),
 code TEXT NOT NULL DEFAULT '',
 reason TEXT NOT NULL DEFAULT '',
 permanent INTEGER NOT NULL DEFAULT 0,
 event_at TEXT NOT NULL DEFAULT '',
 retry_of INTEGER REFERENCES mail_deliveries(id),
 order_id INTEGER REFERENCES orders(id),
 actor_id INTEGER REFERENCES users(id),
 resolved_at TEXT NOT NULL DEFAULT '',
 resolved_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX mail_deliveries_message ON mail_deliveries(message_id);
CREATE INDEX mail_deliveries_recipient ON mail_deliveries(recipient COLLATE NOCASE,id);
CREATE INDEX mail_deliveries_status ON mail_deliveries(status,id);
-- El destinatario, el asunto, el tipo y el vínculo con el intento anterior no cambian después de crearse.
CREATE TRIGGER mail_deliveries_fixed BEFORE UPDATE OF archive_id,outbox_key,kind,subject,recipient,retry_of,order_id,actor_id,created_at ON mail_deliveries
 BEGIN SELECT RAISE(ABORT,'El registro de envío no se modifica'); END;
CREATE TRIGGER mail_deliveries_no_delete BEFORE DELETE ON mail_deliveries BEGIN SELECT RAISE(ABORT,'El registro de envío no se elimina'); END;
CREATE TABLE mail_delivery_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 delivery_id INTEGER NOT NULL REFERENCES mail_deliveries(id),
 event TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL,
 code TEXT NOT NULL DEFAULT '',
 detail TEXT NOT NULL DEFAULT '',
 occurred_at TEXT NOT NULL,
 received_at TEXT NOT NULL,
 fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX mail_delivery_events_delivery ON mail_delivery_events(delivery_id,occurred_at,id);
CREATE TRIGGER mail_delivery_events_fixed BEFORE UPDATE ON mail_delivery_events BEGIN SELECT RAISE(ABORT,'El historial de entrega no se modifica'); END;
CREATE TRIGGER mail_delivery_events_no_delete BEFORE DELETE ON mail_delivery_events BEGIN SELECT RAISE(ABORT,'El historial de entrega no se elimina'); END;
