# Respaldos automáticos en Microsoft OneDrive (1.5.309)

## Por qué saltó «Respaldo de la base central atrasado»

El respaldo lo generaba solo el equipo de la oficina (MI-DATA-CENTER), con el temporizador `ordenes-pro-respaldo.timer` a las 02:30. Su registro muestra lo siguiente:

- Respaldos correctos el 17, el 18 y el 19 de noviembre de 2026.
- Ninguna ejecución el 20 ni el 21, porque **el equipo estuvo apagado**. El siguiente arranque fue el 21 a las 16:37.
- Al encender, el temporizador recuperó la ejecución perdida (`Persistent=true`) y a las 16:44 terminó un respaldo correcto: 39,7 MB, 202 clientes y 23 órdenes.

No había credenciales vencidas ni errores de almacenamiento o de conexión. La causa era que **el respaldo dependía de que un único equipo estuviera encendido**.

**Corrección definitiva:** el respaldo principal lo genera ahora GitHub Actions en la nube, a las 02:00 de Ecuador, aunque la oficina esté apagada. El equipo de la oficina sigue haciendo su propia copia independiente cuando está encendido.

## Cómo funciona

| Pieza | Dónde corre | Qué hace |
|---|---|---|
| Generador (`maintenance/backup-cloud.py --modo …`) | GitHub Actions (`.github/workflows/respaldo.yml`), 07:00 UTC = 02:00 Ecuador | Copia la base central, la verifica, la cifra, la sube, la descarga de nuevo y la restaura en una base aislada |
| Vinculación y panel | La aplicación (Vercel) | OAuth 2.0 con Microsoft, token guardado cifrado, panel Configuración → Respaldos y botones que piden trabajo al generador |
| Copia independiente | Equipo de la oficina (`ordenes-pro-respaldo.timer`, 02:30) | Copia SQLite local verificada, conserva 30; recupera la ejecución al encender |

### Procedimiento de cada respaldo

1. **Bloqueo.** Solo puede haber un respaldo a la vez. Se garantiza con un bloqueo en la base, que caduca solo a los 45 minutos si el proceso muere, y con el grupo de concurrencia de GitHub.
2. **Copia consistente.** Copiar el archivo de la base no basta. El esquema y todas las filas se leen dentro de **una sola transacción de lectura**, una instantánea, y se escriben en una base SQLite nueva. Si esa transacción no se sostiene, se copia sin ella, se vuelven a contar las filas al terminar y, si alguna tabla cambió durante la copia, se repite. Hay hasta 3 intentos.
3. **Comprobación local:** `integrity_check`, `foreign_key_check` y el número de filas de cada tabla, igual que en la base central.
4. **Compresión y cifrado.** Se comprime con gzip y se cifra con **AES-256-GCM** y la clave `BACKUP_ENCRYPTION_KEY`. El cifrado autenticado detecta cualquier alteración del archivo.
5. **Nombre automático:** `ordenes-pro-AAAAMMDD-HHMMSS-<diario|semanal|mensual>.sqlite.gz.enc`.
6. **Subida por partes** con Microsoft Graph a `PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos`. Las carpetas se crean si faltan, y nunca se reemplaza un archivo existente (`conflictBehavior: fail`). Microsoft confirma el tamaño final.
7. **Verificación real.** El archivo **se descarga de nuevo** desde OneDrive, se compara su **SHA-256** con el calculado antes de subirlo, se descifra y se **restaura en una base aislada**. Esa base debe pasar la integridad, las claves foráneas y los mismos recuentos que la central. Solo entonces el respaldo cuenta como válido y se actualiza el estado de salud. Que el archivo exista no basta.
8. **Retención** (abuelo-padre-hijo, sobre las fechas): se conservan 30 diarios, 12 semanales y 12 mensuales. Lo que sobra va a la **papelera de OneDrive**, no se borra definitivamente. Solo se tocan archivos de Órdenes Pro de esa carpeta; el resto de archivos, incluso de la misma carpeta, nunca se toca.
9. **Registro.** Cada ejecución queda en el historial (`system_state.backup_runs`, sin migración de esquema) con:
   - fecha, operación y destino;
   - archivo, tamaño cifrado y sin cifrar, y SHA-256;
   - estado, resultado de la verificación y error, si lo hubo.

**Reintentos:** las llamadas a Microsoft, GitHub y la base se repiten hasta 3 o 4 veces ante fallos de red, 429 y 5xx, respetando `Retry-After`.

### Alertas (centro de notificaciones, solo administración)

| Alerta | Cuándo aparece | Cuándo desaparece |
|---|---|---|
| Respaldo de la base central atrasado | No hay un respaldo **correcto y verificado**, de OneDrive o de la oficina, en las últimas 30 h (un día más margen por los retrasos de GitHub) | En cuanto se verifica un respaldo nuevo |
| Falló el último respaldo en OneDrive | El último respaldo de OneDrive terminó en error | Con el siguiente respaldo correcto |
| Conexión con OneDrive vencida | Microsoft rechaza el acceso guardado (contraseña cambiada, acceso revocado, más de 90 días sin uso) | Al volver a vincular la cuenta |
| Respaldos sin copia en OneDrive | La aplicación de Microsoft está configurada, pero no hay ninguna cuenta vinculada | Al vincular la cuenta |

Las alertas de errores reales nunca se ocultan.

### Seguridad

- **OAuth 2.0 con PKCE** y un `state` aleatorio de un solo uso, válido 10 minutos y ligado al administrador que inició la vinculación. La vuelta desde Microsoft no depende de la cookie de sesión, que es `SameSite=Strict`; la página de retorno vuelve a Configuración desde el propio sitio.
- **Permisos delegados:** `offline_access`, `User.Read` y `Files.ReadWrite`, solo sobre el OneDrive de la cuenta que se vincula. Microsoft 365 empresa no admite un permiso menor (`Files.ReadWrite.AppFolder` es solo para cuentas personales). El código solo usa la carpeta de respaldos.
- **Token de actualización:** se guarda **cifrado** en la base (`od1:`, HMAC-SHA256 en modo contador más etiqueta HMAC, el mismo esquema que los demás secretos del sistema) con `ONEDRIVE_TOKEN_KEY`. Si Microsoft lo rota, se guarda el nuevo. El navegador nunca lo recibe y no aparece en registros ni respuestas.
- **Separación de claves:**
  - la clave que cifra los respaldos (`BACKUP_ENCRYPTION_KEY`) está **solo en GitHub** y en tu copia offline, nunca en Vercel;
  - Vercel solo puede pedir respaldos, nunca descifrarlos.
- **Permisos y registro:** solo administración ve el panel y ejecuta acciones, con CSRF y auditoría (`onedrive_link_started`, `onedrive_linked`, `onedrive_unlinked`, `backup_requested_*`).

## Configuración inicial (la hace administración, una sola vez)

> No pegues ninguno de estos valores en el chat. Se cargan directamente en el portal de Microsoft, en Vercel y en GitHub.

### 1. Registrar la aplicación en Microsoft Entra ID (unos 10 minutos)

1. Entra en <https://entra.microsoft.com> con la cuenta de administrador de Microsoft 365.
2. Ve a **Identidad → Aplicaciones → Registros de aplicaciones → Nuevo registro**.
3. Rellena el registro:
   - **Nombre:** `Órdenes Pro Respaldos`.
   - **Tipos de cuenta admitidos:** *Solo las cuentas de este directorio organizativo (inquilino único)*.
   - **URI de redirección:** tipo *Web*, con el valor `https://ordenes-pro.vercel.app/api/backups/onedrive/callback`.
4. En **Información general**, copia el **Id. de aplicación (cliente)** y el **Id. de directorio (inquilino)**.
5. En **Certificados y secretos → Nuevo secreto de cliente**, elige 24 meses y copia el **Valor**. Solo se muestra una vez.
6. En **Permisos de API → Agregar un permiso → Microsoft Graph → Permisos delegados**, marca `offline_access`, `User.Read` y `Files.ReadWrite`. Si tu directorio lo exige, pulsa además *Conceder consentimiento de administrador*.

### 2. Generar las dos claves (en tu equipo)

Ejecuta este comando dos veces; cada salida es una clave distinta:

```bash
python -c "import base64,secrets;print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

- La primera es `ONEDRIVE_TOKEN_KEY`.
- La segunda es `BACKUP_ENCRYPTION_KEY`. **Guarda una copia offline**, por ejemplo en tu gestor de contraseñas o impresa en la caja fuerte. Sin ella no se puede recuperar ningún respaldo.

### 3. Token de GitHub para «Realizar respaldo ahora»

En GitHub ve a **Settings → Developer settings → Fine-grained tokens → Generate new token** y configúralo así:

- **Repository access:** solo `Ordenes-Pro-PC-DOCTOR`.
- **Permissions → Actions:** *Read and write*.
- **Caducidad:** un año.

Copia el token.

### 4. Token de Turso para el generador

Desde Vercel, en **Storage / Marketplace → Turso → abrir el panel de Turso**, entra en la base `ordenes-pro-db` y crea un **token de base de datos** nuevo y propio para los respaldos, de modo que pueda revocarse sin afectar a la aplicación. Copia también la URL de la base (`libsql://…`).

### 5. Cargar los valores

| Dónde | Variable o secreto | Valor |
|---|---|---|
| Vercel → Settings → Environment Variables (solo **Production**) | `MS_CLIENT_ID` | Id. de aplicación (paso 1.4) |
| | `MS_CLIENT_SECRET` | Valor del secreto de cliente (paso 1.5) |
| | `MS_TENANT_ID` | Id. de directorio (paso 1.4) |
| | `ONEDRIVE_TOKEN_KEY` | primera clave (paso 2) |
| | `GITHUB_BACKUP_TOKEN` | token de GitHub (paso 3) |
| GitHub → repositorio → Settings → Secrets and variables → Actions | `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | paso 4 |
| | `BACKUP_ENCRYPTION_KEY` | segunda clave (paso 2) |
| | `ONEDRIVE_TOKEN_KEY` | **la misma** primera clave |
| | `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT_ID` | los del paso 1 |

Después hay que redesplegar la aplicación para que Vercel cargue las variables.

### 6. Vincular y probar

1. Entra en **Configuración → Respaldos → Vincular OneDrive** e inicia sesión con la cuenta de Microsoft 365 donde quieres guardar los respaldos.
2. Pulsa **Realizar respaldo ahora**. En unos minutos el historial mostrará «Correcto · Verificado» y el archivo aparecerá en OneDrive.

## Restaurar

- **Desde el panel, «Restaurar respaldo»:** pide escribir `RESTAURAR` y restaura el respaldo elegido en una **base aislada**, para comprobar integridad, claves y recuentos. **La base de producción no se modifica.** El resultado queda en el historial.
- **Recuperar los datos de un respaldo:**
  1. Descarga el archivo de OneDrive.
  2. Ejecuta, con la clave en el entorno:

     ```bash
     BACKUP_ENCRYPTION_KEY=… python maintenance/backup-cloud.py --descifrar archivo.sqlite.gz.enc --salida restaurada.sqlite3
     ```

  El comando nunca sobrescribe un archivo existente e informa de la verificación.
- **Volver a poner en marcha producción desde un respaldo** solo se hace por decisión administrativa expresa y sin destruir la base actual:
  1. Crea una base **nueva** en Turso a partir del archivo restaurado (`turso db create <nombre> --from-file restaurada.sqlite3`).
  2. Verifícala.
  3. Cambia `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN` en Vercel.

  La base anterior se conserva intacta para auditoría. El panel no hace este cambio.

## Pruebas

- `local/tests/test_onedrive_backup.py`: 12 escenarios con Microsoft, OneDrive y GitHub **simulados** en 127.0.0.1, sin cuentas reales ni internet.
  - Vinculación con PKCE y `state` de un solo uso, caducado o falsificado.
  - Token cifrado y rotado.
  - Respaldo cifrado, subido, descargado y restaurado.
  - Verificación y restauración aislada pedidas desde el panel.
  - Detección de un archivo alterado.
  - Retención 30/12/12 sin tocar archivos ajenos.
  - Bloqueo contra ejecuciones simultáneas.
  - Acceso revocado, con conexión vencida y alertas separadas.
  - Alerta de atraso que solo se apaga con un respaldo verificado.
  - Permisos, CSRF y auditoría.
  - Copia local de la oficina.
  - Recuperación con `--descifrar`.

  Las pruebas de cifrado necesitan `cryptography`, que es una dependencia del generador.
- Prueba de navegador del panel en 1440, 1024, 768, 390 y 320 px:
  - indicadores, historial y acciones;
  - restauración con confirmación y Escape;
  - bloqueo mientras hay una operación en curso;
  - página de retorno con error;
  - sin desbordes ni errores de consola.
