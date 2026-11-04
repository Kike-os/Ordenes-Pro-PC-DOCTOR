-- Control de series del inventario (04/11/2026): una unidad en existencia (disponible o reservada) con serie escrita debe ocupar esa serie.
-- Con el índice único inventory_units_serial (migración 073), dos unidades en existencia nunca comparten serie, aunque un error de la
-- aplicación intentara reactivar una unidad sin ocupar su serie. SOLO crea disparadores: no modifica ni borra ningún dato.
-- La normalización es la misma de la aplicación (inventory.serial_key): mayúsculas y sin espacios; clean_serial solo admite ASCII imprimible.
-- Reversión: DROP TRIGGER inventory_units_stock_serial_insert; DROP TRIGGER inventory_units_stock_serial_update;
CREATE TRIGGER inventory_units_stock_serial_insert BEFORE INSERT ON inventory_units
 WHEN NEW.status IN ('disponible','reservada') AND NEW.serial!='' AND NEW.serial_key!=REPLACE(UPPER(NEW.serial),' ','')
 BEGIN SELECT RAISE(ABORT,'Una unidad en existencia debe ocupar su serie.'); END;
CREATE TRIGGER inventory_units_stock_serial_update BEFORE UPDATE OF status,serial,serial_key ON inventory_units
 WHEN NEW.status IN ('disponible','reservada') AND NEW.serial!='' AND NEW.serial_key!=REPLACE(UPPER(NEW.serial),' ','')
 BEGIN SELECT RAISE(ABORT,'Una unidad en existencia debe ocupar su serie.'); END;
