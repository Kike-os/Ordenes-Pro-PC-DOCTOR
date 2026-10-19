-- Catálogo de servicios de la Agenda: categorías, palabras de búsqueda, servicios nuevos y citas con varios servicios.
-- No modifica nombres, duraciones ni estado de los servicios existentes, ni datos de citas: solo añade columnas, tablas y servicios.
-- Un servicio nuevo se agrega solo si no existe otro con el mismo código o el mismo nombre. Equivalencias que NO se duplican:
-- «Programación y recuperación de BIOS» (bios), «Asistencia técnica remota» = «Servicio de Administración Remota» (remota),
-- «Reparación de impresoras» = «Servicio para impresoras» (impresoras) y «Diagnóstico y reparación de placas electrónicas» =
-- «Reparación electrónica» (electronica): quedan como palabras de búsqueda del servicio existente.
ALTER TABLE appointment_services ADD COLUMN category TEXT NOT NULL DEFAULT 'Otros servicios';
ALTER TABLE appointment_services ADD COLUMN keywords TEXT NOT NULL DEFAULT '';
UPDATE appointment_services SET category='Diagnóstico y reparación' WHERE code IN ('diagnostico','portatiles','computadoras','electronica','impresoras');
UPDATE appointment_services SET category='BIOS' WHERE code IN ('bios');
UPDATE appointment_services SET category='Mantenimiento' WHERE code IN ('mantenimiento','correctivo');
UPDATE appointment_services SET category='Redes y asistencia remota' WHERE code IN ('remota');
UPDATE appointment_services SET category='Otros servicios' WHERE code IN ('otros','retiro');
UPDATE appointment_services SET keywords='asistencia técnica remota soporte remoto' WHERE code='remota';
UPDATE appointment_services SET keywords='reparación de impresoras' WHERE code='impresoras';
UPDATE appointment_services SET keywords='diagnóstico y reparación de placas electrónicas placa madre' WHERE code='electronica';
UPDATE appointment_services SET keywords='programación recuperación flasheo' WHERE code='bios';
UPDATE appointment_services SET keywords='revisión evaluación' WHERE code='diagnostico';
UPDATE appointment_services SET keywords='limpieza pasta térmica' WHERE code='mantenimiento';
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'licencia','Compra de licencia de software',30,1,'Software, sistemas y licencias','windows office microsoft 365 antivirus kaspersky eset nod32 mcafee norton licencia original' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='licencia' OR lower(label)=lower('Compra de licencia de software'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'bios_desbloqueo','Desbloqueo de BIOS',90,1,'BIOS','bloqueo bios contraseña' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='bios_desbloqueo' OR lower(label)=lower('Desbloqueo de BIOS'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'bios_clave','Recuperación de contraseña de BIOS',90,1,'BIOS','olvidé contraseña clave bios password' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='bios_clave' OR lower(label)=lower('Recuperación de contraseña de BIOS'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'bios_actualizacion','Actualización de BIOS',60,1,'BIOS','actualizar firmware bios' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='bios_actualizacion' OR lower(label)=lower('Actualización de BIOS'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'bios_corrupta','Reparación de BIOS corrupta',120,1,'BIOS','bios dañada corrupta no enciende flasheo' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='bios_corrupta' OR lower(label)=lower('Reparación de BIOS corrupta'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'sistema_operativo','Instalación de Windows y otros sistemas operativos',120,1,'Software, sistemas y licencias','formateo windows 10 windows 11 linux sistema operativo' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='sistema_operativo' OR lower(label)=lower('Instalación de Windows y otros sistemas operativos'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'antivirus','Instalación y configuración de antivirus',45,1,'Software, sistemas y licencias','antivirus seguridad protección' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='antivirus' OR lower(label)=lower('Instalación y configuración de antivirus'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'virus','Eliminación de virus y malware',90,1,'Software, sistemas y licencias','virus malware limpieza seguridad' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='virus' OR lower(label)=lower('Eliminación de virus y malware'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'datos','Recuperación y respaldo de datos',120,1,'Software, sistemas y licencias','respaldo backup recuperar archivos datos' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='datos' OR lower(label)=lower('Recuperación y respaldo de datos'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'bisagras','Reparación de bisagras',90,1,'Diagnóstico y reparación','bisagra tapa portátil' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='bisagras' OR lower(label)=lower('Reparación de bisagras'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'pantallas','Cambio de pantallas',90,1,'Diagnóstico y reparación','pantalla display lcd portátil' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='pantallas' OR lower(label)=lower('Cambio de pantallas'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'playstation','Mantenimiento de consolas PlayStation',90,1,'Mantenimiento','ps4 ps5 consola playstation limpieza' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='playstation' OR lower(label)=lower('Mantenimiento de consolas PlayStation'));
INSERT INTO appointment_services(code,label,duration_minutes,active,category,keywords) SELECT 'redes','Configuración de redes y Wi-Fi',60,1,'Redes y asistencia remota','wifi red router internet' WHERE NOT EXISTS (SELECT 1 FROM appointment_services WHERE code='redes' OR lower(label)=lower('Configuración de redes y Wi-Fi'));
-- Citas con varios servicios: la cita conserva su servicio principal (el primero) y su duración es la suma de los elegidos.
ALTER TABLE appointments ADD COLUMN services_summary TEXT NOT NULL DEFAULT '';
CREATE TABLE appointment_service_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 appointment_id INTEGER NOT NULL REFERENCES appointments(id),
 position INTEGER NOT NULL CHECK(position>=1),
 service_code TEXT NOT NULL REFERENCES appointment_services(code),
 label TEXT NOT NULL,
 duration_minutes INTEGER NOT NULL CHECK(duration_minutes>0),
 detail TEXT NOT NULL DEFAULT '',
 UNIQUE(appointment_id,position),
 UNIQUE(appointment_id,service_code)
);
CREATE INDEX appointment_service_items_service ON appointment_service_items(service_code);
