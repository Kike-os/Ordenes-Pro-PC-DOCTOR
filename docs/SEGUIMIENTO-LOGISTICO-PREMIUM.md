# Seguimiento logístico Premium 4.0 (1.5.269)

Rediseño de la parte inferior de cada repuesto en el detalle de la orden (panel interno, `.opr-card`). **La animación del recorrido no cambia**: el SVG, el avión y el vehículo, las trayectorias, la velocidad, los iconos de origen, aduana, Otavalo y PC-DOCTOR, las transiciones y la lógica son los mismos.

Comprobación automática, con los mismos datos ficticios en producción y en la rama:
- huella del HTML del mapa: idéntica;
- huella de las propiedades de animación (nombre, duración, retardo, curva, repeticiones, dirección, trayectoria y tamaños de los contenedores): idéntica;
- animaciones SVG: 15 en ambos.

## Pasos logísticos detallados
- **Pasos:** los mismos, con su orden y sus nombres, tal como vienen de los datos (`r.detail`).
  - Cada paso lleva número, indicador de estado (completado con marca, actual con anillo y la insignia «Actual», pendiente vacío, no registrado con borde discontinuo) y la fecha alineada a la derecha.
  - Medidas: 34–42 px de alto, radio de 10 px, separación de 6 px y letra de 12,5 px. El brillo azul al pasar el cursor dura 200 ms y no hay animaciones continuas.
- **Resumen:** «N de M completados» con los completados reales y «Actual: …» con el paso en curso; el lector de pantalla recibe lo mismo.

## Tarjetas informativas
- **Distribución:** Envío, Proveedor y pedido, Transporte, Fechas y Taller se reparten las filas (3 + 2 en el panel), sin huecos ni tarjetas aisladas y con alturas parejas por fila. Sigue el estilo Command Center: icono, título y bordes azul oscuro.
- **Códigos largos** (número de pedido, número de seguimiento, guías): se ven completos sin desbordar la tarjeta y tienen un botón **Copiar**.
- **Observaciones internas:**
  - ocupan el ancho completo, con borde ámbar y el distintivo INTERNO;
  - un texto largo se recorta a 3 líneas con «Ver más», que solo aparece si hay texto oculto;
  - el seguimiento público no las muestra y los permisos no cambian.

## Avisos al cliente
- **Presentación:**
  - tarjeta de ancho completo con un resumen de enviados, omitidos y fallidos;
  - se ven los 4 avisos más recientes en dos columnas, con «Ver todos» para el resto;
  - cada aviso muestra canal, fecha y hora, **estado real**, motivo de omisión o error y «Detalles» (evento, canal, estado, fechas, intentos, respuesta y acceso a la comunicación de la orden).
- **Estados:** un aviso omitido nunca se muestra como enviado.
- **Reintento controlado:** solo administración, solo avisos fallidos con intentos disponibles y con confirmación; los omitidos no se reenvían.
- **WhatsApp Business sin configurar:** se explica por qué esos avisos quedan omitidos, con «Revisar configuración» (Configuración → Correo y servicios, solo administración).

## Pruebas
Prueba en el navegador `log269`, 18/18:
- datos y contador de los pasos;
- medidas de los pasos;
- reparto de las tarjetas;
- códigos y copia;
- observaciones internas en escritorio y móvil;
- avisos, detalle y configuración de WhatsApp;
- reintento cancelado sin cambios;
- seguimiento público sin datos internos;
- 1920, 1024, 768, 390 y 320 px;
- movimiento reducido;
- ausencia de errores de JavaScript.
