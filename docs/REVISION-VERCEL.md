# Revisión de Vercel — 10 de octubre de 2026

Estado: corrección local del adaptador WSGI; despliegue y causa remota pendientes de acceso al proyecto y sus registros. No se ha publicado ni modificado la base existente.

## Hallazgos comprobados en esta copia

- Backend propio con `http.server` y `sqlite3`, sin Flask, Django ni FastAPI. `local/app.py` inicia un servidor solo mediante su CLI; no expone una aplicación WSGI para Vercel.
- `local/passenger_wsgi.py` sí contiene el adaptador WSGI `application`, pero su variable `app` era el módulo importado. Se renombró ese import a `core` y se expuso `app = application`, conservando la entrada Passenger. Esto corrige la interfaz del adaptador; no demuestra que Vercel esté usando ese archivo.
- No existe `vercel.json` ni enlace `.vercel/project.json`. No se añadieron reglas sin conocer el directorio raíz y la entrada del despliegue real.
- `local/requirements.txt` declara `argon2-cffi>=23.1.0,<26`. El resto usa principalmente biblioteca estándar; PDF y QR dependen además de los módulos incluidos en `local/vendor`. La instalación en un entorno limpio de Vercel aún debe validarse. El archivo de dependencias está bajo `local/`, por lo que debe comprobarse el directorio raíz configurado.
- La conexión usa directamente `local/var/ordenes.sqlite3`, no `DATABASE_URL`. Cambiar una variable de conexión por sí solo no migra este backend a PostgreSQL.
- `local/var/` está excluido de Git. Un despliegue desde el repositorio no recibe esa base; el adaptador tampoco ejecuta migraciones. No se debe corregir esto publicando datos privados ni creando automáticamente una base vacía.
- La impresión física depende de CUPS, Ghostscript, utilidades locales y una impresora de red. Requiere un agente local o backend con acceso a la impresora si la interfaz se hospeda en Vercel.
- Hay correo de seguridad en hilos daemon y tareas cron separadas: su ejecución fiable debe validarse o adaptarse al alojamiento final.

## Acceso y entorno

No hay CLI ni conector de Vercel disponible, ni VERCEL_TOKEN, VERCEL_ORG_ID o VERCEL_PROJECT_ID en esta sesión. No hay `local/.env`. Las variables del entorno remoto no se pudieron inspeccionar. No se leyeron secretos.

La consulta inicial desde el entorno restringido no pudo acceder al dominio. En la revisión posterior, una consulta de red autorizada confirmó HTTP 500 y `x-vercel-error: FUNCTION_INVOCATION_FAILED` el 10 de octubre de 2026 a las 22:05:44 UTC. Identificador de invocación: `iad1::zqxqc-1791669944075-2ea8f93116cb`. La respuesta pública no incluye una traza para atribuir el fallo a una excepción concreta.

El remoto local apunta a `github.com/Kike-os/Ordenes-Pro.git`, rama local `main`, commit `0eccd0e`. No se ha confirmado que ese commit sea el desplegado. GitHub CLI está instalado pero no tiene sesión autenticada; Vercel tampoco tiene un conector disponible.

En Vercel deben verificarse APP_URL (origen HTTPS exacto), SESSION_SECURE=true, PUBLIC_APP_URL y las variables opcionales de SMTP y Turnstile, sin copiar sus valores secretos a registros. También deben verificarse el commit, rama, directorio raíz y archivo de entrada efectivos.

## Persistencia y conservación

Vercel no garantiza almacenamiento persistente para SQLite local. Copiar la base a `/tmp` no conserva órdenes ni sesiones entre instancias y despliegues.

Para mantener Vercel como backend habría que adaptar explícitamente el acceso SQL y las migraciones a una base externa persistente, por ejemplo PostgreSQL administrado. Hacerlo primero sobre una copia consistente de la base, verificar conteos, claves, cuentas, hashes, sesiones, auditoría, números de orden y comprobantes; conservar la base original y preparar reversión antes de cambiar tráfico. No se ha realizado esa migración ni elegido un proveedor sin conocer el entorno remoto.

La alternativa que requiere menos cambios al almacenamiento actual es alojar el backend WSGI con un volumen persistente y conservar SQLite. Vercel podría servir una interfaz, pero separar orígenes exige revisar cookies, CSRF y rutas; no basta una redirección improvisada.

## Validación y siguiente paso

La suite existente usa bases temporales y datos ficticios. Se cambió el punto invocado en sus pruebas WSGI para validar también la entrada `app` requerida por Vercel, incluyendo acceso, rutas privadas, estáticos, catálogos, creación de órdenes, PDF y QR. Pasaron 78 pruebas en 30,946 segundos, la comprobación de sintaxis JavaScript, la compilación del adaptador y `git diff --check`. No se verificaron los flujos en el despliegue remoto.

Para continuar: identificar repositorio/rama y obtener registros de ejecución de Vercel del fallo, junto con la configuración de entrada y almacenamiento. Después de resolver persistencia, ejecutar pruebas en un despliegue de vista previa aislado, verificar formularios, acceso y recursos en navegador, y solo entonces publicar producción. Las pruebas locales no sustituyen esa validación.

Referencias: [runtime Python y entrada WSGI](https://vercel.com/docs/functions/runtimes/python), [SQLite en Vercel](https://vercel.com/kb/guide/is-sqlite-supported-in-vercel).
