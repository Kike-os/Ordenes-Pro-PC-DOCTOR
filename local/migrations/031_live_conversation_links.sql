-- Centro de Atención en Tiempo Real: una conversación puede vincularse a un cliente y a una orden reales.
ALTER TABLE adi_conversations ADD COLUMN client_id INTEGER REFERENCES clients(id);
ALTER TABLE adi_conversations ADD COLUMN order_id INTEGER REFERENCES orders(id);
