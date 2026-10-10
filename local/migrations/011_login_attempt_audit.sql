CREATE TABLE login_attempt_events (
 id INTEGER PRIMARY KEY,
 account_hash TEXT NOT NULL CHECK(length(account_hash)=64),
 ip_hash TEXT NOT NULL CHECK(length(ip_hash)=64),
 result TEXT NOT NULL CHECK(result IN ('failed','limited','success')),
 account_attempt INTEGER NOT NULL DEFAULT 0,
 ip_attempt INTEGER NOT NULL DEFAULT 0,
 created_at INTEGER NOT NULL
);
CREATE INDEX login_attempt_events_time ON login_attempt_events(created_at);
