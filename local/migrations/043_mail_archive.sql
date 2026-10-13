-- Copia exacta de cada correo institucional enviado por el sistema, con su estado, la orden a la que pertenece y si ADI lo revisó.
-- Solo crea tablas nuevas. El contenido archivado no se puede modificar ni borrar; solo cambia el estado del envío.
CREATE TABLE mail_archive (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kind TEXT NOT NULL,
 order_id INTEGER REFERENCES orders(id),
 recipient TEXT NOT NULL,
 subject TEXT NOT NULL,
 body_text TEXT NOT NULL,
 body_html TEXT NOT NULL,
 attachments TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'preparado' CHECK(status IN ('preparado','enviado','error')),
 adi TEXT NOT NULL DEFAULT 'plantilla' CHECK(adi IN ('revisado','plantilla')),
 message_id TEXT NOT NULL DEFAULT '',
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 sent_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX mail_archive_order ON mail_archive(order_id,id);
CREATE TRIGGER mail_archive_content BEFORE UPDATE OF kind,order_id,recipient,subject,body_text,body_html,attachments,adi,actor_id,created_at ON mail_archive
 BEGIN SELECT RAISE(ABORT,'La copia del correo enviado no se modifica'); END;
CREATE TRIGGER mail_archive_no_delete BEFORE DELETE ON mail_archive BEGIN SELECT RAISE(ABORT,'La copia del correo enviado no se elimina'); END;
-- Resultado de la revisión de ADI por texto de plantilla (los datos variables van enmascarados): evita repetir la consulta en cada envío.
CREATE TABLE mail_review_cache (hash TEXT PRIMARY KEY, reviewed TEXT NOT NULL, created_at TEXT NOT NULL);
