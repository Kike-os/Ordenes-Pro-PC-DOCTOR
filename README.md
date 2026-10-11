# PC-DOCTOR S.A. — ÓRDENES PRO

Versión local de evaluación. No se ha publicado en Tecnoweb ni se ha confirmado la compatibilidad de su hosting. La arquitectura de producción sigue pendiente. Si el hosting admite PHP/MySQL, se recomienda Laravel; este prototipo permite revisar el diseño y los flujos localmente y no requiere Node.js.

## Abrir en Omarchy

En una terminal:

```bash
bash /home/admin-red/Work/Ordenes-Pro-PC-DOCTOR/iniciar-local.sh
```

En la primera ejecución solicita tus datos y una contraseña de al menos 12 caracteres sin mostrarla. No hay credenciales predeterminadas ni registro público. En las siguientes ejecuciones conserva la cuenta y los registros existentes.

Abre **http://127.0.0.1:8010** en el navegador del mismo equipo. Conserva la terminal abierta. Detén el servidor con Ctrl+C. Por defecto escucha únicamente en 127.0.0.1 y no es un servidor de producción.

## Acceso desde otra PC de la red local

Detén el servidor anterior con Ctrl+C y ejecuta en Omarchy:

```bash
bash /home/admin-red/Work/Ordenes-Pro-PC-DOCTOR/iniciar-red-local.sh
```

El script detecta direcciones privadas activas de Omarchy y selecciona la única disponible o solicita elegir entre las interfaces reales. Escucha solo en esa IP y configura el origen permitido para las solicitudes y recuperación. En ambos equipos abre exactamente la URL que muestre; no copies una IP de ejemplo. Los equipos deben compartir una red que permita comunicación entre ellos. Usa únicamente datos ficticios: esta evaluación LAN utiliza HTTP. No exponer el puerto al internet ni al router. No se modifican reglas de firewall.

Si no conecta, comprobar primero que el servidor indique que está escuchando, que la IP elegida pertenezca a Omarchy, que no exista aislamiento Wi-Fi entre clientes y que el firewall permita la conexión desde esa red. La configuración HTTPS de producción sigue pendiente.

## Implementado localmente

- Acceso por usuario o correo, mostrar contraseña y errores genéricos.
- Contraseñas con scrypt (N=32768, r=8, p=3) y sal aleatoria. No se guardan contraseñas reversibles.
- Sesiones aleatorias almacenadas como hash, cookies HttpOnly y SameSite=Strict. Secure configurable para HTTPS; desactivado únicamente para HTTP en loopback. Recordarme extiende el token 30 días sin guardar la contraseña. Sin Recordarme, sesión del navegador con límite de ocho horas.
- Limitación persistente de intentos por IP e identificador. Consultas parametrizadas, protección de origen/JSON en acceso y recuperación, y token CSRF en acciones autenticadas.
- Roles administrador/técnico y rutas privadas; administración y técnicos reciben equipos; las demás escrituras conservan permisos administrativos.
- Clientes, equipos, órdenes, estados, auditoría y migraciones versionadas con respaldo. No hay información real de clientes en pruebas.
- Dashboard con conteos reales, últimos diez registros y estado vacío.
- Recuperación con SMTP STARTTLS, tokens de 20 minutos de un uso; cambio de contraseña revoca todas las sesiones. Protección por cinco intentos fallidos/ventana configurable y revocación de sesiones desde Configuración.
- Auditoría sin contraseñas, tokens ni contenido de órdenes; eventos protegidos contra actualización/eliminación desde la aplicación.

## Interfaz y módulos

Inicio como centro de operaciones, con navegación superior, búsqueda, contadores reales por estado, órdenes que requieren atención, actividad, citas de hoy, mantenimientos y entregas. Conserva el fondo de circuitos; el panel es adaptable y respeta `prefers-reduced-motion`.

- Comprobantes: apertura automática únicamente tras guardado confirmado; la recarga no muestra confirmaciones anteriores.
- Condiciones versionadas, aceptación y documentos A4/térmicos: ver [configuración documental](docs/CONDICIONES.md).
- Nueva orden: asistente de recepción en cuatro pasos para administración y técnicos, con catálogo INEC 2026, marcas, numeración diaria, QR, impresión y PDF. Ver [recepción y encabezado](docs/RECEPCION.md).
- Órdenes: listado completo con búsqueda, paginación de 50 registros, filtro de activas y cambios de estado por administración.
- Clientes: búsqueda, registro y edición por administración.
- Equipos: consulta, registro y edición con selección de cliente por administración.
- Reportes: conteos reales por estado, clientes y equipos; descarga del resumen en CSV.
- Configuración: perfil del administrador, cuentas y estado del correo. No expone secretos ni modifica roles desde la interfaz.

Los técnicos pueden recibir equipos y consultar órdenes/comprobantes; la edición de registros, estados y configuración requiere administración. Todos los POST nuevos conservan validación de sesión, origen y CSRF, consultas parametrizadas y auditoría. No se cambió el esquema ni se eliminaron datos.

## Logotipo original

Se incorporó el archivo `/home/admin-red/Descargas/PC.png` como `local/static/logo-original.png`, copiado sin alterar sus bytes. Se conserva su proporción con `object-fit: contain`. Se utiliza en el inicio, la navegación y las páginas de acceso y recuperación.

## Correo y entorno

Copia `local/.env.example` a `local/.env` y configura SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD y SMTP_FROM con un servicio autorizado. APP_URL debe coincidir exactamente con la dirección usada en el navegador. No publicar el archivo .env. Protege sus permisos con `chmod 600 .env`.

Sin SMTP configurado no se enviarán enlaces; la respuesta pública sigue siendo genérica para no revelar cuentas. Los fallos se registran como eventos sin secretos. No se envían correos durante las pruebas.

## Pruebas

```bash
cd /home/admin-red/Work/Ordenes-Pro-PC-DOCTOR/local
python -m unittest discover -s tests -v
node --check static/app.js
```

Las pruebas usan bases temporales y datos ficticios, y prueban los manejadores HTTP sin necesitar sockets. Una ejecución satisfactoria no sustituye la revisión visual en el navegador ni la prueba de SMTP real.

## Despliegue en Vercel

Para publicar cambios: `bash publicar.sh "descripción del cambio"`. Ejecuta las pruebas, crea el commit y lo sube a GitHub; Vercel despliega automáticamente cada subida a `main`.

Vercel no conserva el archivo SQLite; allí la aplicación usa una base libSQL/Turso mediante `local/remote_db.py`. Seguir [despliegue en Vercel](docs/VERCEL.md).

## Adaptación para cPanel Python

Se preparó `local/wsgi_app.py` para Python 3.11/Passenger y un paquete sin datos ni secretos. Seguir [instalación cPanel](docs/CPANEL.md). Requiere migración y creación del administrador desde la terminal del hosting, configuración HTTPS y prueba remota; todavía no se ha publicado.

- Agenda pública `/citas`, disponibilidad por técnico, estados independientes, reprogramación/cancelación con token privado, conversión explícita a orden y recordatorios de correo por cron cuando hay consentimiento y SMTP. Reservar una cita no crea una orden.
- Chat de texto Adi para clientes y panel de atención humana por consultas periódicas. La API de OpenAI es opcional y solo se usa desde el servidor; el panel administrativo responde consultas con datos SQL reales definidos. No hay envío integrado de WhatsApp ni voz activada.

## Límites del servidor local y planificación anterior

No ejecutar `app.py serve` en cPanel; usar la entrada WSGI y el procedimiento anterior. Ver [inspección](docs/INSPECCION-INICIAL.md) y [publicación pendiente](docs/PUBLICACION.md). Falta verificar SSH, huella del proveedor, PHP/extensiones, MySQL/MariaDB, document root, cron, SMTP y TLS. También falta recibir el logotipo. No se han creado certificados ni automatizaciones remotas. No hay despliegue automático habilitado.

El formulario de órdenes selecciona una ficha de cliente existente y conserva una copia histórica de recepción. La agenda de citas y Adi son funciones locales listas para validación en hosting; correo y llamadas a OpenAI requieren credenciales externas. No exponer el servidor Python de desarrollo a internet.

## Inicio automático en este equipo

El servicio de usuario `ordenes-pro.service` está habilitado de forma permanente y sirve en http://127.0.0.1:8010. Arranca al encender el equipo (con `Linger=yes`) y reinicia el proceso tras 5 segundos si termina. No necesita mantener una terminal abierta. La unidad de referencia está en `maintenance/ordenes-pro.service` y la instalada en `~/.config/systemd/user/ordenes-pro.service`.

Consultar estado: `systemctl --user status ordenes-pro.service`.
Consultar registros: `journalctl --user -u ordenes-pro.service -n 50`.
Detener intencionalmente: `systemctl --user stop ordenes-pro.service`.
Con el servicio activo, no ejecutar los scripts de inicio manual en el mismo puerto.

## Revisión de acceso (10 de octubre de 2026)

Acceso y recuperación unificados, políticas administrativas, notificación de cambios y verificación antibots adaptativa configurable. Ver [controles, pruebas y pendientes de producción](docs/ACCESO-SEGURO.md). Capturas de escritorio y móvil en `revision/auth-20261010/`. La revisión pasó 64 pruebas; SMTP real, claves Turnstile y HTTPS del hosting requieren validación externa.

Ticket térmico, autorizaciones técnicas e impresión Epson de red: [guía y verificación](docs/TICKET-TERMICO.md).
# Ordenes-Pro-PC-DOCTOR
