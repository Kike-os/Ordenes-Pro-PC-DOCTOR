# Instalación Python en cPanel

Paquete para Python 3.11 y Passenger. No contiene cuentas, datos locales ni secretos. Todavía requiere una prueba en el hosting.

1. En Setup Python App, usar raíz `ordenes-pro`, URL `ordenes-pro.ecuadorpcdoctor.com` sin ruta, archivo `wsgi_app.py` y entrada `application`. No usar `passenger_wsgi.py` como archivo de inicio: el panel genera ese archivo como cargador y sobrescribiría la aplicación.
2. En Administrador de archivos abrir la raíz de aplicación indicada por cPanel, normalmente `/home/TU_USUARIO/ordenes-pro`. Debe estar fuera de `public_html`. Si la raíz elegida está dentro de `public_html`, cambiarla antes de subir archivos. La URL pública se configura por separado.
3. Si existe un `passenger_wsgi.py` de ejemplo, descargarlo como respaldo. Subir el ZIP y extraerlo en la raíz de aplicación. `app.py` y `wsgi_app.py` deben quedar directamente dentro de ella. No borrar archivos de configuración generados por cPanel. Eliminar el ZIP del hosting después de extraerlo.
4. Configurar variables en Setup Python App: `APP_URL=https://ordenes-pro.ecuadorpcdoctor.com` y `SESSION_SECURE=true`. No copiar el `.env` local. El paquete incluye bibliotecas portables de QR/PDF y sus licencias; no necesita instalar dependencias con pip. Configurar PUBLIC_APP_URL con la misma URL HTTPS para los QR. Ver [recepción y encabezado](RECEPCION.md) para clima y habilitación explícita de producción.
5. Abrir Terminal de cPanel y pegar el comando de activación del entorno virtual que muestra Setup Python App. En esa misma terminal, situarse en la raíz de aplicación y ejecutar `python app.py migrate`, después `python app.py create-admin`. El segundo comando solicita nombre, usuario, correo y contraseña sin mostrarla. Si no hay Terminal, solicitar al proveedor que habilite acceso a una terminal para estos comandos; no crear una ruta web pública para configurar administradores.
6. Activar/comprobar el certificado del subdominio en SSL/TLS Status (AutoSSL). Configurar la redirección HTTPS únicamente para ese subdominio. Reiniciar la aplicación desde Setup Python App.
7. Abrir `https://ordenes-pro.ecuadorpcdoctor.com`, iniciar sesión y crear una orden ficticia. Comprobar consulta, cambios de estado y cierre de sesión. No usar datos reales hasta terminar estas pruebas.

Para recuperar contraseñas configurar SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD y SMTP_FROM como variables privadas. Sin SMTP, la recuperación no envía correos.

La base SQLite se crea en `var/ordenes.sqlite3`. Conservar y respaldar `var` en futuras actualizaciones; no sobrescribirlo ni subir la base de evaluación local. No requiere MySQL. Confirmar con el proveedor que el almacenamiento permite bloqueos SQLite antes de uso concurrente.

Ante error 500/503 consultar el registro de Passenger en cPanel y compartir solo el mensaje, sin credenciales. Para revertir la primera instalación, detener la aplicación y restaurar el archivo de inicio respaldado; conservar `var`.

Referencia: https://docs.cpanel.net/knowledge-base/web-services/how-to-install-a-python-wsgi-application/

## Actualización del formulario y diagnóstico de catálogos

Actualizar **todo** el paquete, conservando `var/` y las variables privadas. No subir únicamente `static/app.js` o `dashboard.html`: un frontend nuevo con un backend anterior produce HTTP 404 en `/api/reception-options` y `/api/geo/*`.

Con la aplicación detenida desde cPanel, respaldar `var/`, extraer el paquete actualizado en la raíz Python y ejecutar `python app.py migrate` en el entorno virtual. Reiniciar Passenger desde Setup Python App. El paquete incluye `reception.py`, `geography.py`, `weather.py`, `receipt_pdf.py`, `data/inec-2026.json`, las cuatro migraciones y las bibliotecas de `vendor/`. Las rutas de datos se resuelven desde el archivo Python, no desde el directorio de trabajo.

Tras iniciar sesión, en Red/Network del navegador comprobar respuestas JSON HTTP 200 para:

- `/api/reception-options`: ocho tipos y catálogo de marcas.
- `/api/geo/provinces`: 24 provincias.
- `/api/geo/cantons?province=01`: 15 cantones de Azuay.
- `/api/geo/parishes?province=01&canton=0101`: parroquias de Cuenca.
- `/api/geo/localities?canton=0101&parish=010101`: sugerencias de localidad; una lista vacía es válida y permite escritura manual.

HTTP 401 indica una sesión ausente/caducada; HTTP 404 con «Recurso no disponible» indica rutas ausentes en la versión que está ejecutándose o una configuración incorrecta de Passenger. HTTP 500 requiere revisar el traceback del registro de Passenger: ahora se registra la excepción con método y ruta, sin volcar datos del formulario. Una tabla inexistente se corrige ejecutando las migraciones con la aplicación detenida, no ocultando el error. Mantener la aplicación en la raíz de su subdominio; el cliente utiliza rutas absolutas del mismo origen y no necesita CORS.

Verificar permisos de lectura de código, JSON y `vendor/`, y de escritura de `var/` para el usuario que ejecuta Python. Nunca habilitar permisos universales 777 ni exponer `var/` o `.env` bajo `public_html`.

## Agenda de citas, Adi y recordatorios

La actualización incorpora las migraciones 009 y 010. Antes de ejecutar `python app.py migrate`, respaldar `var/ordenes.sqlite3`; `app.py` también crea un respaldo previo a cada migración. Conservar siempre la carpeta `var/` y no reemplazar la base con la local.

La reserva pública se publica en `/citas`; no crea una orden hasta que personal autorizado convierta la cita al recibir el equipo. La agenda interna diaria/semanal/mensual requiere sesión de técnico o administrador. Administración puede ajustar horarios de apertura, disponibilidad semanal por técnico, duración de servicios y feriados. Las reservas se validan de nuevo dentro de una transacción SQLite para evitar ocupar simultáneamente la agenda del mismo técnico.

Para confirmaciones y recordatorios por correo, configurar SMTP con STARTTLS y consentimientos registrados. En Cron Jobs de cPanel programar cada 15 minutos, por ejemplo:

```cron
*/15 * * * * /home/TU_USUARIO/virtualenv/ordenes-pro/3.11/bin/python /home/TU_USUARIO/ordenes-pro/local/appointments_cron.py >> /home/TU_USUARIO/logs/appointments-cron.log 2>&1
```

Ajustar ambas rutas a las que muestre Setup Python App. El proceso respeta `America/Guayaquil`, registra resultado por cita/canal/generación y no marca como enviado si SMTP falla. El WhatsApp se prepara como enlace manual; no hay integración oficial conectada ni se envían mensajes automáticamente. Sin `SMTP_HOST` no hay entrega por correo.

Adi aparece en `/citas` y en el sistema con chat de texto y transferencia a operadores mediante consultas periódicas compatibles con Passenger/cPanel. La consulta del cliente exige número de orden e identificación asociada y solo devuelve estado/equipo básico. El panel administrativo está protegido por rol y solo responde preguntas operativas que tienen consultas reales definidas; no ejecuta modificaciones. `OPENAI_API_KEY` y opcionalmente `OPENAI_MODEL` se configuran únicamente como variables privadas del servidor. Sin clave, usa respuestas seguras de respaldo. Ninguna clave va al navegador. La voz en tiempo real queda para una etapa posterior.

La pantalla de acceso bloquea luego de cinco intentos fallidos con ventana mínima de 15 minutos; `LOGIN_LOCKOUT_SECONDS` admite entre 900 y 86400. Los identificadores de bloqueo se guardan como hashes y los intentos bloqueados no renuevan el vencimiento. Las sesiones existentes pueden revocarse desde Configuración. Antes de uso real, validar SMTP, cron, límites SQLite y la instalación HTTPS en el hosting.
