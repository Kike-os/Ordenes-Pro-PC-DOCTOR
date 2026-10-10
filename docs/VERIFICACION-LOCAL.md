# Verificación local — 2026-10-09

15 pruebas automatizadas aprobadas en bases temporales sin datos reales. Cobertura: contraseña con sal, migraciones repetibles, acceso privado, errores genéricos, límite de intentos, cookies/CSRF, origen, roles, órdenes y conteos reales, auditoría inmutable, recuperación de un uso, caducidad, revocación de sesiones y manejo de fallo SMTP. JavaScript validado con node --check; Python compilado sin errores.

No se pudo verificar HTTP ni diseño en un navegador desde el entorno de ejecución: crear un socket local devuelve PermissionError, Operation not permitted. El servidor NO está activo. Ejecutar iniciar-local.sh desde la terminal de Omarchy y revisar en http://127.0.0.1:8010.

No hay administrador precargado, no se ha configurado SMTP y no se han enviado correos. No se han subido archivos al hosting. La recuperación necesita SMTP real y una comprobación de entrega pendiente. El logotipo original está pendiente.

Estas pruebas corresponden a una evaluación local con Python/SQLite, no a una certificación de producción ni de compatibilidad con cPanel.
