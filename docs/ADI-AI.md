# Adi AI — asistencia de redacción (Fase 1) — 11/10/2026

## Qué hace

Botón **Mejorar con Adi** junto a los campos de texto de las órdenes: falla reportada, observaciones de recepción e inspección física (nueva orden); descripción de trabajo, observaciones del técnico, hallazgos, recomendaciones y comentario del historial (edición de la orden); y el comentario de seguimiento.

El técnico elige el tipo de mejora (ortografía, redacción, redacción técnica, simplificar, explicación para el cliente), ve la sugerencia con los cambios resaltados y decide **Aplicar mejora**, **Regenerar** o **Cancelar**. Nada se reemplaza sin su aceptación y «Deshacer» recupera el texto original.

## Estado real

- **Proveedor de IA: no configurado.** No hay ninguna clave en el servidor, así que hoy el botón solo explica que falta la conexión. El servicio, las rutas y la interfaz están probados con un proveedor simulado; falta la prueba con un proveedor real.
- Para activarlo: definir `ANTHROPIC_API_KEY` (Claude; modelo por defecto `claude-opus-5-5`, ajustable con `ADI_MODEL`) u `OPENAI_API_KEY` en Vercel y en `local/.env`. La clave nunca llega al navegador.
- Canales: chat web activo (respuestas por reglas); correo según Mail Pro; WhatsApp sin conexión oficial, pendiente.

## Protecciones

- Al proveedor solo viaja el párrafo y el nombre del campo; ningún dato del cliente ni de la orden.
- El texto se envía como dato entre etiquetas y el modelo tiene instrucción de no obedecer lo que contenga.
- Se comprueba que series, códigos, medidas, fechas e importes del original sigan idénticos; si falta alguno, la interfaz lo advierte.
- Solo administración y técnicos; 60 mejoras por usuario y hora; 4000 caracteres por consulta; 25 s de espera.
- Cada uso se registra en `adi_actions` (usuario, tipo, modelo, tokens) sin guardar el texto.
- Se desactiva en Configuración → «Adi — asistencia de redacción».

## Pendiente (fases siguientes)

Fase 2: Mail Pro y mensajes a clientes. Fase 3: respuestas sugeridas con base de conocimiento. Fase 4: atención automática supervisada. Ninguna está implementada; ningún mensaje se envía automáticamente.

## Archivos

`local/adi_ai.py`, rutas `/api/adi/status`, `/api/adi/write`, `/api/adi/settings` en `local/app.py`, `attachAdi` en `local/static/app.js`, pruebas en `local/tests/test_adi_ai.py`.


Desde la 1.5.46 el servidor acepta también la variable `OPEN_API_KEY` (nombre mal escrito frecuente) como clave de OpenAI. El nombre correcto sigue siendo `OPENAI_API_KEY`.
