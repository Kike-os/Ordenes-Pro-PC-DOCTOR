# Despliegue en Vercel con base remota

Vercel no conserva archivos entre ejecuciones, por lo que `local/var/ordenes.sqlite3` no sirve allí. En Vercel la aplicación usa una base libSQL/Turso, compatible con SQLite: las consultas, las migraciones y los triggers de inmutabilidad son los mismos. Sin `TURSO_DATABASE_URL` todo sigue funcionando con el archivo SQLite local.

## Piezas

- `api/index.py`: entrada de Vercel; envuelve `application` de `local/wsgi_app.py` y toma la IP del cliente de las cabeceras que fija Vercel para los límites por IP. No migra ni crea cuentas.
- `vercel.json`: envía todas las rutas a esa función y le pasa la ruta original en `__path`, porque Vercel la sustituye por `/api/index`. `requirements.txt` (raíz) repite `local/requirements.txt`.
- `.vercelignore`: excluye `revision/`, `docs/`, `tmp/`, pruebas, `local/var/`, `.env`, respaldos y paquetes.
- `local/remote_db.py`: cliente HTTP (Hrana) con la interfaz de `sqlite3` que usa la aplicación. `app.connect()` lo elige cuando existe `TURSO_DATABASE_URL`.

## Variables en Vercel

| Variable | Valor |
| --- | --- |
| `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | Base remota. El token es secreto. |
| `APP_URL`, `PUBLIC_APP_URL` | Opcionales: por defecto el dominio de producción de Vercel. `APP_URL` debe ser el origen exacto del navegador. `PUBLIC_APP_URL` queda grabado en los QR, que son permanentes: fijar el dominio definitivo antes de registrar órdenes reales. |
| `SESSION_SECURE` | `true` por defecto en esta entrada. |
| `APP_ENV`, `PRODUCTION_ENABLED` | Solo tras la decisión administrativa de habilitar producción. |
| `SMTP_*`, `TURNSTILE_*`, `OPENAI_API_KEY` | Opcionales, igual que en `local/.env.example`. |

## Migrar y crear el administrador

Se hace desde un equipo de confianza, nunca desde la función. Con las dos variables `TURSO_*` en el entorno o en `local/.env`:

```bash
cd local
python app.py migrate
python app.py create-admin
```

Antes de cada migración pendiente sobre una base con datos, `migrate` descarga una copia completa a `local/var/backup-*.sqlite3`. La base remota empieza vacía: no se copian datos locales a un servicio externo sin autorización específica.

## Pruebas

La suite normal usa SQLite temporal. `local/tests/test_remote_db.py` prueba el adaptador contra un servidor libSQL local y se omite si falta `LIBSQL_TEST_URL`:

```bash
sqld --http-listen-addr 127.0.0.1:8099 --db-path /tmp/libsql-pruebas
LIBSQL_TEST_URL=http://127.0.0.1:8099 python -m unittest local/tests/test_remote_db.py
```

## Pendientes conocidos en Vercel

- Impresión térmica: requiere CUPS y la impresora de la red local; desde Vercel responde como no disponible.
- Correos de seguridad: salen en un hilo en segundo plano que Vercel puede congelar al terminar la respuesta; validar la entrega real antes de depender de la recuperación por correo.
- Recordatorios (`appointments_cron.py`, `maintenance_cron.py`): no se ejecutan solos en Vercel; deben programarse en un equipo con las variables `TURSO_*`.
