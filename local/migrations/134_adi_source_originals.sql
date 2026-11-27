CREATE TABLE IF NOT EXISTS adi_lab_source_originals (
    knowledge_id INTEGER PRIMARY KEY REFERENCES adi_lab_knowledge(id),
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL CHECK(bytes>0 AND bytes<=1000000),
    data BLOB NOT NULL
);
