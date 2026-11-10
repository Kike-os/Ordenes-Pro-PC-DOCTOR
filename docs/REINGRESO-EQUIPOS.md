# Reingreso de equipos (1.5.267)

Cuando un cliente vuelve con un equipo que ya se atendió y entregó, se registra una **orden nueva** vinculada al **mismo equipo** (su registro maestro `EQ-0001`). La orden anterior **no se reabre ni se reutiliza**: conserva su número, estado, fechas de ingreso y entrega, pagos, presupuesto, diagnóstico, fotos y documentos.

## Cómo se inicia

- **Desde la orden entregada:** botón «Reingresar equipo» en las acciones.
- **Desde la ficha del equipo** (Historial técnico), la **lista de equipos** (si su última orden está entregada) o el **historial de equipos del cliente**.
- **Por número de serie en la recepción:** al escribir o escanear la serie, si pertenece a un equipo del cliente elegido, la recepción pasa sola a «Equipo existente» y conserva su identidad. Si el cliente aún no está elegido, «Usar también este cliente» hace lo mismo. En el servidor, la misma serie con las mismas características reutiliza el registro (la respuesta indica `linked_device`). Con otra marca, modelo, tipo o color **no se fusiona automáticamente**: queda como equipo aparte, señalado como «Serie repetida», para comprobar con el cliente si es el mismo.

La recepción se abre con el cliente y el equipo fijados, en modo «Equipo existente», y muestra la atención anterior: número, estado y fecha de entrega. Un equipo con un ingreso **abierto** no admite otro: el botón queda deshabilitado y el servidor responde 409 con el número de la orden abierta.

## Historial

- La ficha del equipo (`GET /api/devices/<id>`) lista todas sus órdenes, de la más reciente a la más antigua, con su código `EQ`.
- El detalle de una orden incluye `device_visits`: la cantidad de atenciones del equipo y la anterior. La interfaz lo muestra como «Reingreso del equipo EQ-…», con accesos a la orden anterior y al historial técnico.

## Búsqueda

Las listas de órdenes y de equipos encuentran por serie, cliente, cédula, marca, modelo, número de orden, código `EQ` y **teléfono en cualquier formato** («0991234567», «099 123 4567» o «+593991234567»), con la misma conversión que el buscador global (`phones.as_query`).

## Qué no cambia

- La «Revisión por falla recurrente» sigue existiendo para administración, dentro de la misma orden y con su registro aparte.
- Un mismo número de serie a nombre de **otro cliente** genera un equipo separado y la recepción lo advierte, sin fusionar nada.

Pruebas: `local/tests/test_reingreso.py`. Cubre:
- orden entregada y pagada que vuelve meses después;
- el reconocimiento por serie;
- un solo registro maestro;
- la independencia de pagos, presupuesto, diagnóstico y documentos;
- las fechas originales intactas;
- el número nuevo;
- el historial con ambas atenciones;
- el ingreso abierto, la marca distinta, otro cliente y la búsqueda.
