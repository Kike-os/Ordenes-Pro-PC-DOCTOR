-- Fotos y evidencia de recepción de cada orden. Las imágenes se guardan ya reducidas (JPEG) y codificadas en base64.
CREATE TABLE order_photos(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), position INTEGER NOT NULL DEFAULT 0, is_main INTEGER NOT NULL DEFAULT 0, mime TEXT NOT NULL, size INTEGER NOT NULL, data TEXT NOT NULL, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
CREATE INDEX order_photos_order ON order_photos(order_id,position);
