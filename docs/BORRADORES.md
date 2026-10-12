# Borradores de Nueva orden

Desde la 1.5.42 los borradores se guardan en el servidor (tabla `order_drafts`, migración 030), no en el navegador.

- Un borrador por usuario, con identificador, propietario, fecha de creación, fecha de actualización, estado y número de revisión. Guardar otra vez actualiza el mismo registro.
- Guardar un borrador no crea la orden, ni su número, ni documentos. No exige los campos obligatorios de la orden.
- Se conservan cliente, equipo, recepción, accesorios, paso del asistente y las autorizaciones de acceso (decisión, alcance, descripciones y operaciones de riesgo).
- **No** se conservan: fotos (solo existen en la memoria del navegador hasta finalizar; al recuperar se avisa cuántas faltan), contraseñas, ni las casillas de confirmación del cliente y de aceptación de condiciones, que deben volver a marcarse al finalizar.
- Si otra sesión guardó un borrador más reciente, el servidor responde con un conflicto y pide decidir si se reemplaza. El guardado automático nunca reemplaza un borrador más reciente.
- «Descartar» vacía el borrador y deja constancia en auditoría. Al finalizar correctamente la orden, el borrador se descarta.
- Guardado automático opcional (casilla «Auto», preferencia de cada navegador): guarda tras 4 segundos sin escribir.
- Un borrador antiguo guardado en el navegador se sigue ofreciendo para recuperarlo; al guardar pasa al servidor.

Rutas: `GET /api/order-draft`, `POST /api/order-draft` (`data`, `revision`, `force`) y `POST /api/order-draft` con `action: discard`.
