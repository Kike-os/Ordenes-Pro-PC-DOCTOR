# Respaldos automáticos en Microsoft OneDrive (1.5.309 · 1.5.310)

## Auditoría (21/11/2026)

### Por qué saltó «Respaldo de la base central atrasado»

El respaldo dependía del equipo de la oficina (MI-DATA-CENTER), con el temporizador `ordenes-pro-respaldo.timer` a las 02:30. Su registro muestra:

- copias correctas los días 17, 18 y 19;
- el equipo **apagado** del 19 al 21;
- el 21 a las 16:37, al encenderlo, recuperó la copia perdida (`Persistent=true`) y terminó bien.

No había credenciales vencidas ni errores de almacenamiento o de conexión.

### El respaldo de 37,8 MB y el historial vacío

Es la copia de la oficina del 21/11 a las 16:37 (39 665 664 bytes, 202 clientes y 23 órdenes). La hizo el guion anterior, que solo dejaba un resumen (`system_state.cloud_backup`) y no el historial nuevo. Por eso el indicador lo mostraba y el historial salía vacío.

**Comprobación del archivo** (`~/Respaldos-OrdenesPro/ordenes-pro-nube-20261121-163742.sqlite3`):

- su SHA-256 coincide con el registrado al crearlo;
- restaurado en un entorno aislado pasa `integrity_check`, con 0 errores de claves foráneas;
- contiene 219 tablas, 11 213 filas, 202 clientes y 23 órdenes, las 23 vinculadas a su cliente.

**Cómo se unificó el historial, sin inventar registros:**

- La copia que solo constaba en el resumen aparece como «registro anterior» con sus datos reales. Antes de sobrescribir el resumen se guarda en el historial.
- Cada copia nueva de la oficina incorpora una sola vez las líneas `OK` de su registro real (`respaldos.log`). Las líneas `ERROR` nunca se convierten en respaldos.

### Estado encontrado

| Elemento | Situación |
|---|---|
| Tareas de Vercel | Avisos y estabilidad, protegidas con `CRON_SECRET`; ninguna de respaldo |
| Equipo de la oficina | Copia diaria a las 02:30; funciona cuando el equipo está encendido |
| GitHub Actions (1.5.309) | Necesitaba un token de Turso que no se puede copiar desde producción. **Sustituido** por la tarea del servidor; el flujo y sus secretos se retiraron |
| Claves en Vercel | `ONEDRIVE_TOKEN_KEY` y `BACKUP_ENCRYPTION_KEY` cargadas en Production como sensibles |
| Microsoft | Sin aplicación registrada: la cuenta es personal y Microsoft exige un directorio de Azure gratuito para registrar aplicaciones |

## Cómo funciona desde la 1.5.310

| Pieza | Dónde | Qué hace |
|---|---|---|
| Respaldo diario en OneDrive | **Servidor**: tarea programada de Vercel `/api/cron/backup` a las 07:00 UTC, es decir a las 02:00 de Ecuador | Copia la base, la verifica, la cifra, la sube, la descarga y la restaura aislada. No depende del navegador ni de ningún equipo |
| «Realizar respaldo ahora» y «Verificar respaldo» | **Servidor**, misma función | Igual que el anterior, en el momento |
| Función de respaldos | `api/backup.py`, con un plazo propio de **300 s** | El resto de la aplicación sigue en `api/index.py` con 30 s |
| Copia local independiente | Equipo de la oficina, a las 02:30 | Copia SQLite verificada; conserva 30 |
| Motor | `local/backup_runner.py` | Lo usan el servidor y el guion de la oficina |

### Procedimiento de cada respaldo

1. **Comprobación previa.** Si falta algo (aplicación de Microsoft, conexión o clave), el respaldo no se hace y se explica el motivo. **Nunca se anota un respaldo en la nube que no ocurrió.**
2. **Bloqueo.** No puede haber dos respaldos a la vez; el bloqueo caduca solo a los 45 minutos si el proceso muere.
3. **Copia consistente.** El esquema y todas las filas se leen dentro de **una sola transacción de lectura**. Si esa transacción no se sostiene, se copia sin ella con doble recuento y se repite si algo cambió durante la copia. Hay hasta 3 intentos.
4. **Comprobación de la copia:** `integrity_check`, `foreign_key_check` y el recuento de cada tabla.
5. **Compresión y cifrado:** gzip y **AES-256-GCM** con `BACKUP_ENCRYPTION_KEY`.
6. **Nombre automático:** `ordenes-pro-AAAAMMDD-HHMMSS-<diario|semanal|mensual>.sqlite.gz.enc`.
7. **Subida por partes** con Microsoft Graph a `PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos`. La carpeta se crea si falta y nunca se reemplaza un archivo existente.
8. **Verificación real.** El archivo **se descarga de nuevo**, se compara su **SHA-256**, se descifra y se **restaura en una base aislada** con los mismos recuentos que la central. Solo entonces es válido.
9. **Retención 30/12/12** sobre las fechas. Lo que sobra va a la **papelera** de OneDrive. Los archivos ajenos nunca se tocan.
10. **Registro.** Cada respaldo queda en el historial con fecha, tipo, destino, archivo, tamaño, SHA-256, estado, verificación y error. La última ejecución programada queda en `backup_cron`, también cuando se omite por falta de configuración.

### Panel (Configuración → Respaldos, solo administración)

- **Estados separados:**
  - base central;
  - copia local de la oficina;
  - sincronización con el servidor;
  - Microsoft OneDrive, con su último respaldo en la nube;
  - próximo respaldo programado, con el resultado de la última ejecución.

  La copia de la oficina **nunca** se presenta como respaldo en la nube.
- **Asistente en tres pasos:**
  1. **Datos de la aplicación registrada en Microsoft:** Id. de aplicación, tipo de cuenta y secreto.
     - Tipos de cuenta: Personal o Familiar (`consumers`), Empresa (directorio concreto) o Personal y empresa (`common`).
     - El secreto se envía una vez y el servidor lo guarda **cifrado** con `ONEDRIVE_TOKEN_KEY`; nunca vuelve al navegador. Si se deja en blanco al editar, se conserva.
     - Las variables `MS_CLIENT_ID`, `MS_CLIENT_SECRET` y `MS_TENANT_ID`, si existen, tienen prioridad sobre lo guardado.
  2. **Conectar Microsoft OneDrive:** OAuth 2.0 con PKCE y un `state` de un solo uso, válido 10 minutos. Los errores de Microsoft se explican en claro (secreto incorrecto, tipo de cuenta, dirección de retorno, permiso denegado). La carpeta se crea automáticamente.
  3. **Respaldo de prueba y verificación**, con los botones habilitados solo cuando todo está listo. Si están desactivados, el panel dice por qué.
- **Historial unificado**, con «Verificar» y «Restaurar respaldo» en cada respaldo de OneDrive. Restaurar pide escribir `RESTAURAR`, se hace en una **base aislada** y **no toca producción**.

### Alertas (centro de notificaciones)

| Alerta | Cuándo |
|---|---|
| Respaldo de la base central atrasado | No hay un respaldo **verificado**, de OneDrive o de la oficina, en 30 h. Se retira sola con el siguiente respaldo verificado |
| Falló el último respaldo en OneDrive | El último respaldo de OneDrive terminó en error |
| Conexión con OneDrive vencida | Microsoft rechazó el acceso guardado |
| Respaldos sin copia en OneDrive | La aplicación está configurada, pero no hay ninguna cuenta conectada |

## Lo que falta para que funcione en producción

1. **Publicar la 1.5.310**, con tu autorización.
2. **Registrar la aplicación en Microsoft.**
   - Con cuenta personal hace falta antes **activar la cuenta gratuita de Azure** (https://azure.microsoft.com/free), con verificación por SMS y tarjeta, sin cargo. Así se crea tu directorio.
   - Después, en https://portal.azure.com → Registros de aplicaciones → Nuevo registro:
     - **Tipos de cuenta:** *Solo cuentas personales de Microsoft*.
     - **URI de redirección (Web):** `https://ordenes-pro.vercel.app/api/backups/onedrive/callback`.
     - **Permisos delegados de Microsoft Graph:** `offline_access`, `User.Read` y `Files.ReadWrite`.
     - **Secreto de cliente:** 24 meses.

   El asistente del panel muestra la misma guía.
3. **En el panel:** paso 1 (pegar el Id. y el secreto), paso 2 (Conectar) y paso 3 (Realizar respaldo ahora).

**Copia offline de la clave de los respaldos:** el archivo `~/CLAVE-RESPALDOS-ORDENES-PRO.txt` (permisos 600) contiene `BACKUP_ENCRYPTION_KEY`. Guárdala en un gestor de contraseñas y borra el archivo: sin ella no se puede recuperar ningún respaldo de OneDrive.

## Recuperar

- **Desde el panel:** «Restaurar respaldo», una restauración de prueba aislada.
- **Datos de un respaldo:** se descarga de OneDrive y se ejecuta:

  ```bash
  BACKUP_ENCRYPTION_KEY=… python maintenance/backup-cloud.py --descifrar archivo.sqlite.gz.enc --salida restaurada.sqlite3
  ```

  Nunca sobrescribe.
- **Volver a poner producción desde un respaldo:** solo por decisión administrativa expresa.
  1. Crea una base **nueva** en Turso desde el archivo restaurado.
  2. Verifícala.
  3. Cambia `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN` en Vercel.

  La base anterior se conserva.

## Pruebas

- **`local/tests/test_onedrive_backup.py`:** 18 escenarios con Microsoft y OneDrive **simulados**, sin cuentas reales ni internet:
  - el asistente: validación, secreto cifrado y nunca devuelto, y prioridad de las variables del servidor;
  - cambio de aplicación, que obliga a volver a conectar;
  - cuenta personal (`consumers`) con PKCE;
  - errores de Microsoft explicados;
  - permisos y CSRF;
  - respaldo bloqueado con motivo hasta que todo está listo;
  - respaldo del servidor cifrado, subido, descargado y restaurado;
  - tarea programada con `CRON_SECRET` que nunca anota un respaldo en la nube sin OneDrive;
  - falta de la clave de cifrado;
  - verificación y restauración aislada, con detección de un archivo alterado;
  - retención 30/12/12;
  - bloqueo contra ejecuciones simultáneas;
  - acceso revocado;
  - historial unificado con el registro real de la oficina y la copia anterior conservada;
  - alerta de atraso;
  - desconexión;
  - recuperación con `--descifrar`.
- **Prueba de navegador:** 15 comprobaciones del recorrido completo, desde «Sin configurar» hasta el respaldo verificado, con Microsoft simulado, en 1440, 1024, 768, 390 y 320 px, sin errores de consola.
