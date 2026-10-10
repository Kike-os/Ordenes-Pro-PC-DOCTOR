CREATE TABLE daily_order_sequences (
 reception_date TEXT PRIMARY KEY,
 value INTEGER NOT NULL CHECK(value>0)
);
ALTER TABLE orders ADD COLUMN received_at TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN number_date TEXT;
ALTER TABLE orders ADD COLUMN daily_sequence INTEGER;
ALTER TABLE orders ADD COLUMN qr_url TEXT NOT NULL DEFAULT '';
UPDATE orders SET code='OP-'||printf('%05d',id) WHERE code IS NULL;
UPDATE orders SET received_at=strftime('%Y-%m-%dT%H:%M:%S',created_at-18000,'unixepoch')||'-05:00'
 WHERE received_at='';
CREATE UNIQUE INDEX orders_daily_number ON orders(number_date,daily_sequence);
CREATE TRIGGER immutable_order_number BEFORE UPDATE OF code,number_date,daily_sequence ON orders
 WHEN NEW.code IS NOT OLD.code OR NEW.number_date IS NOT OLD.number_date OR NEW.daily_sequence IS NOT OLD.daily_sequence
 BEGIN SELECT RAISE(ABORT,'El número de orden es permanente'); END;
CREATE TRIGGER immutable_order_qr BEFORE UPDATE OF qr_url ON orders
 WHEN OLD.qr_url!='' AND NEW.qr_url IS NOT OLD.qr_url
 BEGIN SELECT RAISE(ABORT,'El QR de la orden es permanente'); END;
-- La secuencia diaria nunca retrocede, incluso si se elimina una orden.
CREATE TRIGGER monotonic_daily_sequence BEFORE UPDATE ON daily_order_sequences
 WHEN NEW.reception_date!=OLD.reception_date OR NEW.value<=OLD.value
 BEGIN SELECT RAISE(ABORT,'La secuencia diaria no puede retroceder'); END;
CREATE TRIGGER retain_daily_sequence BEFORE DELETE ON daily_order_sequences
 BEGIN SELECT RAISE(ABORT,'La secuencia diaria debe conservarse'); END;
INSERT OR IGNORE INTO brands(name,category)
 SELECT trim(brand),'computer' FROM devices WHERE trim(COALESCE(brand,''))!='';
