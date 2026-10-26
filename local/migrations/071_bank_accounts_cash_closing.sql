-- Cuentas bancarias (catálogo central) y cierres de caja diarios por usuario con sus depósitos. Solo añade estructuras:
-- ningún pago, presupuesto, factura, cliente u orden existente se modifica. Las dos columnas nuevas quedan vacías hasta que se elijan.
CREATE TABLE bank_accounts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 bank TEXT NOT NULL CHECK(length(bank) BETWEEN 2 AND 120),
 account_type TEXT NOT NULL CHECK(account_type IN ('corriente','ahorros')),
 number TEXT NOT NULL CHECK(length(number) BETWEEN 4 AND 30),
 holder TEXT NOT NULL CHECK(length(holder) BETWEEN 3 AND 300),
 holder_id TEXT NOT NULL CHECK(length(holder_id) BETWEEN 3 AND 20),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id),
 UNIQUE(bank,number)
);
-- Una sola cuenta predeterminada (la que se ofrece por omisión en presupuestos y facturas).
CREATE UNIQUE INDEX bank_accounts_one_default ON bank_accounts(is_default) WHERE is_default=1;
CREATE TRIGGER bank_accounts_no_delete BEFORE DELETE ON bank_accounts BEGIN SELECT RAISE(ABORT,'Las cuentas bancarias no se eliminan: se desactivan'); END;
ALTER TABLE quotes ADD COLUMN bank_account_id INTEGER REFERENCES bank_accounts(id);
ALTER TABLE invoices ADD COLUMN bank_account_id INTEGER REFERENCES bank_accounts(id);
-- Cierre de caja: uno por usuario y día (fecha de Ecuador). Guarda la foto de los cobros de ese día al cerrar.
CREATE TABLE cash_closings (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 day TEXT NOT NULL CHECK(length(day)=10),
 expected_cash_cents INTEGER NOT NULL,
 counted_cash_cents INTEGER NOT NULL CHECK(counted_cash_cents>=0),
 difference_cents INTEGER NOT NULL,
 totals TEXT NOT NULL DEFAULT '{}',
 movements TEXT NOT NULL DEFAULT '[]',
 notes TEXT NOT NULL DEFAULT '',
 closed_at TEXT NOT NULL,
 closed_by INTEGER REFERENCES users(id),
 UNIQUE(user_id,day)
);
CREATE TRIGGER cash_closings_locked BEFORE UPDATE ON cash_closings BEGIN SELECT RAISE(ABORT,'Un cierre de caja no se modifica'); END;
CREATE TRIGGER cash_closings_no_delete BEFORE DELETE ON cash_closings BEGIN SELECT RAISE(ABORT,'Un cierre de caja no se elimina'); END;
-- Depósitos del efectivo de un cierre. «depositado» solo cuando el usuario lo confirma; «conciliado» solo por administración.
CREATE TABLE cash_deposits (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 closing_id INTEGER NOT NULL REFERENCES cash_closings(id),
 bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','depositado','conciliado','anulado')),
 deposit_date TEXT NOT NULL DEFAULT '',
 voucher_number TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 request_key TEXT UNIQUE,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 deposited_by INTEGER REFERENCES users(id),
 deposited_at TEXT NOT NULL DEFAULT '',
 reconciled_by INTEGER REFERENCES users(id),
 reconciled_at TEXT NOT NULL DEFAULT '',
 voided_by INTEGER REFERENCES users(id),
 voided_at TEXT NOT NULL DEFAULT '',
 void_reason TEXT NOT NULL DEFAULT ''
);
-- El mismo comprobante bancario no se registra dos veces en la misma cuenta.
CREATE UNIQUE INDEX cash_deposits_one_voucher ON cash_deposits(bank_account_id,voucher_number) WHERE voucher_number!='' AND status!='anulado';
CREATE INDEX cash_deposits_status ON cash_deposits(status,closing_id);
CREATE TRIGGER cash_deposits_reconciled_locked BEFORE UPDATE ON cash_deposits WHEN OLD.status='conciliado' BEGIN SELECT RAISE(ABORT,'Un depósito conciliado no se modifica'); END;
CREATE TRIGGER cash_deposits_no_delete BEFORE DELETE ON cash_deposits BEGIN SELECT RAISE(ABORT,'Un depósito no se elimina: se anula'); END;
-- Comprobante del depósito (JPG, PNG o PDF hasta 5 MB), en una tabla aparte para que los listados no lean archivos.
CREATE TABLE cash_deposit_files (
 deposit_id INTEGER PRIMARY KEY REFERENCES cash_deposits(id),
 name TEXT NOT NULL,
 mime TEXT NOT NULL CHECK(mime IN ('image/jpeg','image/png','application/pdf')),
 size INTEGER NOT NULL CHECK(size>0 AND size<=5242880),
 sha256 TEXT NOT NULL,
 data TEXT NOT NULL,
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id)
);
-- Partes de un archivo en subida (los envíos se trocean para no superar el límite de cada petición). Se borran al completarse.
CREATE TABLE cash_upload_parts (
 upload_id TEXT NOT NULL,
 part INTEGER NOT NULL CHECK(part>=0),
 total INTEGER NOT NULL CHECK(total BETWEEN 1 AND 20),
 data TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 PRIMARY KEY(upload_id,part)
);
CREATE TABLE cash_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 closing_id INTEGER REFERENCES cash_closings(id),
 deposit_id INTEGER REFERENCES cash_deposits(id),
 bank_account_id INTEGER REFERENCES bank_accounts(id),
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 actor TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE TRIGGER cash_events_no_update BEFORE UPDATE ON cash_events BEGIN SELECT RAISE(ABORT,'El historial de caja no se modifica'); END;
CREATE TRIGGER cash_events_no_delete BEFORE DELETE ON cash_events BEGIN SELECT RAISE(ABORT,'El historial de caja no se elimina'); END;
