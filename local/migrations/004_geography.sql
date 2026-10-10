CREATE TABLE geo_provinces(code TEXT PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE geo_cantons(code TEXT PRIMARY KEY,name TEXT NOT NULL,province_code TEXT NOT NULL REFERENCES geo_provinces(code));
CREATE INDEX geo_cantons_province ON geo_cantons(province_code);
CREATE TABLE geo_parishes(code TEXT PRIMARY KEY,name TEXT NOT NULL,canton_code TEXT NOT NULL REFERENCES geo_cantons(code),kind TEXT NOT NULL,locality_code TEXT NOT NULL DEFAULT '');
CREATE INDEX geo_parishes_canton ON geo_parishes(canton_code);
CREATE TABLE geo_localities(code TEXT PRIMARY KEY,name TEXT NOT NULL,canton_code TEXT NOT NULL REFERENCES geo_cantons(code),kind TEXT NOT NULL);
CREATE TABLE geo_catalog(version TEXT PRIMARY KEY,source TEXT NOT NULL,retrieved_at TEXT NOT NULL,sha256 TEXT NOT NULL,source_url TEXT NOT NULL);
ALTER TABLE clients ADD COLUMN document_type TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN trade_name TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN province_code TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN canton TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN canton_code TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN parish TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN parish_code TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN locality_code TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN main_street TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN secondary_street TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN building_number TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN geo_version TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN reception_snapshot TEXT NOT NULL DEFAULT '';
CREATE TRIGGER immutable_reception_snapshot BEFORE UPDATE OF reception_snapshot ON orders
 WHEN OLD.reception_snapshot!='' AND NEW.reception_snapshot IS NOT OLD.reception_snapshot
 BEGIN SELECT RAISE(ABORT,'La recepción original debe conservarse'); END;
