CREATE TABLE appointment_mail (
 id INTEGER PRIMARY KEY,
 appointment_id INTEGER NOT NULL REFERENCES appointments(id),
 kind TEXT NOT NULL CHECK(kind IN ('request','confirmation','rescheduled','cancelled')),
 generation INTEGER NOT NULL,
 recipient TEXT NOT NULL DEFAULT '',
 result TEXT NOT NULL CHECK(result IN ('sent','failed','no_email','no_consent','not_configured')),
 detail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 UNIQUE(appointment_id,kind,generation)
);
