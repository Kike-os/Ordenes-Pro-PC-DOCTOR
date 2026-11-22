# Reconstruir Órdenes Pro desde un respaldo completo (1.5.313)

Google Drive guarda la copia, pero **no sustituye al servidor**. Esta guía sirve para volver a levantar el sistema si se pierde el servidor (Vercel) o la base central (Turso).

## Qué contiene cada respaldo completo

Archivo `ordenes-pro-AAAAMMDD-HHMMSS-<diario|semanal|mensual>-completo.tar.gz.enc`, guardado en `PC-DOCTOR S.A./Órdenes Pro/Respaldos Base de Datos` de tu Google Drive. Está cifrado con AES-256-GCM.

| Ruta dentro del archivo | Contenido |
|---|---|
| `base/ordenes-pro.sqlite3` | Base completa, en una copia consistente: todas las tablas y registros. **Fotos, documentos, adjuntos, firmas, logos de marca, comprobantes y XML/PDF de facturas están dentro de la base.** No hay archivos alojados en otros servicios; solo enlaces de proveedores, como las descargas de licencias |
| `codigo/` | El proyecto **tal como estaba desplegado**: `api/`, `local/` (backend, frontend, plantillas, migraciones, logos, bibliotecas incluidas), `maintenance/` (guiones de mantenimiento y de la copia de la oficina), `docs/`, pruebas, `vercel.json` (tareas programadas) y `requirements.txt` (dependencias) |
| `configuracion/variables-entorno.json` | Variables del servidor, con credenciales y claves: Turso, correo, WhatsApp, Azur/SRI, Turnstile, IA, claves de cifrado de los secretos guardados en la base, `CRON_SECRET` y acceso a Google Drive |
| `manifiesto.json` | Versión, *commit*, fecha, huella SHA-256 de **cada** archivo, recuentos de la base, variables guardadas y no configuradas, tareas programadas y lista de lo que falta |
| `LEEME-RESTAURAR.md` | Esta guía, resumida y con los datos de ese respaldo |

**No contiene `BACKUP_ENCRYPTION_KEY`,** la clave que lo descifra. Guardarla dentro de lo que protege anularía el cifrado. El manifiesto guarda solo su huella, para comprobar que tienes la clave correcta sin revelarla.

**Qué significa «completo».** El panel solo llama «completo» a un respaldo cuando se cumple todo esto:

- la base supera la comprobación de integridad;
- están todos los archivos de código esenciales y al menos 100 migraciones;
- están las variables imprescindibles: las de Turso con base central y `CRON_SECRET` en Vercel;
- tras **descargarlo de nuevo**, cada archivo coincide con su SHA-256.

Si falta algo, queda como **«incompleto»** y el panel dice exactamente qué falta.

## Guardar la clave de recuperación (independiente del servidor)

La clave está en el archivo `~/CLAVE-RESPALDOS-ORDENES-PRO.txt` del equipo de la oficina y en las variables de Vercel. **Sin ella no se puede recuperar ningún respaldo.**

1. Cópiala en tu **gestor de contraseñas** con el nombre «Órdenes Pro · clave de respaldos».
2. **Imprímela** y guárdala en un lugar seguro, separado del equipo.
3. Después **borra** el archivo de texto del equipo. El agente local ya tiene su copia protegida en `~/.config/ordenes-pro/backup.key`.

## Reconstruir el sistema

1. **Descarga** el respaldo completo más reciente desde Google Drive, o el anterior que quieras.
2. **Descifra y comprueba.** Sirve cualquier equipo con Python 3.12+ y `pip install cryptography`, más el código de este repositorio o el de un respaldo ya extraído:

   ```bash
   BACKUP_ENCRYPTION_KEY='la clave' python maintenance/backup-cloud.py --descifrar-completo ARCHIVO-completo.tar.gz.enc --salida restaurado
   ```

   El comando comprueba la huella de cada archivo y la integridad de la base, informa si el respaldo era completo y lo extrae en `restaurado/`. Nunca sobrescribe.
3. **Base de datos:** crea una base **nueva** en Turso desde el archivo y genera su token.

   ```bash
   turso db create ordenes-pro-restaurada --from-file restaurado/base/ordenes-pro.sqlite3
   turso db tokens create ordenes-pro-restaurada
   ```

   Sin Turso, copia el archivo a `codigo/local/var/ordenes.sqlite3` y usa SQLite local.
4. **Código:** sube `restaurado/codigo/` a un repositorio nuevo y crea el proyecto en Vercel (Framework Python, instalación `pip install -r requirements.txt`). Las tareas programadas de `vercel.json` se activan solas.
5. **Variables:** en Vercel → Settings → Environment Variables (Production):
   - carga las de `restaurado/configuracion/variables-entorno.json`;
   - cambia `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN` por los de la base nueva;
   - añade `BACKUP_ENCRYPTION_KEY` desde tu copia offline;
   - vuelve a desplegar.
6. **Reconecta los servicios externos.** Si cambia el dominio, actualiza las direcciones de retorno:
   - **Google Drive:** añade la nueva URI `https://<dominio>/api/backups/google/callback` en Google Cloud y pulsa «Conectar Google Drive».
   - **WhatsApp Business (Meta):** URL del webhook.
   - **Cloudflare Turnstile:** dominio permitido.
   - **Correo (Mail Pro), Azur (SRI), IA y Dell:** sus credenciales vienen en la base, cifradas con las claves restauradas, o en las variables. Comprueba con Configuración → Estado del sistema.
7. **Comprueba:** entra como administración y revisa Inicio, Órdenes, Clientes y el PDF de una orden. Después pulsa **«Crear respaldo completo ahora»** para volver a quedar protegido.

## Restauración de prueba (sin tocar nada)

En Configuración → Respaldos, **«Restauración de prueba»** (pide escribir `RESTAURAR`):

1. descarga el respaldo y comprueba cada archivo;
2. restaura la base en una copia aislada;
3. **arranca el código restaurado contra esa base, sin credenciales y con la red de salida bloqueada**, de modo que no puede enviar correos, notificaciones ni facturas;
4. prueba las funciones principales: sesión, órdenes, clientes, catálogo, sistema, el panel, el detalle de una orden y su PDF.

El resultado aparece función por función. Producción no se toca. Además se hace sola una vez por semana.
