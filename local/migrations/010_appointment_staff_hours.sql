CREATE TABLE appointment_staff_hours (
 technician_id INTEGER NOT NULL REFERENCES users(id),
 weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
 start_time TEXT NOT NULL,
 end_time TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
 PRIMARY KEY(technician_id,weekday),
 CHECK(start_time<end_time)
);
WITH RECURSIVE days(weekday) AS (SELECT 0 UNION ALL SELECT weekday+1 FROM days WHERE weekday<6)
INSERT INTO appointment_staff_hours(technician_id,weekday,start_time,end_time,enabled)
SELECT u.id,d.weekday,CASE WHEN d.weekday=5 THEN '09:00' ELSE '09:00' END,
       CASE WHEN d.weekday=5 THEN '13:00' ELSE '17:00' END,
       CASE WHEN d.weekday=6 THEN 0 ELSE 1 END
FROM users u CROSS JOIN days d WHERE u.active=1 AND u.role IN ('administrador','tecnico');
