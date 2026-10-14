-- Estado «En revisión por falla recurrente» y registro de cada nueva revisión dentro de la misma orden (mismo número).
-- Solo añade un estado y una tabla. El registro no se modifica ni se borra: conserva el motivo, el técnico responsable y,
-- si el equipo ya estaba entregado, la fecha de la entrega original (el reingreso queda trazado sin alterar la historia).
INSERT OR IGNORE INTO statuses(code,label) VALUES ('revision_recurrente','En revisión por falla recurrente');
CREATE TABLE order_recurrences (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 number INTEGER NOT NULL,
 reason TEXT NOT NULL,
 technician_id INTEGER REFERENCES users(id),
 actor_id INTEGER REFERENCES users(id),
 previous_status TEXT NOT NULL,
 reentry INTEGER NOT NULL DEFAULT 0,
 delivered_at TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 UNIQUE(order_id,number)
);
CREATE TRIGGER order_recurrences_fixed BEFORE UPDATE ON order_recurrences BEGIN SELECT RAISE(ABORT,'El registro de revisión recurrente no se modifica'); END;
CREATE TRIGGER order_recurrences_no_delete BEFORE DELETE ON order_recurrences BEGIN SELECT RAISE(ABORT,'El registro de revisión recurrente no se elimina'); END;
