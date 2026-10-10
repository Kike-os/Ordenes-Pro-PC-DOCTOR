ALTER TABLE clients ADD COLUMN client_type TEXT NOT NULL DEFAULT 'natural' CHECK(client_type IN ('natural','empresa'));
ALTER TABLE clients ADD COLUMN country TEXT NOT NULL DEFAULT 'Ecuador';
ALTER TABLE clients ADD COLUMN identity_key TEXT;
CREATE UNIQUE INDEX clients_identity_unique ON clients(identity_key) WHERE identity_key IS NOT NULL;
-- Los duplicados históricos permanecen intactos y se detectan al registrar otra ficha.
UPDATE clients SET identity_key=CASE WHEN document_type!='' THEN document_type WHEN length(identification)=10 THEN 'cedula' ELSE 'ruc' END||':'||identification
 WHERE identification!='' AND (SELECT count(*) FROM clients c WHERE c.identification=clients.identification)=1;
