-- Centro de Métodos de Pago: tarjetas y factores DATAFAST (diferido con intereses) y recargo comercial configurable.
-- SOLO crea tablas nuevas y su carga inicial (INSERT OR IGNORE: idempotente). No modifica ningún dato existente.
-- Reversión (antes de usarlas): DROP TABLE card_surcharge_history; DROP TABLE card_surcharge_settings; DROP TABLE card_factors; DROP TABLE card_products; DROP TABLE card_factor_groups;
-- Factores en puntos básicos (2,68 % = 268). Un factor «pendiente» no tiene valor y no se puede seleccionar.
CREATE TABLE card_factor_groups (code TEXT PRIMARY KEY CHECK(length(code)=1), label TEXT NOT NULL);
CREATE TABLE card_products (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 bank TEXT NOT NULL CHECK(length(bank) BETWEEN 2 AND 80),
 brand TEXT NOT NULL CHECK(length(brand) BETWEEN 2 AND 60),
 category TEXT NOT NULL CHECK(length(category) BETWEEN 2 AND 80),
 group_code TEXT NOT NULL REFERENCES card_factor_groups(code),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 source TEXT NOT NULL DEFAULT '',
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id),
 UNIQUE(bank,brand,category)
);
CREATE TABLE card_factors (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 group_code TEXT NOT NULL REFERENCES card_factor_groups(code),
 months INTEGER NOT NULL CHECK(months IN (3,4,5,6,9,10,12,15,18,24,36)),
 factor_bp INTEGER CHECK(factor_bp IS NULL OR factor_bp BETWEEN 0 AND 10000),
 status TEXT NOT NULL CHECK(status IN ('vigente','pendiente','reemplazado')),
 valid_from TEXT NOT NULL,
 valid_to TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL,
 version TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT '',
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id),
 CHECK(status!='vigente' OR factor_bp IS NOT NULL),
 UNIQUE(group_code,months,version)
);
CREATE UNIQUE INDEX card_factors_current ON card_factors(group_code,months) WHERE status IN ('vigente','pendiente');
CREATE TRIGGER card_factors_no_delete BEFORE DELETE ON card_factors BEGIN SELECT RAISE(ABORT,'Los factores no se eliminan: se reemplazan por una nueva versión.'); END;
CREATE TABLE card_surcharge_settings (
 id INTEGER PRIMARY KEY CHECK(id=1),
 percent_bp INTEGER NOT NULL DEFAULT 0 CHECK(percent_bp BETWEEN 0 AND 5000),
 fixed_cents INTEGER NOT NULL DEFAULT 0 CHECK(fixed_cents BETWEEN 0 AND 100000),
 payer TEXT NOT NULL DEFAULT 'cliente' CHECK(payer IN ('cliente','empresa')),
 methods TEXT NOT NULL DEFAULT '[]',
 valid_from TEXT NOT NULL DEFAULT '',
 valid_to TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
 validated INTEGER NOT NULL DEFAULT 0 CHECK(validated IN (0,1)),
 note TEXT NOT NULL DEFAULT '',
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE TABLE card_surcharge_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 percent_bp INTEGER NOT NULL, fixed_cents INTEGER NOT NULL, payer TEXT NOT NULL, methods TEXT NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT NOT NULL, active INTEGER NOT NULL, validated INTEGER NOT NULL, note TEXT NOT NULL,
 changed_at TEXT NOT NULL, changed_by INTEGER REFERENCES users(id), actor TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER card_surcharge_history_no_update BEFORE UPDATE ON card_surcharge_history BEGIN SELECT RAISE(ABORT,'El historial del recargo no se modifica.'); END;
CREATE TRIGGER card_surcharge_history_no_delete BEFORE DELETE ON card_surcharge_history BEGIN SELECT RAISE(ABORT,'El historial del recargo no se elimina.'); END;
INSERT OR IGNORE INTO card_factor_groups(code,label) VALUES ('A','Grupo A');
INSERT OR IGNORE INTO card_factor_groups(code,label) VALUES ('B','Grupo B');
INSERT OR IGNORE INTO card_factor_groups(code,label) VALUES ('C','Grupo C');
INSERT OR IGNORE INTO card_factor_groups(code,label) VALUES ('D','Grupo D');
INSERT OR IGNORE INTO card_factor_groups(code,label) VALUES ('E','Grupo E');
INSERT OR IGNORE INTO card_factor_groups(code,label) VALUES ('F','Grupo F');
INSERT OR IGNORE INTO card_factor_groups(code,label) VALUES ('G','Grupo G');
INSERT OR IGNORE INTO card_factor_groups(code,label) VALUES ('H','Grupo H');
INSERT OR IGNORE INTO card_factor_groups(code,label) VALUES ('I','Grupo I');
INSERT OR IGNORE INTO card_factor_groups(code,label) VALUES ('J','Grupo J');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Diners','Diners','Personal','A','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Diners','Discover','Personal','A','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Diners','Visa Titanium','Personal','A','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Diners','Mastercard Titanium','Personal','A','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Diners','Diners','Corporativa','B','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Diners','Diners','Empresarial','C','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Diners','Diners','PYMES','D','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Diners','Diners','Minorista','E','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Diners','Diners','Simple','F','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Diners','Diners','Ampliado','G','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Pichincha','Visa','Personal','A','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Pichincha','Visa','Corporativa','B','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Pichincha','Visa','Empresarial','C','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Pichincha','Visa','PYMES','D','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Pichincha','Mastercard','Personal','A','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Pichincha','Mastercard','Corporativa','B','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Pichincha','Mastercard','Empresarial','C','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Pichincha','Mastercard','PYMES','D','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco de Manabí','Visa','Única (la tabla no distingue categoría)','A','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco de Loja','Visa','Única (la tabla no distingue categoría)','A','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco de Andalucía','Visa','Única (la tabla no distingue categoría)','H','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco General Rumiñahui (BGR)','Visa','Personal','A','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco General Rumiñahui (BGR)','Visa','Corporativa','B','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco General Rumiñahui (BGR)','Visa','Empresarial','C','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco General Rumiñahui (BGR)','Visa','PYMES','D','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco del Pacífico','Mastercard','Única (la tabla no distingue categoría)','I','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco del Pacífico','Visa','Única (la tabla no distingue categoría)','I','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco del Pacífico','Pacificard','Única (la tabla no distingue categoría)','I','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Guayaquil','American Express','Única (la tabla no distingue categoría)','J','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Guayaquil','Visa','Única (la tabla no distingue categoría)','J','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_products(bank,brand,category,group_code,source,updated_at) VALUES ('Banco Guayaquil','Mastercard','Única (la tabla no distingue categoría)','J','DATAFAST 6.2 (correspondencia de bancos y grupos)','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',3,263,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',4,330,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',5,397,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',6,465,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',9,669,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',10,738,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',12,876,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',15,1085,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',18,1297,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',24,1729,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('A',36,2623,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',3,128,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',4,161,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',5,193,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',6,226,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',9,324,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',10,357,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',12,422,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',15,522,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',18,622,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',24,824,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('B',36,1235,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',3,167,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',4,209,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',5,251,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',6,294,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',9,422,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',10,465,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',12,551,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',15,681,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',18,812,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',24,1078,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('C',36,1621,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',3,160,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',4,201,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',5,242,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',6,282,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',9,405,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',10,447,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',12,529,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',15,654,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',18,780,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',24,1035,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('D',36,1556,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',3,426,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',4,534,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',5,644,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',6,754,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',9,1089,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',10,1202,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',12,1431,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',15,1779,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',18,2134,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',24,2864,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('E',36,4401,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',3,380,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',4,476,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',5,574,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',6,672,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',9,969,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',10,1070,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',12,1272,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',15,1581,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',18,1894,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',24,2537,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('F',36,3885,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',3,340,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',4,426,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',5,513,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',6,601,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',9,866,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',10,955,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',12,1136,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',15,1410,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',18,1688,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',24,2257,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('G',36,3445,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',3,262,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',4,328,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',5,395,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',6,462,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',9,665,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',10,733,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',12,870,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',15,1078,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',18,1289,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',24,1717,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('H',36,2605,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',3,261,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',4,327,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',5,393,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',6,459,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',9,661,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',10,728,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',12,865,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',15,1071,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',18,1280,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',24,1705,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('I',36,2585,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('J',3,268,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('J',4,336,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('J',5,405,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('J',6,473,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('J',9,681,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('J',10,750,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('J',12,891,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('J',15,1103,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('J',18,1319,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,updated_at) VALUES ('J',24,1758,'vigente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_factors(group_code,months,factor_bp,status,valid_from,source,version,note,updated_at) VALUES ('J',36,NULL,'pendiente','2026-10-01','DATAFAST · tabla de factores de diferido con intereses','6.2','Pendiente de confirmar: no legible en el texto recuperado del PDF. No se habilita hasta validarlo con el documento original.','2026-10-27T00:00:00-05:00');
INSERT OR IGNORE INTO card_surcharge_settings(id,percent_bp,fixed_cents,payer,methods,valid_from,active,validated,note,updated_at) VALUES (1,900,0,'cliente','["credito_corriente","diferido_con_intereses","diferido_sin_intereses"]','2026-10-01',1,0,'Recargo comercial solicitado por PC-DOCTOR. Pendiente de validación contractual, tributaria y comercial antes de trasladarlo al cliente.','2026-10-27T00:00:00-05:00');
INSERT INTO card_surcharge_history(percent_bp,fixed_cents,payer,methods,valid_from,valid_to,active,validated,note,changed_at,actor) SELECT percent_bp,fixed_cents,payer,methods,valid_from,valid_to,active,validated,'Carga inicial',updated_at,'Migración 076' FROM card_surcharge_settings WHERE id=1 AND NOT EXISTS (SELECT 1 FROM card_surcharge_history);
