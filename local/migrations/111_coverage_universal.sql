-- 1.5.301 · Cobertura Empresarial PC-DOCTOR para cualquier partida del presupuesto, con dos modalidades. Solo AGREGA: no cambia ni borra
-- coberturas, pagos, historial, caja ni inventario. Las coberturas existentes quedan como «interna» (costo interno), que es lo que eran.
--  · interna:   PC-DOCTOR asume total o parcialmente el costo (proveedor u operativo). El cliente sigue pagando el precio de su presupuesto.
--  · comercial: PC-DOCTOR asume total o parcialmente el precio de venta de la partida. Se muestra al cliente como «Beneficio PC-DOCTOR»
--               y reduce el importe de la línea (en la factura viaja como descuento de la línea). Solo en presupuestos editables.
ALTER TABLE part_coverages ADD COLUMN modality TEXT NOT NULL DEFAULT 'interna' CHECK(modality IN ('interna','comercial'));
ALTER TABLE part_coverages ADD COLUMN reason_code TEXT NOT NULL DEFAULT '';
-- Una cobertura viva por partida y modalidad (un repuesto en garantía puede tener ambas: precio exonerado y costo asumido).
DROP INDEX IF EXISTS part_coverages_one_live;
CREATE UNIQUE INDEX IF NOT EXISTS part_coverages_one_live_mode ON part_coverages(quote_id,line_position,line_description,modality) WHERE status IN ('solicitada','autorizada');
-- Catálogo configurable de motivos (administración agrega, renombra o desactiva; nunca se borran para no perder el historial).
CREATE TABLE IF NOT EXISTS coverage_reasons (
 code TEXT PRIMARY KEY CHECK(length(code) BETWEEN 2 AND 40),
 label TEXT NOT NULL CHECK(length(label) BETWEEN 3 AND 80),
 requires_note INTEGER NOT NULL DEFAULT 0 CHECK(requires_note IN (0,1)),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 position INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER IF NOT EXISTS coverage_reasons_no_delete BEFORE DELETE ON coverage_reasons BEGIN SELECT RAISE(ABORT,'Un motivo no se elimina: se desactiva'); END;
INSERT OR IGNORE INTO coverage_reasons(code,label,requires_note,active,position) VALUES
 ('garantia','Garantía de reparación',0,1,1),
 ('compensacion','Compensación por inconvenientes',1,1,2),
 ('error_interno','Error técnico interno',1,1,3),
 ('atencion_comercial','Atención comercial',0,1,4),
 ('cortesia','Cortesía empresarial',0,1,5),
 ('retrabajo','Retrabajo sin cargo',0,1,6),
 ('reposicion','Reposición de producto',0,1,7),
 ('otro','Otro motivo justificado',1,1,8);
