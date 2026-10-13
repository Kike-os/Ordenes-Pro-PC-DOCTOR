-- Eliminación lógica de borradores de presupuesto: el borrador sale de las listas activas y deja de editarse, pero su registro y su
-- historial se conservan para auditoría. Solo aplica a borradores que nunca se enviaron (lo comprueba el servidor).
ALTER TABLE quotes ADD COLUMN deleted_at TEXT NOT NULL DEFAULT '';
ALTER TABLE quotes ADD COLUMN deleted_by INTEGER REFERENCES users(id);
