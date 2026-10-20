-- Numeración única de órdenes: PCD + fecha de ingreso (AAAAMMDD) + consecutivo GLOBAL de cuatro dígitos (PCD-20261019-0005). El
-- consecutivo no se reinicia por día, mes ni año: lo lleva el contador permanente order_serial (058), que nunca retrocede ni se borra.
-- Las órdenes existentes se unifican a ese formato por orden de ingreso y con su fecha ORIGINAL de recepción. Los equipos adicionales
-- (-E02…) siguen el número de su orden principal. Ninguna orden se elimina y nada más cambia: clientes, equipos, presupuestos, pagos,
-- licencias, historial y correos siguen ligados a la orden por su identificador interno. Una orden sin fecha real de ingreso conserva su
-- código: nunca se inventa una fecha. Cada código anterior queda como alias
-- permanente (búsquedas, QR impresos, correos ya enviados) y la tabla de equivalencias conserva el cambio.
CREATE TABLE order_renumbering (
 order_id INTEGER PRIMARY KEY REFERENCES orders(id),
 old_code TEXT,
 new_code TEXT NOT NULL,
 number_date TEXT,
 sequence INTEGER,
 created_at TEXT NOT NULL
);
INSERT INTO order_renumbering(order_id,old_code,new_code,number_date,sequence,created_at)
 WITH mains AS (
  SELECT id,replace(COALESCE(NULLIF(substr(received_at,1,10),''),date(created_at,'unixepoch','-5 hours')),'-','') day,
         ROW_NUMBER() OVER (ORDER BY created_at,id) n
  FROM orders WHERE (group_id IS NULL OR group_id=id) AND created_at>0)
 SELECT o.id,o.code,
  CASE WHEN m.id IS NOT NULL THEN 'PCD-'||m.day||'-'||printf('%04d',m.n) ELSE 'PCD-'||g.day||'-'||printf('%04d',g.n)||'-E'||printf('%02d',o.unit_no) END,
  m.day,m.n,strftime('%Y-%m-%dT%H:%M:%S','now')
 FROM orders o LEFT JOIN mains m ON m.id=o.id LEFT JOIN mains g ON g.id=o.group_id
 WHERE m.id IS NOT NULL OR g.id IS NOT NULL;
CREATE TRIGGER order_renumbering_fixed BEFORE UPDATE ON order_renumbering BEGIN SELECT RAISE(ABORT,'La tabla de equivalencias no se modifica'); END;
CREATE TRIGGER order_renumbering_no_delete BEFORE DELETE ON order_renumbering BEGIN SELECT RAISE(ABORT,'La tabla de equivalencias no se elimina'); END;

CREATE TABLE order_code_aliases (
 code TEXT PRIMARY KEY COLLATE NOCASE,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 reason TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX order_code_aliases_order ON order_code_aliases(order_id);
INSERT INTO order_code_aliases(code,order_id,reason,created_at)
 SELECT old_code,order_id,'Código anterior a la unificación del consecutivo global',created_at FROM order_renumbering
 WHERE old_code IS NOT NULL AND old_code!=new_code AND old_code NOT IN (SELECT new_code FROM order_renumbering);
CREATE TRIGGER order_code_aliases_fixed BEFORE UPDATE ON order_code_aliases BEGIN SELECT RAISE(ABORT,'Los códigos anteriores se conservan'); END;
CREATE TRIGGER order_code_aliases_no_delete BEFORE DELETE ON order_code_aliases BEGIN SELECT RAISE(ABORT,'Los códigos anteriores se conservan'); END;

-- El número y el QR son permanentes: la protección se retira solo dentro de esta transacción y se vuelve a crear idéntica.
DROP TRIGGER immutable_order_number;
DROP TRIGGER immutable_order_qr;
UPDATE orders SET code='#renumerando-'||id,number_date=NULL,daily_sequence=NULL
 WHERE id IN (SELECT order_id FROM order_renumbering r WHERE r.old_code IS NOT r.new_code OR r.number_date IS NOT orders.number_date OR r.sequence IS NOT orders.daily_sequence);
UPDATE orders SET
 qr_url=CASE WHEN (SELECT old_code FROM order_renumbering WHERE order_id=orders.id) IS NOT NULL AND substr(qr_url,-length((SELECT old_code FROM order_renumbering WHERE order_id=orders.id)))=(SELECT old_code FROM order_renumbering WHERE order_id=orders.id)
  THEN substr(qr_url,1,length(qr_url)-length((SELECT old_code FROM order_renumbering WHERE order_id=orders.id)))||(SELECT new_code FROM order_renumbering WHERE order_id=orders.id) ELSE qr_url END,
 code=(SELECT new_code FROM order_renumbering WHERE order_id=orders.id),
 number_date=(SELECT number_date FROM order_renumbering WHERE order_id=orders.id),
 daily_sequence=(SELECT sequence FROM order_renumbering WHERE order_id=orders.id)
 WHERE code LIKE '#renumerando-%';
CREATE TRIGGER immutable_order_number BEFORE UPDATE OF code,number_date,daily_sequence ON orders
 WHEN NEW.code IS NOT OLD.code OR NEW.number_date IS NOT OLD.number_date OR NEW.daily_sequence IS NOT OLD.daily_sequence
 BEGIN SELECT RAISE(ABORT,'El número de orden es permanente'); END;
CREATE TRIGGER immutable_order_qr BEFORE UPDATE OF qr_url ON orders
 WHEN OLD.qr_url!='' AND NEW.qr_url IS NOT OLD.qr_url
 BEGIN SELECT RAISE(ABORT,'El QR de la orden es permanente'); END;

-- El contador global continúa desde el último número asignado (nunca retrocede).
UPDATE order_serial SET value=(SELECT MAX(sequence) FROM order_renumbering) WHERE value<(SELECT COALESCE(MAX(sequence),0) FROM order_renumbering);
