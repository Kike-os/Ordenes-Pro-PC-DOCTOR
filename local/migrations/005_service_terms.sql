CREATE TABLE service_terms (
 id TEXT PRIMARY KEY,
 version TEXT NOT NULL UNIQUE,
 effective_date TEXT NOT NULL,
 title TEXT NOT NULL,
 full_text TEXT NOT NULL,
 compact_text TEXT NOT NULL,
 content_hash TEXT NOT NULL,
 published_at TEXT NOT NULL,
 published_by INTEGER NOT NULL REFERENCES users(id)
);
CREATE INDEX service_terms_effective ON service_terms(effective_date,published_at);
CREATE TRIGGER immutable_service_terms_update BEFORE UPDATE ON service_terms
 BEGIN SELECT RAISE(ABORT,'Las condiciones publicadas son inmutables; publica una nueva versión'); END;
CREATE TRIGGER immutable_service_terms_delete BEFORE DELETE ON service_terms
 BEGIN SELECT RAISE(ABORT,'Las condiciones publicadas deben conservarse'); END;
ALTER TABLE orders ADD COLUMN terms_document_id TEXT REFERENCES service_terms(id);
ALTER TABLE orders ADD COLUMN terms_acceptance_id TEXT;
CREATE UNIQUE INDEX orders_terms_acceptance_unique ON orders(terms_acceptance_id) WHERE terms_acceptance_id IS NOT NULL;
ALTER TABLE orders ADD COLUMN terms_accepted_at TEXT;
ALTER TABLE orders ADD COLUMN terms_mechanism TEXT;
ALTER TABLE orders ADD COLUMN terms_acceptor TEXT;
ALTER TABLE orders ADD COLUMN terms_actor_id INTEGER REFERENCES users(id);
CREATE TRIGGER immutable_order_terms BEFORE UPDATE OF terms_document_id,terms_acceptance_id,terms_accepted_at,terms_mechanism,terms_acceptor,terms_actor_id ON orders
 WHEN OLD.terms_acceptance_id IS NOT NULL AND (NEW.terms_document_id IS NOT OLD.terms_document_id OR NEW.terms_acceptance_id IS NOT OLD.terms_acceptance_id OR NEW.terms_accepted_at IS NOT OLD.terms_accepted_at OR NEW.terms_mechanism IS NOT OLD.terms_mechanism OR NEW.terms_acceptor IS NOT OLD.terms_acceptor OR NEW.terms_actor_id IS NOT OLD.terms_actor_id)
 BEGIN SELECT RAISE(ABORT,'La aceptación original debe conservarse'); END;
