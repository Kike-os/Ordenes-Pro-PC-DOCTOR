CREATE TABLE IF NOT EXISTS proforma_identity_passkeys (
    link_id INTEGER PRIMARY KEY REFERENCES proforma_links(id),
    passkey_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
