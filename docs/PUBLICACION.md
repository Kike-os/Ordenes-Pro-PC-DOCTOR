# Publicación: pendiente de verificar Tecnoweb

Destino previsto, todavía no comprobado: `/home/ecpcdoct/public_html/ordenes-pro.ecuadorpcdoctor.com`.

No confundir este destino con la raíz del dominio principal. No escribir en él hasta comprobar la configuración del subdominio en cPanel y obtener autorización para la primera publicación.

## Inspección de solo lectura

1. Comprobar TCP a server112.tecnoweb.net:22.
2. Pedir a Tecnoweb la huella SHA256 del servidor por un canal oficial y compararla antes de aceptar la clave de host. No desactivar StrictHostKeyChecking.
3. Conectar como ecpcdoct usando la clave privada local; nunca subir esa clave.
4. Comprobar directorio con `pwd`, `ls -ld` y `realpath`; contrastar con Dominios en cPanel.
5. Consultar `php -v`, `php -m`, `command -v composer`, `command -v git` y `crontab -l`. Confirmar versión de MySQL/MariaDB y permisos del usuario de aplicación mediante el panel, sin mostrar contraseñas.

## Arquitectura y procedimiento por concretar

Si solo hay PHP/MySQL, implementar la versión de producción con Laravel compatible con la versión de PHP confirmada, reutilizando diseño y flujos de esta evaluación. Compilar recursos en Omarchy. No requiere Node permanente.

Antes de habilitar sincronización, preparar un entorno de staging y un script ajustado a las capacidades reales: ejecutar pruebas, generar artefacto sin .env/claves/datos, comprobar destino exclusivo, respaldar base y archivos persistentes, aplicar migraciones compatibles, activar versión, verificar salud y revertir código si falla. No automatizar migraciones inversas destructivas. Mantener archivos de usuarios fuera de los directorios de versiones.

Preferir releases y enlace atómico cuando SSH y el proveedor lo permitan; con SFTP, documentar un cambio controlado en mantenimiento, sin sobrescritura general de archivos ni borrado remoto. Guardar credenciales en un gestor de secretos o configuración SSH privada, nunca en Git.

HTTPS: comprobar certificado del subdominio y renovación en AutoSSL o herramienta autorizada por Tecnoweb, configurar redirección HTTPS para este subdominio y cookies Secure. Publicar únicamente el directorio public de Laravel y desactivar listado de directorios según Apache/Nginx confirmado. APP_DEBUG=false y permisos mínimos. No aplicar reglas globales del dominio principal.

La primera autorización debe identificar versión, pruebas, destino verificado, respaldo y reversión. Actualmente ninguno de estos pasos de producción se ha ejecutado. Este documento es un procedimiento previsto, no una integración de despliegue habilitada.
