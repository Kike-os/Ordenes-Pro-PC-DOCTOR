-- Borrador de un mensaje al cliente: uno por orden y usuario. Es trabajo en curso, no una comunicación: se puede reemplazar y descartar, y
-- desaparece al registrar o enviar el mensaje. Tabla nueva; no toca datos existentes.
CREATE TABLE order_message_drafts (
 order_id INTEGER NOT NULL REFERENCES orders(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 template TEXT NOT NULL DEFAULT '',
 channel TEXT NOT NULL DEFAULT 'whatsapp' CHECK(channel IN ('whatsapp','correo')),
 recipient TEXT NOT NULL DEFAULT '',
 subject TEXT NOT NULL DEFAULT '',
 body TEXT NOT NULL,
 sources TEXT NOT NULL DEFAULT '',
 updated_at TEXT NOT NULL,
 PRIMARY KEY(order_id,user_id)
);
