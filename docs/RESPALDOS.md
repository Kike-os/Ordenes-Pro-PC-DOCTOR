# Base de datos central y respaldos

## Dónde están los datos

- **Producción** (`ordenes-pro.ecuadorpcdoctor.com`, Vercel): base **libSQL/Turso** en la nube (`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` como variables de Vercel, fuera de Git). Es persistente e independiente del código: los despliegues no la tocan. Todas las computadoras que entran a producción leen y escriben la misma base.
- **Servicio local** (`127.0.0.1:8010`): archivo SQLite `local/var/ordenes.sqlite3` de ese equipo. **No es la base central**: lo que se registre ahí no llega a la nube. La aplicación lo avisa a administración y el formulario de clientes indica «Guardado en la base local de este equipo» en lugar de «Guardado en la nube».

Las migraciones solo añaden estructura (`local/migrations/`), se aplican con respaldo previo y nunca recrean tablas con datos.

## Respaldo diario de la base central

`maintenance/backup-cloud.py` copia esquema y datos a un archivo SQLite nuevo en `~/Respaldos-OrdenesPro/` (fuera del proyecto, permisos 600), comprueba integridad, compara el número de filas de cada tabla con el origen, calcula el SHA-256, conserva las últimas 30 copias y anota el resultado en `respaldos.log` y en la propia base (`system_state.cloud_backup`). Si pasan más de 48 horas sin un respaldo correcto, la aplicación muestra un aviso a administración.

```bash
vercel env run -e production -- python maintenance/backup-cloud.py        # respaldo manual
python maintenance/backup-cloud.py --verify ~/Respaldos-OrdenesPro/<archivo>   # restauración de prueba aislada
systemctl --user list-timers ordenes-pro-respaldo.timer                   # programación diaria (02:30)
```

La programación usa `maintenance/ordenes-pro-respaldo.service` y `.timer` (systemd de usuario).

## Restauración

1. Verificar la copia con `--verify` (integridad, claves foráneas y recuentos).
2. Para consultarla sin tocar producción: copiarla a `local/var/ordenes.sqlite3` en un equipo de pruebas y arrancar el servicio local sin variables `TURSO_*`.
3. Restaurar sobre la base central es una operación manual y excepcional: debe decidirla administración y hacerse con un respaldo nuevo previo.

## Pendiente

- Las copias quedan en este equipo: falta una segunda ubicación externa (otro disco o almacenamiento en la nube) y cifrado con una clave que administre PC-DOCTOR.
- El servicio local sigue usando su propia base. Para trabajar siempre sobre la central hay que usar producción o configurar `TURSO_*` en el servicio local (decisión administrativa).
