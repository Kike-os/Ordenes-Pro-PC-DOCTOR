ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN identification TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN job_title TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN approval TEXT NOT NULL DEFAULT 'approved' CHECK(approval IN ('approved','pending','rejected'));
ALTER TABLE users ADD COLUMN requested_at INTEGER;
ALTER TABLE users ADD COLUMN reviewed_by INTEGER REFERENCES users(id);
ALTER TABLE users ADD COLUMN reviewed_at INTEGER;
