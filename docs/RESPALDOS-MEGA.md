# Respaldos automáticos en MEGA Cloud (1.5.311)

Sustituye a la integración con Microsoft OneDrive (1.5.309 y 1.5.310), que se retiró por completo: panel, autenticación OAuth de Microsoft, rutas y tarea de Vercel.

- **Ningún otro módulo usaba esa autenticación.** La mención a «Microsoft» en Licencias es una línea de productos, sin relación con OneDrive.
- **En OneDrive nunca llegó a guardarse un respaldo**, así que no hay nada que recuperar allí.
- **El historial y la copia local de la oficina se conservan.**

## Por qué un agente y no el servidor

- **Vercel no puede ejecutar MEGAcmd.** No admite procesos persistentes, y MEGAcmd necesita su servidor (`mega-cmd-server`) y su sesión guardada en disco.
- **No se usa la API interna de MEGA ni bibliotecas no oficiales.** El SDK tiene una licencia de revisión restringida y `mega.py` está abandonada.
- **MEGA S4**, el almacenamiento compatible con S3, no está disponible en cuentas gratuitas.
- **La opción elegida es un agente en el equipo de la oficina (MI-DATA-CENTER)** con **MEGAcmd oficial** de MEGA Limited.
  - El paquete de MEGA para Arch exige `ffmpeg` 7 y el sistema tiene `ffmpeg` 9, de modo que no arranca. Por eso se usa el **paquete oficial para Ubuntu 24.04 dentro de un contenedor de Podman** sin privilegios.
  - La clave del repositorio se comprueba por su huella: `B01C 8118 8048 0C85 4C73 EC7E 1A66 4B78 7094 A482`, MegaLimited, válida hasta 2032.

## Cómo funciona

| Pieza | Dónde | Qué hace |
|---|---|---|
| Respaldo diario | Temporizador `ordenes-pro-respaldo.timer`, a las **02:00 America/Guayaquil** | Copia consistente, copia local, cifrado, cola de pendientes, subida y verificación. Si el equipo estaba apagado, lo hace al encenderlo (`Persistent=true`) |
| Agente | Servicio `ordenes-pro-mega-agente.service` | Cada 30 s envía su estado y atiende las órdenes del panel; cada hora reintenta los pendientes y retira las descargas caducadas; cada semana hace una restauración de prueba |
| MEGAcmd | Contenedor `ordenes-mega` (quadlet de Podman, siempre encendido) | Sesión de MEGA en `~/.local/share/ordenes-pro/mega-sesion` (700). **La contraseña nunca pasa por Órdenes Pro** |
| Panel | Configuración → Respaldos (Vercel) | Muestra el estado real que informa el agente y le deja órdenes. Nunca toca la cuenta MEGA |

Todo funciona aunque nadie haya iniciado sesión en el equipo, porque *linger* está activo.

### Procedimiento de cada respaldo

1. **Copia consistente.** El esquema y todas las filas se leen en **una sola transacción de lectura**. Se comprueba con `integrity_check`, `foreign_key_check` y el recuento de cada tabla.
2. **Copia local independiente** en `~/Respaldos-OrdenesPro`. Se conservan las últimas 30.
3. **Cifrado:** gzip y **AES-256-GCM** con la clave de `~/.config/ordenes-pro/backup.key` (600). El archivo cifrado entra en la **cola de pendientes**, en `~/Respaldos-OrdenesPro/mega-intercambio/pendientes`, una ubicación persistente.
4. **Subida a MEGA** (`mega-put`) en `PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos`. La carpeta se crea si falta y antes se comprueba que haya espacio.
5. **Verificación real:** el archivo se **descarga de nuevo** (`mega-get`), se compara su **SHA-256**, se descifra y se **restaura en una base aislada** con los mismos recuentos. **Solo entonces** cuenta como respaldado en MEGA y sale de la cola.
6. **Conservación 30/12/12:** lo que sobra va a la **papelera de MEGA** (`mega-mv … //bin`), donde sigue siendo recuperable. Los archivos ajenos a Órdenes Pro nunca se tocan.

### Si MEGA o internet fallan

- El respaldo cifrado queda **pendiente en disco**, con el número de intentos y el motivo real. Se distingue «sin conexión» de «sin sesión».
- Se reintenta **cada hora y al encender el equipo**, y también con el botón «Reintentar subidas pendientes».
- **Nunca se declara respaldado en MEGA** algo que no se subió y verificó.
- Si el archivo subido no coincide (SHA-256), se manda a la papelera de MEGA, se registra como error y se vuelve a subir.
- **Si el servidor central deja de funcionar,** el respaldo en MEGA sirve para recuperar los datos, pero **no sustituye la operación sin conexión** del sistema.

### Panel (Configuración → Respaldos, solo administración)

- **Estados:**
  - agente (señal y equipo);
  - conexión MEGA (cuenta, o causa real: sin conexión o sin sesión);
  - almacenamiento usado, con barra;
  - último respaldo local correcto;
  - último respaldo MEGA verificado;
  - próximo respaldo programado;
  - pendientes de subir, con intentos y error.
- **Botones:**
  - «Realizar respaldo ahora»;
  - «Verificar conexión y espacio»;
  - «Crear carpeta de respaldos»;
  - «Reintentar subidas pendientes».

  En cada respaldo de MEGA, además: «Verificar», «Descargar» (un enlace de MEGA del archivo **cifrado**, válido 24 h, que el agente retira después) y «Restaurar en entorno aislado» (pide escribir `RESTAURAR`; **no toca producción**).
- **Órdenes al agente,** con su resultado real. Se atienden en menos de un minuto.
- **Historial unificado**, sin inventar registros. Incluye la copia de 37,8 MB del 21/11, que se conserva.

### Alertas (se retiran solas al corregirse la causa)

| Alerta | Cuándo aparece |
|---|---|
| Respaldo de la base central atrasado | Sin un respaldo **verificado** (MEGA o local) en 30 h |
| Falló el último respaldo en MEGA | Fallo de integridad del archivo subido |
| Respaldos pendientes de subir a MEGA | Un pendiente tiene más de 2 h |
| MEGA desconectado | Sin sesión o sin conexión, con el motivo real |
| Agente de respaldos sin señal | El equipo de la oficina no informa en 10 minutos |
| Espacio en MEGA casi lleno | 90 % ocupado |

## Instalación (equipo de la oficina, una sola vez)

1. **Tú, con contraseña de administrador:**

   ```bash
   sudo pacman -S --needed podman
   ```

2. **Instalador** (sin privilegios): construye la imagen, crea el entorno de Python, la clave y los servicios.

   ```bash
   bash maintenance/mega-agente/instalar.sh
   ```

3. **Tú, en tu terminal, una sola vez:**

   ```bash
   podman exec -it ordenes-mega mega-login tu-correo
   ```

   La contraseña y, si la tienes activada, la doble autenticación se escriben **solo ahí**.
4. **En el panel:** «Crear carpeta de respaldos» y «Realizar respaldo ahora».

**Clave de los respaldos:** `BACKUP_ENCRYPTION_KEY`. El agente la lee de `~/.config/ordenes-pro/backup.key`. Guarda una copia offline en tu gestor de contraseñas: sin ella no se puede recuperar ningún respaldo de MEGA.

## Recuperar un respaldo

1. Usa «Descargar» en el panel, o descárgalo directamente desde MEGA.
2. Ejecuta:

   ```bash
   python maintenance/backup-cloud.py --descifrar archivo.sqlite.gz.enc --salida restaurada.sqlite3
   ```

   El comando usa la clave del archivo `backup.key` o de `BACKUP_ENCRYPTION_KEY`, nunca sobrescribe y muestra la verificación.

Volver a poner producción desde un respaldo exige una decisión administrativa expresa:

1. Crear una base **nueva** en Turso desde el archivo restaurado.
2. Verificarla.
3. Cambiar `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN` en Vercel.

## Pruebas

- **`local/tests/test_backups_mega.py`:** 15 escenarios con **MEGAcmd simulado** (`local/tests/fake_megacmd.py`), sin cuentas reales:
  - respaldo completo con copia local, cifrado, subida, nueva descarga, SHA-256 y restauración aislada;
  - corte de red: el respaldo queda pendiente, se reintenta y la alerta se retira;
  - sesión de MEGA cerrada;
  - archivo dañado en la nube;
  - falta de espacio;
  - conservación 30/12/12 con papelera, sin tocar archivos ajenos;
  - bloqueo contra subidas simultáneas;
  - órdenes del panel, con permisos, CSRF, auditoría y sin duplicados;
  - el agente ejecutando las siete órdenes;
  - descarga que caduca a las 24 h;
  - ciclo del servicio;
  - alertas de agente sin señal y de espacio;
  - alerta de atraso, que solo se retira con un respaldo verificado;
  - historial con la copia anterior;
  - recuperación con `--descifrar`.
- **Prueba de navegador:** 14 comprobaciones con el agente simulado atendiendo órdenes reales:
  - estados separados;
  - corte de red, con el respaldo pendiente y la causa real;
  - reintento, verificación de conexión y espacio;
  - descarga y restauración aislada;
  - 1440, 1024, 768, 390 y 320 px, sin errores de consola.
