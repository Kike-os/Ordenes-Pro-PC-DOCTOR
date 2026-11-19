-- 1.5.305 · Gastos internos de la orden: categoría, fecha y comprobante opcional de cada gasto. Solo AGREGA columnas con valor por defecto:
-- no cambia ni borra coberturas, pagos, historial, presupuestos, caja ni inventario. Las coberturas existentes quedan sin categoría.
--  · expense_kind: categoría del gasto interno (transporte, terceros, materiales…). Vacía en las coberturas de partidas.
--  · expense_date: fecha en que ocurrió el gasto (AAAA-MM-DD). Vacía = la fecha de registro.
--  · file_id: comprobante opcional (JPG, PNG o PDF) guardado en payment_files, igual que los comprobantes de Caja.
ALTER TABLE part_coverages ADD COLUMN expense_kind TEXT NOT NULL DEFAULT '';
ALTER TABLE part_coverages ADD COLUMN expense_date TEXT NOT NULL DEFAULT '';
ALTER TABLE part_coverages ADD COLUMN file_id INTEGER REFERENCES payment_files(id);
