# ÓRDENES PRO — inspección inicial

Fecha: 2026-10-09. Dominio previsto: https://ordenes-pro.ecuadorpcdoctor.com/

## Evidencia disponible

- No se encontró un proyecto de ÓRDENES PRO en el directorio local Work.
- Node.js y Git están disponibles localmente. PHP, Composer y MySQL no están en PATH.
- No existe ~/.ssh; no se encontró una conexión SSH configurada allí.
- La consulta pública del subdominio con la herramienta web no permitió acceder al sitio. Esto no demuestra que el dominio esté caído ni permite deducir el proveedor.
- No se realizaron conexiones autenticadas, publicaciones ni modificaciones remotas.

## Información necesaria antes de elegir la arquitectura

Confirmar con el panel o documentación del proveedor:

1. Proveedor, plan y panel de administración.
2. Versiones de PHP admitidas, extensiones PDO MySQL, OpenSSL, mbstring y soporte de Argon2id; límites de memoria y ejecución.
3. MySQL o MariaDB: versión, base exclusiva, usuario con permisos limitados y política de respaldos.
4. SSH/SFTP, puerto, Git, Composer y tareas cron disponibles. Configurar credenciales fuera del repositorio, sin compartir contraseñas por chat.
5. Directorio raíz exacto del subdominio y posibilidad de apuntarlo a public/. No deducirlo del dominio ni usar la raíz del sitio principal.
6. Servidor web, reglas de reescritura, TLS y renovación automática del certificado del subdominio.
7. SMTP autenticado o servicio transaccional autorizado para recuperación de contraseñas.
8. Logotipo original proporcionado por el propietario; no recrearlo ni extraer uno de terceros.

## Arquitectura candidata, pendiente de verificación

Si el hosting admite PHP compatible y MySQL/MariaDB, evaluar Laravel con vistas de servidor y recursos estáticos compilados localmente. No requiere un proceso Node.js permanente en producción. Confirmar versiones y requisitos oficiales antes de instalar dependencias. Si no admite Laravel, decidir otra arquitectura compatible a partir de evidencia del proveedor.

Modelo inicial: usuarios y roles, clientes, equipos, estados, órdenes y eventos de auditoría; relaciones mediante claves foráneas e índices. Migraciones incrementales, pruebas con datos ficticios y sin registros de clientes reales.

Autenticación prevista: hashing seguro, sesiones con cookies HttpOnly/Secure/SameSite, CSRF, limitación de intentos, errores genéricos, recuperación con tokens temporales de un solo uso y alta inicial de administrador mediante comando privado. Recordarme conservará un token revocable, nunca la contraseña. No habrá registro público administrativo.

## Criterios del despliegue

- Ejecutar pruebas y validaciones antes de generar un artefacto.
- Excluir secretos, .env, dependencias de desarrollo y datos de pruebas del artefacto público.
- Separar código de archivos persistentes, sesiones y base de datos.
- Usar variables de entorno de producción; depuración desactivada.
- Respaldar antes de migraciones y verificar restauración.
- Preferir versiones en directorios separados con cambio atómico cuando el proveedor lo permita.
- Preparar reversión del código; no ejecutar migraciones inversas destructivas como mecanismo automático de reversión.
- Validar salud, acceso, autorización y recuperación de contraseña en un entorno de prueba.
- Solicitar autorización explícita para el primer despliegue con la versión y destino ya identificados.
- No modificar ecuadorpcdoctor.com ni otras aplicaciones.

## Estado

Inspección local completada. Capacidades y raíz del hosting sin verificar. Implementación, pruebas funcionales, configuración SMTP/TLS y despliegue pendientes. Este documento no representa un sistema implementado.
