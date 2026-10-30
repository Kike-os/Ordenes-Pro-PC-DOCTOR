-- Centro de seguimiento técnico y comunicación con el cliente, dentro de cada orden. Cada seguimiento crea además su evento en el historial
-- inmutable (order_history), así las órdenes antiguas y el seguimiento del inicio no cambian.
-- Lo interno del taller (internal_note) nunca sale de Órdenes Pro; lo visible para el cliente (client_message con client_visible=1) es lo
-- único que puede mostrarse en el enlace público o enviarse.
CREATE TABLE order_followups (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 history_id INTEGER REFERENCES order_history(id),
 kind TEXT NOT NULL,
 internal_note TEXT NOT NULL DEFAULT '',
 client_message TEXT NOT NULL DEFAULT '',
 client_visible INTEGER NOT NULL DEFAULT 0 CHECK(client_visible IN (0,1)),
 status_code TEXT NOT NULL DEFAULT '',
 next_action TEXT NOT NULL DEFAULT '',
 next_date TEXT NOT NULL DEFAULT '',
 priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('baja','normal','alta','urgente')),
 quote_id INTEGER REFERENCES quotes(id),
 corrects_id INTEGER REFERENCES order_followups(id),
 request_key TEXT UNIQUE,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX order_followups_order ON order_followups(order_id,id);
CREATE TRIGGER order_followups_no_update BEFORE UPDATE ON order_followups BEGIN SELECT RAISE(ABORT,'Un seguimiento no se modifica: se corrige con otro seguimiento'); END;
CREATE TRIGGER order_followups_no_delete BEFORE DELETE ON order_followups BEGIN SELECT RAISE(ABORT,'Un seguimiento no se elimina'); END;
-- Evidencias (fotografías, capturas, informes PDF). visible_to_client=0: solo el taller.
CREATE TABLE order_followup_files (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 followup_id INTEGER NOT NULL REFERENCES order_followups(id),
 order_id INTEGER NOT NULL REFERENCES orders(id),
 name TEXT NOT NULL,
 mime TEXT NOT NULL CHECK(mime IN ('image/jpeg','image/png','image/webp','application/pdf')),
 size INTEGER NOT NULL CHECK(size>0),
 sha256 TEXT NOT NULL,
 visible_to_client INTEGER NOT NULL DEFAULT 0 CHECK(visible_to_client IN (0,1)),
 data TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX order_followup_files_order ON order_followup_files(order_id,followup_id);
CREATE TRIGGER order_followup_files_no_update BEFORE UPDATE ON order_followup_files BEGIN SELECT RAISE(ABORT,'Una evidencia no se modifica'); END;
CREATE TRIGGER order_followup_files_no_delete BEFORE DELETE ON order_followup_files BEGIN SELECT RAISE(ABORT,'Una evidencia no se elimina'); END;
-- Mensajes al cliente. «preparado» = redactado o abierto en WhatsApp/copiado (NO es un envío). «enviado» solo con confirmación del proveedor
-- (WhatsApp Business) o cuando el servidor de correo lo aceptó; «entregado» y «leido» solo con el aviso real del proveedor.
CREATE TABLE order_messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 followup_id INTEGER REFERENCES order_followups(id),
 channel TEXT NOT NULL CHECK(channel IN ('whatsapp','whatsapp_manual','correo','copia')),
 template TEXT NOT NULL DEFAULT '',
 recipient TEXT NOT NULL DEFAULT '',
 body TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('preparado','enviado','entregado','leido','error')),
 provider_id TEXT NOT NULL DEFAULT '',
 error TEXT NOT NULL DEFAULT '',
 attempts INTEGER NOT NULL DEFAULT 0,
 request_key TEXT UNIQUE,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX order_messages_order ON order_messages(order_id,id);
CREATE INDEX order_messages_provider ON order_messages(provider_id);
CREATE TRIGGER order_messages_no_delete BEFORE DELETE ON order_messages BEGIN SELECT RAISE(ABORT,'Un mensaje registrado no se elimina'); END;
-- El contenido y el canal de un mensaje no cambian; solo avanzan su estado, el identificador del proveedor y los intentos.
CREATE TRIGGER order_messages_body_locked BEFORE UPDATE ON order_messages WHEN NEW.body!=OLD.body OR NEW.channel!=OLD.channel OR NEW.order_id!=OLD.order_id
 BEGIN SELECT RAISE(ABORT,'El contenido de un mensaje registrado no se modifica'); END;
