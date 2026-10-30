-- Ventana «Comunicación con el cliente»: solo agrega columnas (no cambia ni borra datos).
-- recommendation: recomendación para el cliente registrada en el seguimiento (comunicable, igual que client_message).
-- sources: seguimientos (y registros anteriores elegidos expresamente) usados para redactar el mensaje, en JSON.
-- subject: asunto del correo tal como se envió.
ALTER TABLE order_followups ADD COLUMN recommendation TEXT NOT NULL DEFAULT '';
ALTER TABLE order_messages ADD COLUMN sources TEXT NOT NULL DEFAULT '';
ALTER TABLE order_messages ADD COLUMN subject TEXT NOT NULL DEFAULT '';
-- Como el contenido: las fuentes y el asunto de un mensaje registrado no cambian.
CREATE TRIGGER order_messages_sources_locked BEFORE UPDATE ON order_messages WHEN NEW.sources!=OLD.sources OR NEW.subject!=OLD.subject
 BEGIN SELECT RAISE(ABORT,'El contenido de un mensaje registrado no se modifica'); END;
