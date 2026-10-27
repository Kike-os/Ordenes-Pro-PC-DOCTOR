-- Caja por sesiones (apertura, movimientos, arqueo por denominaciones, cierre inmutable y fondo del siguiente turno), pagos con detalle
-- (débito, crédito, cheque, cuenta receptora, referencia, fecha, pagos mixtos), transferencias y depósitos con verificación, vouchers de
-- tarjeta, proformas con aprobación del cliente, anticipos y notas de crédito (ambiente de pruebas).
-- SOLO añade tablas y columnas, salvo «invoices», que se reconstruye con el mismo contenido para admitir los orígenes «proforma» y
-- «venta_inventario» (la restricción CHECK no se puede cambiar de otro modo). Las claves foráneas se comprueban al confirmar.
PRAGMA defer_foreign_keys=ON;

-- ---- Facturas: nuevos orígenes y datos informativos de financiamiento (no cambian importes ni impuestos) ----
CREATE TABLE invoices_077 (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 doc_type TEXT NOT NULL DEFAULT '01',
 status TEXT NOT NULL DEFAULT 'borrador' CHECK(status IN ('borrador','pendiente','enviado','autorizado','rechazado','descartado')),
 environment TEXT NOT NULL DEFAULT '1' CHECK(environment IN ('1','2')),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('orden','venta_licencia','proforma','venta_inventario')),
 source_id INTEGER NOT NULL,
 order_id INTEGER REFERENCES orders(id),
 quote_id INTEGER REFERENCES quotes(id),
 license_sale_id INTEGER REFERENCES license_sales(id),
 client_id INTEGER REFERENCES clients(id),
 buyer_id_type TEXT NOT NULL DEFAULT '' CHECK(buyer_id_type IN ('','04','05','06','07','08')),
 buyer_id TEXT NOT NULL DEFAULT '',
 buyer_name TEXT NOT NULL DEFAULT '',
 buyer_address TEXT NOT NULL DEFAULT '',
 buyer_email TEXT NOT NULL DEFAULT '',
 buyer_phone TEXT NOT NULL DEFAULT '',
 consumer_final INTEGER NOT NULL DEFAULT 0 CHECK(consumer_final IN (0,1)),
 subtotal_cents INTEGER NOT NULL DEFAULT 0,
 discount_cents INTEGER NOT NULL DEFAULT 0,
 tax_cents INTEGER NOT NULL DEFAULT 0,
 total_cents INTEGER NOT NULL DEFAULT 0,
 establishment TEXT NOT NULL DEFAULT '',
 emission_point TEXT NOT NULL DEFAULT '',
 sequential INTEGER,
 access_key TEXT UNIQUE,
 issue_date TEXT NOT NULL DEFAULT '',
 authorization_number TEXT NOT NULL DEFAULT '',
 authorized_at TEXT NOT NULL DEFAULT '',
 sri_messages TEXT NOT NULL DEFAULT '[]',
 xml_unsigned TEXT NOT NULL DEFAULT '',
 xml_signed TEXT NOT NULL DEFAULT '',
 xml_authorized TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 emitted_by INTEGER REFERENCES users(id),
 emitted_at TEXT NOT NULL DEFAULT '',
 bank_account_id INTEGER REFERENCES bank_accounts(id),
 financing TEXT NOT NULL DEFAULT '{}',
 UNIQUE(environment,establishment,emission_point,doc_type,sequential)
);
INSERT INTO invoices_077(id,doc_type,status,environment,source_kind,source_id,order_id,quote_id,license_sale_id,client_id,buyer_id_type,buyer_id,buyer_name,buyer_address,buyer_email,buyer_phone,
 consumer_final,subtotal_cents,discount_cents,tax_cents,total_cents,establishment,emission_point,sequential,access_key,issue_date,authorization_number,authorized_at,sri_messages,xml_unsigned,
 xml_signed,xml_authorized,created_by,created_at,updated_at,emitted_by,emitted_at,bank_account_id)
SELECT id,doc_type,status,environment,source_kind,source_id,order_id,quote_id,license_sale_id,client_id,buyer_id_type,buyer_id,buyer_name,buyer_address,buyer_email,buyer_phone,
 consumer_final,subtotal_cents,discount_cents,tax_cents,total_cents,establishment,emission_point,sequential,access_key,issue_date,authorization_number,authorized_at,sri_messages,xml_unsigned,
 xml_signed,xml_authorized,created_by,created_at,updated_at,emitted_by,emitted_at,bank_account_id FROM invoices;
-- Los disparadores de las partidas consultan «invoices»: se quitan durante el cambio y se recrean idénticos.
DROP TRIGGER invoice_items_locked;
DROP TRIGGER invoice_items_no_delete;
DROP TABLE invoices;
ALTER TABLE invoices_077 RENAME TO invoices;
CREATE TRIGGER invoice_items_locked BEFORE UPDATE ON invoice_items WHEN (SELECT status FROM invoices WHERE id=OLD.invoice_id) NOT IN ('borrador') BEGIN SELECT RAISE(ABORT,'Las partidas de un comprobante emitido no se modifican'); END;
CREATE TRIGGER invoice_items_no_delete BEFORE DELETE ON invoice_items WHEN (SELECT status FROM invoices WHERE id=OLD.invoice_id) NOT IN ('borrador') BEGIN SELECT RAISE(ABORT,'Las partidas de un comprobante emitido no se eliminan'); END;
CREATE UNIQUE INDEX invoices_one_per_source ON invoices(source_kind,source_id,environment) WHERE status!='descartado';
CREATE INDEX invoices_status ON invoices(status,created_at);
CREATE TRIGGER invoices_authorized_locked BEFORE UPDATE ON invoices WHEN OLD.status='autorizado' BEGIN SELECT RAISE(ABORT,'Un comprobante autorizado no se modifica'); END;
CREATE TRIGGER invoices_no_delete BEFORE DELETE ON invoices BEGIN SELECT RAISE(ABORT,'Los comprobantes no se eliminan'); END;

-- ---- Archivos de respaldo de pagos (comprobantes de transferencia, vouchers, sustentos de egresos) ----
CREATE TABLE payment_files (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kind TEXT NOT NULL CHECK(kind IN ('transferencia','voucher','egreso','ingreso','anticipo')),
 name TEXT NOT NULL,
 mime TEXT NOT NULL CHECK(mime IN ('image/jpeg','image/png','application/pdf')),
 size INTEGER NOT NULL CHECK(size>0),
 sha256 TEXT NOT NULL,
 data BLOB NOT NULL,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE TRIGGER payment_files_no_update BEFORE UPDATE ON payment_files BEGIN SELECT RAISE(ABORT,'Un comprobante no se modifica'); END;
CREATE TRIGGER payment_files_no_delete BEFORE DELETE ON payment_files BEGIN SELECT RAISE(ABORT,'Un comprobante no se elimina'); END;

-- Historial común de caja, transferencias y vouchers (inmutable).
CREATE TABLE payment_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 entity TEXT NOT NULL CHECK(entity IN ('sesion','movimiento','transferencia','voucher','anticipo','cuenta','caja')),
 entity_id INTEGER NOT NULL,
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 actor TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX payment_events_entity ON payment_events(entity,entity_id,id);
CREATE TRIGGER payment_events_no_update BEFORE UPDATE ON payment_events BEGIN SELECT RAISE(ABORT,'El historial no se modifica'); END;
CREATE TRIGGER payment_events_no_delete BEFORE DELETE ON payment_events BEGIN SELECT RAISE(ABORT,'El historial no se elimina'); END;

-- ---- Caja por sesiones ----
CREATE TABLE cash_registers (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL UNIQUE CHECK(length(name) BETWEEN 3 AND 60),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id)
);
CREATE TRIGGER cash_registers_no_delete BEFORE DELETE ON cash_registers BEGIN SELECT RAISE(ABORT,'Una caja no se elimina: se desactiva'); END;
INSERT INTO cash_registers(name,created_at) VALUES ('Caja principal','2026-10-27T00:00:00-05:00');

-- Denominaciones USD configurables. Los arqueos guardan su propio valor, así que un cambio aquí no altera los históricos.
CREATE TABLE cash_denominations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kind TEXT NOT NULL CHECK(kind IN ('moneda','billete')),
 value_cents INTEGER NOT NULL CHECK(value_cents>0),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 position INTEGER NOT NULL,
 UNIQUE(kind,value_cents)
);
INSERT INTO cash_denominations(kind,value_cents,position) VALUES ('moneda',1,1),('moneda',5,2),('moneda',10,3),('moneda',25,4),('moneda',50,5),('moneda',100,6),
 ('billete',100,7),('billete',200,8),('billete',500,9),('billete',1000,10),('billete',2000,11),('billete',5000,12),('billete',10000,13);
CREATE TRIGGER cash_denominations_no_delete BEFORE DELETE ON cash_denominations BEGIN SELECT RAISE(ABORT,'Una denominación no se elimina: se desactiva'); END;

-- Sesión de caja: una sola abierta (o en arqueo) por caja. El cierre se guarda aparte y no se modifica.
CREATE TABLE cash_sessions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL UNIQUE,
 register_id INTEGER NOT NULL REFERENCES cash_registers(id),
 shift TEXT NOT NULL CHECK(shift IN ('Mañana','Tarde','Noche','Jornada completa')),
 cashier_id INTEGER NOT NULL REFERENCES users(id),
 opened_by INTEGER NOT NULL REFERENCES users(id),
 opened_at TEXT NOT NULL,
 opening_cents INTEGER NOT NULL CHECK(opening_cents>=0),
 opening_note TEXT NOT NULL DEFAULT '',
 fund_from_session_id INTEGER REFERENCES cash_sessions(id),
 fund_expected_cents INTEGER NOT NULL DEFAULT 0,
 fund_received_by TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('abierta','arqueo','revision','cerrada','cerrada_diferencia','anulada')),
 reviewed_by INTEGER REFERENCES users(id),
 reviewed_at TEXT NOT NULL DEFAULT '',
 review_note TEXT NOT NULL DEFAULT '',
 voided_by INTEGER REFERENCES users(id),
 voided_at TEXT NOT NULL DEFAULT '',
 void_reason TEXT NOT NULL DEFAULT '',
 request_key TEXT UNIQUE
);
CREATE UNIQUE INDEX cash_sessions_one_open ON cash_sessions(register_id) WHERE status IN ('abierta','arqueo');
-- El fondo reservado de un cierre solo lo recibe una apertura.
CREATE UNIQUE INDEX cash_sessions_fund_once ON cash_sessions(fund_from_session_id) WHERE fund_from_session_id IS NOT NULL AND status!='anulada';
CREATE TRIGGER cash_sessions_fixed BEFORE UPDATE OF code,register_id,shift,cashier_id,opened_by,opened_at,opening_cents,fund_from_session_id,fund_expected_cents ON cash_sessions
BEGIN SELECT RAISE(ABORT,'La apertura de una caja no se modifica'); END;
CREATE TRIGGER cash_sessions_no_delete BEFORE DELETE ON cash_sessions BEGIN SELECT RAISE(ABORT,'Una sesión de caja no se elimina'); END;

-- Conteos por denominación: el de apertura (definitivo al abrir) y el de cierre (borrador hasta cerrar).
CREATE TABLE cash_counts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 session_id INTEGER NOT NULL REFERENCES cash_sessions(id),
 stage TEXT NOT NULL CHECK(stage IN ('apertura','cierre')),
 counts TEXT NOT NULL DEFAULT '[]',
 coins_cents INTEGER NOT NULL DEFAULT 0 CHECK(coins_cents>=0),
 bills_cents INTEGER NOT NULL DEFAULT 0 CHECK(bills_cents>=0),
 total_cents INTEGER NOT NULL DEFAULT 0 CHECK(total_cents>=0),
 final INTEGER NOT NULL DEFAULT 0 CHECK(final IN (0,1)),
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id),
 UNIQUE(session_id,stage)
);
CREATE TRIGGER cash_counts_final BEFORE UPDATE ON cash_counts WHEN OLD.final=1 BEGIN SELECT RAISE(ABORT,'Un arqueo definitivo no se modifica'); END;
CREATE TRIGGER cash_counts_no_delete BEFORE DELETE ON cash_counts BEGIN SELECT RAISE(ABORT,'Un arqueo no se elimina'); END;

-- Ingresos y egresos registrados en la caja (los cobros de órdenes y licencias se leen de sus propias tablas: no se duplican).
CREATE TABLE cash_movements (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 session_id INTEGER NOT NULL REFERENCES cash_sessions(id),
 direction TEXT NOT NULL CHECK(direction IN ('ingreso','egreso')),
 kind TEXT NOT NULL,
 method TEXT NOT NULL CHECK(method IN ('efectivo','transferencia','deposito','debito','credito','cheque','otro')),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 concept TEXT NOT NULL CHECK(length(concept) BETWEEN 3 AND 200),
 beneficiary TEXT NOT NULL DEFAULT '',
 client_id INTEGER REFERENCES clients(id),
 document TEXT NOT NULL DEFAULT '',
 reference TEXT NOT NULL DEFAULT '',
 bank_account_id INTEGER REFERENCES bank_accounts(id),
 authorized_by TEXT NOT NULL DEFAULT '',
 note TEXT NOT NULL DEFAULT '',
 file_id INTEGER REFERENCES payment_files(id),
 request_key TEXT UNIQUE,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 voided_by INTEGER REFERENCES users(id),
 voided_at TEXT NOT NULL DEFAULT '',
 void_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX cash_movements_session ON cash_movements(session_id,id);
CREATE TRIGGER cash_movements_fixed BEFORE UPDATE OF session_id,direction,kind,method,amount_cents,concept,beneficiary,client_id,document,reference,bank_account_id,authorized_by,note,file_id,request_key,created_by,created_at ON cash_movements
BEGIN SELECT RAISE(ABORT,'Un movimiento de caja no se modifica: se anula con su motivo'); END;
CREATE TRIGGER cash_movements_no_delete BEFORE DELETE ON cash_movements BEGIN SELECT RAISE(ABORT,'Un movimiento de caja no se elimina'); END;

-- Cierre definitivo: foto completa e inmutable.
CREATE TABLE cash_session_closings (
 session_id INTEGER PRIMARY KEY REFERENCES cash_sessions(id),
 closed_at TEXT NOT NULL,
 closed_by INTEGER NOT NULL REFERENCES users(id),
 confirmed_name TEXT NOT NULL,
 expected_cash_cents INTEGER NOT NULL,
 counted_cash_cents INTEGER NOT NULL CHECK(counted_cash_cents>=0),
 difference_cents INTEGER NOT NULL,
 difference_reason TEXT NOT NULL DEFAULT '',
 reserved_cents INTEGER NOT NULL DEFAULT 0 CHECK(reserved_cents>=0),
 withdrawn_cents INTEGER NOT NULL DEFAULT 0 CHECK(withdrawn_cents>=0),
 delivered_by TEXT NOT NULL DEFAULT '',
 delivered_to TEXT NOT NULL DEFAULT '',
 summary TEXT NOT NULL DEFAULT '{}',
 counts TEXT NOT NULL DEFAULT '[]',
 note TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER cash_session_closings_locked BEFORE UPDATE ON cash_session_closings BEGIN SELECT RAISE(ABORT,'Un cierre de caja no se modifica'); END;
CREATE TRIGGER cash_session_closings_no_delete BEFORE DELETE ON cash_session_closings BEGIN SELECT RAISE(ABORT,'Un cierre de caja no se elimina'); END;

-- ---- Pagos de las órdenes: detalle del método, cuenta receptora, referencia, fecha del pago, operación (pagos mixtos) y sesión de caja ----
ALTER TABLE order_payments ADD COLUMN method_detail TEXT NOT NULL DEFAULT '';
ALTER TABLE order_payments ADD COLUMN bank_account_id INTEGER REFERENCES bank_accounts(id);
ALTER TABLE order_payments ADD COLUMN reference TEXT NOT NULL DEFAULT '';
ALTER TABLE order_payments ADD COLUMN paid_at TEXT NOT NULL DEFAULT '';
ALTER TABLE order_payments ADD COLUMN operation_id TEXT NOT NULL DEFAULT '';
ALTER TABLE order_payments ADD COLUMN cash_session_id INTEGER REFERENCES cash_sessions(id);
CREATE TRIGGER order_payments_detail_fixed BEFORE UPDATE OF method_detail,bank_account_id,reference,paid_at,operation_id ON order_payments
BEGIN SELECT RAISE(ABORT,'El detalle de un pago no se modifica: se anula y se registra de nuevo'); END;
-- Un cobro sin caja abierta puede asignarse una sola vez a una sesión (incidencia resuelta); después ya no cambia.
CREATE TRIGGER order_payments_session_once BEFORE UPDATE OF cash_session_id ON order_payments WHEN OLD.cash_session_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'La sesión de caja de un pago no se cambia'); END;
CREATE INDEX order_payments_session ON order_payments(cash_session_id);
CREATE INDEX order_payments_operation ON order_payments(operation_id) WHERE operation_id!='';

-- ---- Cuentas bancarias: correo, observaciones, RUC del titular y verificación antes de usarlas en documentos ----
ALTER TABLE bank_accounts ADD COLUMN email TEXT NOT NULL DEFAULT '';
ALTER TABLE bank_accounts ADD COLUMN notes TEXT NOT NULL DEFAULT '';
ALTER TABLE bank_accounts ADD COLUMN holder_ruc TEXT NOT NULL DEFAULT '';
ALTER TABLE bank_accounts ADD COLUMN verified INTEGER NOT NULL DEFAULT 1 CHECK(verified IN (0,1));
ALTER TABLE bank_accounts ADD COLUMN verified_at TEXT NOT NULL DEFAULT '';
ALTER TABLE bank_accounts ADD COLUMN verified_by INTEGER REFERENCES users(id);

-- Transferencias y depósitos recibidos: un comprobante subido no significa dinero recibido hasta que administración lo confirma.
CREATE TABLE bank_transfers (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL UNIQUE,
 method TEXT NOT NULL CHECK(method IN ('transferencia','deposito')),
 bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
 client_id INTEGER REFERENCES clients(id),
 payer TEXT NOT NULL DEFAULT '',
 source_kind TEXT NOT NULL DEFAULT '' CHECK(source_kind IN ('','orden','factura','proforma')),
 source_id INTEGER,
 payment_id INTEGER REFERENCES order_payments(id),
 advance_id INTEGER,
 reference TEXT NOT NULL CHECK(length(reference) BETWEEN 3 AND 60),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 paid_at TEXT NOT NULL,
 file_id INTEGER REFERENCES payment_files(id),
 note TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','confirmado','rechazado','conciliado')),
 status_note TEXT NOT NULL DEFAULT '',
 verified_by INTEGER REFERENCES users(id),
 verified_at TEXT NOT NULL DEFAULT '',
 reconciled_by INTEGER REFERENCES users(id),
 reconciled_at TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
-- La misma referencia bancaria no se repite en la misma cuenta (salvo un registro rechazado).
CREATE UNIQUE INDEX bank_transfers_reference ON bank_transfers(bank_account_id,lower(reference)) WHERE status!='rechazado';
CREATE INDEX bank_transfers_status ON bank_transfers(status,paid_at);
CREATE TRIGGER bank_transfers_fixed BEFORE UPDATE OF code,method,bank_account_id,client_id,payer,source_kind,source_id,payment_id,advance_id,reference,amount_cents,paid_at,file_id,created_by,created_at ON bank_transfers
BEGIN SELECT RAISE(ABORT,'Una transferencia registrada no se modifica: se rechaza con su motivo'); END;
CREATE TRIGGER bank_transfers_no_delete BEFORE DELETE ON bank_transfers BEGIN SELECT RAISE(ABORT,'Una transferencia no se elimina'); END;

-- ---- Vouchers de tarjeta (sin CVV, PIN, banda ni número completo: solo los últimos cuatro dígitos) ----
CREATE TABLE card_vouchers (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL UNIQUE,
 payment_id INTEGER REFERENCES order_payments(id),
 advance_id INTEGER,
 cash_session_id INTEGER REFERENCES cash_sessions(id),
 client_id INTEGER REFERENCES clients(id),
 issuer_bank TEXT NOT NULL,
 acquirer TEXT NOT NULL DEFAULT 'DATAFAST',
 brand TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT '',
 tx_type TEXT NOT NULL CHECK(tx_type IN ('debito','corriente','diferido_con_intereses','diferido_sin_intereses')),
 months INTEGER NOT NULL DEFAULT 1 CHECK(months BETWEEN 1 AND 48),
 lot TEXT NOT NULL CHECK(length(lot) BETWEEN 1 AND 20),
 reference TEXT NOT NULL CHECK(length(reference) BETWEEN 1 AND 30),
 approval_code TEXT NOT NULL CHECK(length(approval_code) BETWEEN 2 AND 20),
 paid_at TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 last4 TEXT NOT NULL CHECK(length(last4)=4 AND last4 GLOB '[0-9][0-9][0-9][0-9]'),
 file_id INTEGER REFERENCES payment_files(id),
 status TEXT NOT NULL DEFAULT 'registrada' CHECK(status IN ('registrada','autorizada','pendiente_liquidacion','liquidada','reversada','rechazada')),
 commission_cents INTEGER NOT NULL DEFAULT 0 CHECK(commission_cents>=0),
 commission_tax_cents INTEGER NOT NULL DEFAULT 0 CHECK(commission_tax_cents>=0),
 withholding_cents INTEGER NOT NULL DEFAULT 0 CHECK(withholding_cents>=0),
 net_cents INTEGER,
 settled_at TEXT NOT NULL DEFAULT '',
 note TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX card_vouchers_approval ON card_vouchers(acquirer,lot,approval_code);
CREATE TRIGGER card_vouchers_no_delete BEFORE DELETE ON card_vouchers BEGIN SELECT RAISE(ABORT,'Un voucher no se elimina: se reversa o rechaza'); END;

-- ---- Proformas con aprobación del cliente, versiones y conversión controlada a factura ----
CREATE TABLE proformas (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL UNIQUE,
 version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),
 parent_id INTEGER REFERENCES proformas(id),
 origin TEXT NOT NULL CHECK(origin IN ('cliente','orden','catalogo','directa','inventario')),
 order_id INTEGER REFERENCES orders(id),
 client_id INTEGER REFERENCES clients(id),
 client_name TEXT NOT NULL DEFAULT '',
 client_identification TEXT NOT NULL DEFAULT '',
 client_address TEXT NOT NULL DEFAULT '',
 client_phone TEXT NOT NULL DEFAULT '',
 client_email TEXT NOT NULL DEFAULT '',
 issue_date TEXT NOT NULL,
 valid_until TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('borrador','enviada','vista','aprobada','parcial','rechazada','modificacion','vencida','convertida','reemplazada','cancelada')),
 tax_rate_bp INTEGER NOT NULL CHECK(tax_rate_bp BETWEEN 0 AND 3000),
 payment_method TEXT NOT NULL DEFAULT 'efectivo',
 financing TEXT NOT NULL DEFAULT '{}',
 bank_account_id INTEGER REFERENCES bank_accounts(id),
 notes TEXT NOT NULL DEFAULT '',
 conditions TEXT NOT NULL DEFAULT '',
 subtotal_cents INTEGER NOT NULL DEFAULT 0,
 discount_cents INTEGER NOT NULL DEFAULT 0,
 tax_cents INTEGER NOT NULL DEFAULT 0,
 total_cents INTEGER NOT NULL DEFAULT 0,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 sent_at TEXT NOT NULL DEFAULT '',
 sent_to TEXT NOT NULL DEFAULT '',
 viewed_at TEXT NOT NULL DEFAULT '',
 decided_at TEXT NOT NULL DEFAULT '',
 invoice_id INTEGER REFERENCES invoices(id),
 replaced_by INTEGER REFERENCES proformas(id),
 request_key TEXT UNIQUE
);
CREATE INDEX proformas_status ON proformas(status,created_at);
CREATE TRIGGER proformas_no_delete BEFORE DELETE ON proformas BEGIN SELECT RAISE(ABORT,'Una proforma no se elimina: se cancela'); END;
CREATE TRIGGER proformas_converted_locked BEFORE UPDATE ON proformas WHEN OLD.status IN ('convertida','reemplazada') AND NEW.status=OLD.status
BEGIN SELECT RAISE(ABORT,'Una proforma convertida o reemplazada no se modifica'); END;
CREATE TABLE proforma_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 proforma_id INTEGER NOT NULL REFERENCES proformas(id),
 position INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('producto','servicio')),
 catalog_id INTEGER REFERENCES catalog_items(id),
 inventory_item_id INTEGER REFERENCES inventory_items(id),
 code TEXT NOT NULL DEFAULT '',
 description TEXT NOT NULL CHECK(length(description) BETWEEN 2 AND 300),
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 100000),
 unit_cents INTEGER NOT NULL CHECK(unit_cents>=0),
 discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents>=0),
 taxed INTEGER NOT NULL DEFAULT 1 CHECK(taxed IN (0,1)),
 status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','aprobado','rechazado')),
 authorization TEXT NOT NULL DEFAULT ''
);
CREATE INDEX proforma_items_proforma ON proforma_items(proforma_id,position);
CREATE TABLE proforma_links (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 proforma_id INTEGER NOT NULL REFERENCES proformas(id),
 token_hash TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 revoked_at TEXT NOT NULL DEFAULT '',
 failed INTEGER NOT NULL DEFAULT 0,
 viewed_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE proforma_acceptances (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 proforma_id INTEGER NOT NULL REFERENCES proformas(id),
 decision TEXT NOT NULL CHECK(decision IN ('aprobada','parcial','rechazada','modificacion')),
 signer_name TEXT NOT NULL,
 method TEXT NOT NULL,
 signature TEXT NOT NULL DEFAULT '[]',
 evidence TEXT NOT NULL,
 evidence_hash TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TRIGGER proforma_acceptances_no_update BEFORE UPDATE ON proforma_acceptances BEGIN SELECT RAISE(ABORT,'La evidencia de aceptación no se modifica'); END;
CREATE TRIGGER proforma_acceptances_no_delete BEFORE DELETE ON proforma_acceptances BEGIN SELECT RAISE(ABORT,'La evidencia de aceptación no se elimina'); END;
CREATE TABLE proforma_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 proforma_id INTEGER NOT NULL REFERENCES proformas(id),
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 actor TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE TRIGGER proforma_events_no_update BEFORE UPDATE ON proforma_events BEGIN SELECT RAISE(ABORT,'El historial no se modifica'); END;
CREATE TRIGGER proforma_events_no_delete BEFORE DELETE ON proforma_events BEGIN SELECT RAISE(ABORT,'El historial no se elimina'); END;

-- Anticipos y abonos de clientes (antes de facturar), vinculados a una proforma; se aplican a su factura sin cobrarse dos veces.
CREATE TABLE advances (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL UNIQUE,
 client_id INTEGER REFERENCES clients(id),
 proforma_id INTEGER REFERENCES proformas(id),
 method TEXT NOT NULL CHECK(method IN ('efectivo','transferencia','deposito','debito','credito','cheque','otro')),
 bank_account_id INTEGER REFERENCES bank_accounts(id),
 reference TEXT NOT NULL DEFAULT '',
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 paid_at TEXT NOT NULL,
 cash_session_id INTEGER REFERENCES cash_sessions(id),
 operation_id TEXT NOT NULL DEFAULT '',
 note TEXT NOT NULL DEFAULT '',
 request_key TEXT UNIQUE,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 voided_by INTEGER REFERENCES users(id),
 voided_at TEXT NOT NULL DEFAULT '',
 void_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX advances_proforma ON advances(proforma_id);
CREATE TRIGGER advances_fixed BEFORE UPDATE OF client_id,proforma_id,method,bank_account_id,reference,amount_cents,paid_at,operation_id,request_key,created_by,created_at ON advances
BEGIN SELECT RAISE(ABORT,'Un anticipo no se modifica: se anula con su motivo'); END;
CREATE TRIGGER advances_no_delete BEFORE DELETE ON advances BEGIN SELECT RAISE(ABORT,'Un anticipo no se elimina'); END;

-- ---- Notas de crédito (ambiente de pruebas; la emisión real sigue desactivada) ----
CREATE TABLE credit_notes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 status TEXT NOT NULL CHECK(status IN ('borrador','pendiente','descartado')),
 environment TEXT NOT NULL DEFAULT '1' CHECK(environment IN ('1','2')),
 scope TEXT NOT NULL CHECK(scope IN ('total','parcial')),
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 5 AND 300),
 subtotal_cents INTEGER NOT NULL DEFAULT 0,
 tax_cents INTEGER NOT NULL DEFAULT 0,
 total_cents INTEGER NOT NULL DEFAULT 0,
 establishment TEXT NOT NULL DEFAULT '',
 emission_point TEXT NOT NULL DEFAULT '',
 sequential INTEGER,
 access_key TEXT UNIQUE,
 issue_date TEXT NOT NULL DEFAULT '',
 xml_unsigned TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 emitted_by INTEGER REFERENCES users(id),
 emitted_at TEXT NOT NULL DEFAULT '',
 request_key TEXT UNIQUE,
 UNIQUE(environment,establishment,emission_point,sequential)
);
CREATE TRIGGER credit_notes_emitted_locked BEFORE UPDATE ON credit_notes WHEN OLD.status='pendiente' BEGIN SELECT RAISE(ABORT,'Una nota de crédito emitida no se modifica'); END;
CREATE TRIGGER credit_notes_no_delete BEFORE DELETE ON credit_notes BEGIN SELECT RAISE(ABORT,'Una nota de crédito no se elimina'); END;
CREATE TABLE credit_note_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 credit_note_id INTEGER NOT NULL REFERENCES credit_notes(id),
 invoice_item_id INTEGER NOT NULL REFERENCES invoice_items(id),
 code TEXT NOT NULL,
 description TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_price_micros INTEGER NOT NULL,
 discount_cents INTEGER NOT NULL DEFAULT 0,
 base_cents INTEGER NOT NULL CHECK(base_cents>=0),
 tax_code TEXT NOT NULL,
 tax_rate_bp INTEGER NOT NULL,
 tax_cents INTEGER NOT NULL CHECK(tax_cents>=0),
 total_cents INTEGER NOT NULL
);

-- Cobros de licencias también quedan en la sesión de caja abierta.
ALTER TABLE license_sale_payments ADD COLUMN cash_session_id INTEGER REFERENCES cash_sessions(id);
CREATE INDEX license_sale_payments_session ON license_sale_payments(cash_session_id);
-- Correcciones posteriores a un cierre: se registran aparte, con motivo y autorización; el cierre original no cambia.
CREATE TABLE cash_adjustments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 session_id INTEGER NOT NULL REFERENCES cash_sessions(id),
 amount_cents INTEGER NOT NULL CHECK(amount_cents!=0),
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 10 AND 300),
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE TRIGGER cash_adjustments_no_update BEFORE UPDATE ON cash_adjustments BEGIN SELECT RAISE(ABORT,'Un ajuste de caja no se modifica'); END;
CREATE TRIGGER cash_adjustments_no_delete BEFORE DELETE ON cash_adjustments BEGIN SELECT RAISE(ABORT,'Un ajuste de caja no se elimina'); END;
