# Respaldos automáticos en Google Drive (1.5.312)

Sustituye a MEGA Cloud (1.5.311) y a Microsoft OneDrive (1.5.309 y 1.5.310). **El respaldo lo hace el propio servidor**: no necesita Podman, ni agentes, ni que la computadora de la oficina esté encendida.

## Auditoría y decisión

- **Hosting:** Vercel (región `iad1`, la misma que la base Turso) con Python. El servidor **sí** puede respaldar en una función propia de hasta 300 s (`api/backup.py`). El resto de la aplicación sigue con su límite de 30 s.
- **Tareas programadas:** Vercel ejecuta cada tarea una vez al día. Hay una a las **02:00** de Ecuador y dos reintentos, a las **04:00** y a las **07:00**, que solo actúan si el respaldo del día no quedó verificado. Vercel puede retrasar el disparo unos minutos.
- **Google Drive API frente a rclone.** Se eligió la **API de Google Drive**, por tres motivos:
  1. Funciona con la biblioteca estándar de Python en el propio servidor. rclone es un binario que necesita configuración persistente y no encaja en funciones sin estado.
  2. Usa el permiso **mínimo** `drive.file`: Órdenes Pro solo ve y modifica los archivos y carpetas que él mismo crea, nunca el resto de tu Drive.
  3. Google calcula el **SHA-256** de cada archivo, lo que permite verificar la integridad en la nube.
- **Proveedores anteriores:**
  - **OneDrive:** nunca guardó un respaldo.
  - **MEGA:** dejó un respaldo **pendiente** el 21/11, que nunca se subió. Su copia cifrada sigue en el equipo de la oficina y su copia local está verificada. El panel lo muestra como «No subido (proveedor retirado)» y **ya no cuenta como pendiente**. El registro no se modifica.
  - **No se borra** ningún respaldo, ni de MEGA ni de los locales.

## Cómo funciona

1. **Comprobación previa.** Si falta la conexión, la configuración o la clave, no se hace el respaldo y se explica el motivo. **Nunca se anota un respaldo en la nube que no ocurrió.**
2. **Bloqueo.** No puede haber dos respaldos a la vez.
3. **Copia consistente.** El esquema y todas las filas se leen dentro de **una sola transacción de lectura**. Se comprueba con `integrity_check`, `foreign_key_check` y el recuento de cada tabla.
4. **Compresión y cifrado:** gzip y **AES-256-GCM** con `BACKUP_ENCRYPTION_KEY`, que ya está en Vercel.
5. **Nombre automático:** `ordenes-pro-AAAAMMDD-HHMMSS-<diario|semanal|mensual>.sqlite.gz.enc`.
6. **Subida reanudable por partes** a `PC-DOCTOR S.A./Órdenes Pro/Respaldos Base de Datos`. La carpeta se crea sola y, si alguien la borró, se vuelve a crear.
7. **Verificación real, en tres pasos:**
   - Google confirma que el archivo existe con su tamaño y que su **SHA-256** coincide con el calculado antes de subirlo. Si no coincide, el archivo va a la papelera y se registra el error.
   - El archivo **se descarga de nuevo**.
   - Se descifra y se **restaura en una base aislada** con los mismos recuentos que la central.

   **Solo entonces** cuenta como respaldado y el panel dice «Protegido».
8. **Conservación 30/12/12:** lo que sobra va a la **papelera** de Google Drive, recuperable 30 días. Los archivos ajenos nunca se tocan.
9. **Prueba de restauración semanal automática** del último respaldo.
10. **Copia local independiente:** el equipo de la oficina sigue haciendo su copia local verificada cada día a las **03:00**, y al encenderlo si estaba apagado. No es necesaria para la nube.

## Panel (Configuración → Respaldos, solo administración)

- **Aviso de protección:** solo dice «Protegido en Google Drive» con un respaldo subido **y** verificado. Antes indica claramente que los datos **no** están protegidos en la nube.
- **Estados:**
  - base central;
  - copia local de la oficina;
  - Google Drive (conectado, sin conectar o vencido);
  - espacio usado y total;
  - último respaldo correcto en Drive;
  - próximos respaldos y reintentos, con el resultado de la última ejecución;
  - pendiente y errores (reintento previsto o último error).
- **Botones:** Realizar respaldo ahora, Verificar conexión, Crear carpeta, Verificar integridad y Restauración de prueba (pide escribir `RESTAURAR`, es aislada y **no toca producción**).
- **Asistente para conectar:**
  1. **Cliente OAuth de Google Cloud:** el secreto se guarda **cifrado** en el servidor y nunca vuelve al navegador.
  2. **Conectar Google Drive:** OAuth 2.0 con PKCE en la página de Google. **Órdenes Pro nunca pide la contraseña de Google.**
  3. **Primer respaldo y verificación.**
- **Historial unificado**, sin inventar registros. Incluye la copia anterior de 37,8 MB.

## Alertas (se retiran solas al corregirse la causa)

| Alerta | Cuándo aparece |
|---|---|
| Respaldo de la base central atrasado | Sin un respaldo **verificado** en 30 h |
| Falló el último respaldo en Google Drive | El último intento terminó con error |
| Conexión con Google Drive vencida | Google rechazó el acceso; el mensaje explica la causa probable (revocado, contraseña cambiada o app en modo «Prueba», que caduca a los 7 días) |
| Respaldos sin copia en Google Drive | Google Drive no está conectado |
| Espacio en Google Drive casi lleno | 90 % ocupado |

## Configuración (una sola vez, unos 10 minutos, gratis y sin tarjeta)

1. **Crea el proyecto:** entra en https://console.cloud.google.com con tu cuenta de Google y crea el proyecto **Órdenes Pro Respaldos**.
2. **Activa la API:** APIs y servicios → Biblioteca → **Google Drive API** → Habilitar.
3. **Configura el consentimiento de OAuth** (Google Auth Platform):
   - **Tipo:** Externo.
   - **Nombre:** Órdenes Pro Respaldos, con tu correo de asistencia.
   - **Acceso a los datos:** añade el permiso `…/auth/drive.file`.
   - **Público:** pulsa **Publicar app**, para que quede en producción. **Importante:** en modo «Prueba», Google caduca el acceso a los 7 días.
4. **Crea el cliente:** Clientes → Crear cliente → **Aplicación web**. En **URI de redireccionamiento autorizados** escribe `https://ordenes-pro.vercel.app/api/backups/google/callback`.
5. **En Órdenes Pro**, Configuración → Respaldos:
   - pega el **ID de cliente** y el **Secreto del cliente** (paso 1);
   - pulsa **Conectar Google Drive** (paso 2);
   - pulsa **Realizar respaldo ahora**.

Claves del servidor, ya cargadas en Vercel (Production):

- `BACKUP_ENCRYPTION_KEY`: cifra los respaldos. **Guarda una copia offline**; sin ella no se puede recuperar ningún respaldo.
- `ONEDRIVE_TOKEN_KEY`: se reutiliza como clave que cifra el acceso a Google. También acepta el nombre `BACKUP_TOKEN_KEY`.

Si se definen `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`, tienen prioridad sobre lo guardado en el asistente.

## Recuperar

- **Desde el panel:** «Restauración de prueba», aislada.
- **Datos de un respaldo:** descarga el archivo desde Google Drive y ejecuta:

  ```bash
  BACKUP_ENCRYPTION_KEY=… python maintenance/backup-cloud.py --descifrar archivo.sqlite.gz.enc --salida restaurada.sqlite3
  ```

  Nunca sobrescribe.
- **Volver a poner producción desde un respaldo:** solo por decisión administrativa expresa.
  1. Crea una base **nueva** en Turso.
  2. Verifícala.
  3. Cambia `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN` en Vercel.

  La base anterior se conserva.

## Pruebas

- **`local/tests/test_gdrive_backup.py`:** 16 escenarios con Google (OAuth y Drive v3) **simulado**, sin cuentas reales ni internet:
  - asistente con el secreto cifrado y nunca devuelto;
  - permiso mínimo `drive.file`, PKCE, acceso offline y `state` de un solo uso;
  - carpeta automática;
  - errores de Google explicados;
  - verificar conexión, espacio y crear carpeta;
  - permisos y CSRF;
  - respaldo bloqueado con motivo hasta conectar;
  - respaldo cifrado, con SHA-256 confirmado por Google, nueva descarga y restauración aislada;
  - verificar integridad y restauración de prueba;
  - archivo alterado, detectado por el SHA-256 de Google, a la papelera y con alerta;
  - conservación 30/12/12 con papelera, sin tocar archivos ajenos;
  - bloqueo contra ejecuciones simultáneas;
  - tarea programada con `CRON_SECRET`, reintentos que no repiten lo ya verificado y que nunca afirman un respaldo sin Drive;
  - acceso vencido con explicación;
  - indicador de pendientes de proveedores retirados, sin modificar registros;
  - copia local de la oficina con su registro real;
  - alerta de atraso.
- **Prueba de navegador:** 17 comprobaciones del recorrido completo, de «Sin configurar» a «Protegido», con Google simulado, en 1440, 1024, 768, 390 y 320 px, sin errores de consola.
