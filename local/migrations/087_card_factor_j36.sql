-- Factor DATAFAST 6.2 del grupo J (Banco Guayaquil: American Express, Visa y Mastercard) a 36 meses: 26,67 %.
-- La migración 076 lo dejó «pendiente» porque la cifra no era legible en el texto recuperado del PDF. Administración envió el 03/11/2026 la
-- tabla original (DATAFAST versión 6.2, aprobada el 01/10/2026), donde se lee 26,67 %. La fila pendiente no tenía valor: se completa (misma
-- versión de la tabla) y su nota conserva el estado anterior. Solo cambia esa fila y solo si sigue pendiente; no se borra nada.
UPDATE card_factors SET factor_bp=2667,status='vigente',
 note='Confirmado el 03/11/2026 con la tabla original DATAFAST 6.2 enviada por administración (26,67 %). Antes: pendiente, no legible en el texto recuperado del PDF.',
 updated_at='2026-11-03T18:15:00-05:00'
 WHERE group_code='J' AND months=36 AND version='6.2' AND status='pendiente' AND factor_bp IS NULL;
