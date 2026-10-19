-- Consecutivo permanente de órdenes (OP-0001, OP-0002…; desde OP-10000 sigue con más dígitos). No se reinicia por fecha, nunca
-- retrocede ni se borra, y no reutiliza números de órdenes eliminadas o anuladas. Arranca después de las órdenes principales que ya
-- existen (las equipos adicionales -E02… no consumen número). Las órdenes existentes conservan su código.
CREATE TABLE order_serial (
 id INTEGER PRIMARY KEY CHECK(id=1),
 value INTEGER NOT NULL CHECK(value>=0)
);
INSERT INTO order_serial(id,value) SELECT 1,COUNT(*) FROM orders WHERE group_id IS NULL OR group_id=id;
CREATE TRIGGER monotonic_order_serial BEFORE UPDATE ON order_serial
 WHEN NEW.id!=OLD.id OR NEW.value<=OLD.value
 BEGIN SELECT RAISE(ABORT,'El consecutivo de órdenes no puede retroceder'); END;
CREATE TRIGGER retain_order_serial BEFORE DELETE ON order_serial
 BEGIN SELECT RAISE(ABORT,'El consecutivo de órdenes debe conservarse'); END;
