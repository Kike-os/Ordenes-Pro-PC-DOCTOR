# Database Guardian Pro 1.0 · Self-Healing & Migration Control (1.5.331)

**Dónde está:** Sistema → tarjeta **Database Guardian Pro**. Solo la usa administración.

**Archivos:**

- `local/db_guardian.py`.
- Mejoras en `db_migrations.py`, `stability.py`, `remote_db.py`, `notifications.py` y `versioning.py`.
- Migración `122_migration_ledger.sql`: solo crea una tabla.
- `local/migrations/MANIFEST.json`.

## Causa raíz de la incidencia del 24/11/2026 02:04

| Hora (Ecuador) | Evento |
|---|---|
| 02:04 | Vercel despliega la 1.5.327, que incluye los archivos `119_payment_commitments.sql` y `120_financial_rates.sql` |
| 02:04–02:06 | El monitor de estabilidad se ejecuta, compara archivos con registros (`Faltan migraciones`) y lo marca como **fallo crítico** |
| ~02:06 | Administración aplica 119 y 120 desde Sistema → Migraciones (respaldo verificado de las 02:00): 231 → 234 tablas, sin pérdida de filas |
| 02:05–02:07 | Diagnóstico posterior: «En observación», sin fallos |

**Qué pasó:**

- **La conexión con la base nunca falló.** Lo que hubo fue un intervalo de unos dos minutos entre el despliegue y la aplicación de las migraciones.
- **Por qué existe ese intervalo:** Vercel no ejecuta migraciones al desplegar, y no debe hacerlo, porque las vistas previas podrían tocar la base de producción.
- **Por qué no hubo fallo real:** el código de esas versiones tolera las tablas ausentes. Los módulos comprueban `installed()` y muestran «requiere la migración N».
- **El error del monitor:** clasificaba esa espera como incidencia crítica comparando **cantidades**.

**Estado real de 119 y 120** (verificado con Database Guardian: estructura, columnas, índices y registro):

- `119_payment_commitments.sql`: **verificada**.
  - Tablas: `payment_commitments` y `payment_commitment_events`.
  - Índices: `payment_commitments_order`, `payment_commitments_due` y `payment_commitment_events_c`.
- `120_financial_rates.sql`: **verificada**.
  - Tabla: `financial_rates`.
  - Índice: `financial_rates_kind`.
- Ninguna quedó a medias: cada migración se aplica en una sola petición atómica a Turso (`BEGIN IMMEDIATE … INSERT INTO migrations … COMMIT`). Si una sentencia falla, el flujo se cierra y Turso descarta la transacción entera.

**Corrección:**

- El monitor ya no cuenta archivos: **verifica la estructura**.
- Una migración **aditiva pendiente** pasa a ser **advertencia** (amarillo): actualización en curso, el código la tolera, y hay un aviso en notificaciones.
- Siguen siendo **críticas**:
  - la estructura incompleta o sin registro;
  - una migración modificada o duplicada;
  - una migración no aditiva pendiente.
- Si una migración aditiva sigue pendiente más de 30 minutos después del despliegue, pasa a «requiere intervención».

**Diferencias entre Preview y Producción:** no se pueden verificar desde el código, porque dependen de la configuración de variables en Vercel. Lo recomendado es que las vistas previas **no** usen la base de producción. Queda pendiente de que administración lo revise en Vercel.

## Migration Manager

**Estado de cada migración, con evidencia:**

- registro en `migrations`;
- libro `migration_ledger`: checksum SHA-256, fecha, duración, resultado, versión y ejecutor (desde 1.5.331);
- tablas, columnas e índices declarados que existen de verdad. Se tienen en cuenta los objetos que una migración posterior elimina o reconstruye; por ejemplo, la 111 reemplaza un índice de la 110;
- checksum del archivo comparado con `MANIFEST.json` y con el registrado al aplicarla.

**Estados posibles:** verificada, pendiente, incompleta, sin registro, modificada, duplicada.

**Aplicación controlada:**

- **Bloqueo distribuido** en `system_state`: una sola ejecución entre instancias, con caducidad de 5 minutos. Un bloqueo caducado se libera y se registra.
- **Una sola petición atómica** por migración.
- **Verificación posterior** de la estructura antes de registrarla en el libro.
- **Recuento de filas** antes y después de aplicar.
- Si otra instancia la registró a la vez, se comprueba antes de informar un error. Nunca se repite.
- **SQLite local:** ahora se deshace la transacción de un script fallido. Antes podía quedar abierta; Turso ya la descartaba.

**Control previo obligatorio al publicar** (`python local/versioning.py publish`, o `python local/db_guardian.py`). Detiene la publicación si hay:

- nombres no válidos;
- números repetidos;
- migraciones publicadas que se modificaron o se borraron;
- migraciones que faltan en el manifiesto.

Una migración nueva se añade al manifiesto con `python local/db_guardian.py manifest`. Ese comando se niega a regenerarlo si una migración ya publicada cambió.

## Procedimiento de publicación (con migraciones)

1. Pruebas: suite completa, `node --check` y `py_compile`.
2. Control previo de migraciones (automático en `versioning.py publish`).
3. Respaldo verificado de menos de 24 horas. Lo exige el aplicador.
4. Publicación en GitHub; Vercel despliega. El código nuevo tolera las tablas ausentes, y el monitor muestra **amarillo** con aviso.
5. **Inmediatamente:** Sistema → Migraciones → «Aplicar» (o la API), con APLICAR.
6. Database Guardian: **Verificar migraciones**. Todas deben quedar «verificada».
7. Diagnóstico de estabilidad.

## Recuperación segura (self-healing)

**Lo que hace de forma automática:** solo operaciones sin riesgo.

- **Reintentos de lectura** (`SELECT 1`): 3 intentos con espera exponencial y jitter (máximo 2 s).
- **Cortacircuitos:** tras 3 fallos seguidos, se espera 60 s antes de volver a intentar.
- **Reintentos de Turso:** ya existían, solo para lecturas y para el primer envío de una transacción. Ahora llevan jitter.
- **Bloqueo caducado:** se libera.
- **Estado:** se recalcula.

**Lo que nunca hace:**

- ejecutar migraciones destructivas;
- repetir escrituras financieras o tributarias.

## Monitor

**Niveles:**

- **verde:** operativo;
- **amarillo:** advertencia;
- **rojo:** incidencia crítica;
- **azul:** recuperación en curso (aplicación con bloqueo);
- **gris:** sin verificar o con información de más de 60 minutos.

La **gravedad potencial** del componente («crítica») se muestra aparte del estado actual. En AutoCare, una incidencia resuelta muestra «Gravedad potencial», no un nivel activo.

**Métricas:**

- tiempo de respuesta y latencia p50, p90 y p95 (p95 solo con 20 o más mediciones);
- última comprobación y última conexión correcta;
- migraciones aplicadas y verificadas, y pendientes;
- compatibilidad del esquema;
- incidencias activas y resueltas;
- versión desplegada;
- gráfica de latencia reciente.

**Botones:**

- Verificar conexión;
- Diagnóstico completo;
- Verificar migraciones;
- Consultar integridad (`quick_check`, claves foráneas y recuentos de tablas críticas, solo lectura);
- Actualizar estado;
- Consultar historial;
- Exportar diagnóstico (JSON sin credenciales ni datos de clientes);
- Ver detalles técnicos;
- Solicitar reparación controlada: libera un bloqueo caducado o lleva a aplicar las migraciones aditivas con respaldo y APLICAR.

## Incidencias

**Cada incidencia registra:**

- código, tipo y componente;
- causa;
- estado: activa, en diagnóstico, en recuperación, resuelta o requiere intervención;
- fecha de detección y de resolución, y duración;
- apariciones agrupadas e intentos de recuperación;
- versión y acciones.

**Reglas:**

- Una incidencia resuelta no mantiene el indicador en rojo.
- Nada se borra.
- Los fallos de «Faltan migraciones» ya registrados por el monitor de estabilidad se conservan como **incidencias históricas resueltas**, con su causa.

## Notificaciones

Avisa en el centro de notificaciones, con claves estables que no se duplican:

- migraciones pendientes;
- inconsistencias del esquema;
- incidencias que requieren intervención;
- incidencias críticas resueltas y verificadas (en las últimas 24 horas).

## Pruebas

`local/tests/test_db_guardian.py` (15 pruebas, con base temporal y migraciones de prueba en una carpeta temporal) cubre:

- **Conexión:** normal (verde y percentiles), lenta, interrupción recuperada con espera exponencial, reintentos agotados con cortacircuitos y resolución, reinicio de instancia y estado gris sin comprobaciones.
- **Migraciones:**
  - aditiva pendiente: advertencia, no crítica en el monitor de estabilidad;
  - aplicación verificada y registrada en el libro, sin duplicar y con los registros financieros intactos;
  - estructura sin registro e incompleta, que son críticas;
  - duplicada y modificada, que bloquean la publicación;
  - dos procesos a la vez (bloqueo, estado azul, 409 y caducidad);
  - fallo a mitad de una actualización, sin nada aplicado a medias.
- **119 y 120:** verificadas con su estructura.
- **Integración:** rutas, integridad, exportación sin secretos, notificaciones y acceso solo de administración.

## Pendiente

- **[Administración]** Revisar en Vercel que las vistas previas (Preview) no usen la base de producción.
- Aplicar las migraciones antes del código (despliegue en dos pasos) cuando una versión no pueda tolerar tablas ausentes. Hoy todas las versiones las toleran.
