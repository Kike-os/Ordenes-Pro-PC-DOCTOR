# Recepción técnica y evidencia fotográfica (1.5.262)

El código está en `local/reception_details.py`, las rutas en `local/app.py` y la interfaz en `local/static/app.js` (prefijo `rx`). La migración es `098_reception_details.sql`.

## Inspección física por zonas

**Zonas:** carcasa, pantalla, bisagras, tornillos/tapas/gomas, puertos, teclado, touchpad, batería, humedad/manipulación y encendido.

- **Según el tipo de equipo:** cada zona aparece solo donde aplica. Por ejemplo, bisagras y touchpad solo en portátiles, y la batería en portátiles y móviles.
- **Ubicación:** cada daño admite una ubicación opcional, con sugerencias.
- **«Sin daños visibles»:** es excluyente; el sistema no permite combinarlo con daños.
- **Texto del comprobante:** lo marcado se escribe en «Estado físico» como «Inspección inicial: …», que es lo que va al comprobante y a la hoja A4.
- **Revisión antes de guardar:** el técnico puede corregir o ampliar ese texto. La confirmación muestra exactamente lo que se guardará.

## Cargador

**Estados:** no entregado, buen estado aparente, con daños y pendiente de revisión técnica.

- **Con daños:** pide indicar el daño (cable, punta, carcasa, falso contacto, sin voltaje u otras observaciones).
- **Datos opcionales:** marca, potencia, voltaje y número de serie.
- **Sin cargador:** se agrega sola la nota «El equipo fue recibido sin cargador. Las pruebas de alimentación quedan sujetas a la disponibilidad de una fuente compatible.»

## Accesorios

- **Qué se registra:** cada accesorio recibido, con su cantidad, su estado aparente (buen estado o con daños) y una observación. Se pueden agregar accesorios personalizados.
- **No entregado ≠ dañado:** un accesorio no entregado no se marca; uno recibido con daños se marca con ese estado.
- **Texto del comprobante:** se compone en «Accesorios recibidos».

## Fotos de evidencia

- **Categorías:** recepción, diagnóstico, reparación y entrega.
- **Datos de cada foto:** zona o pieza y observación.
- **Zona de la foto (1.5.263):** además de las zonas de inspección, se puede elegir el cargador y **cada accesorio recibido** por su nombre (por ejemplo, «Mouse y receptor USB»), para fotografiar un accesorio concreto cuando hace falta.
- **Nombre descriptivo:** sigue el formato `PCD-20261109-0001_HP_240-G7_Pantalla_01.jpg`, y la foto se descarga con ese nombre.
- **Fecha, hora y técnico:** quedan registrados.
- **Marcar daños:** las marcas, con lápiz o círculo en rojo o amarillo, se guardan en una **copia**. El original no cambia y sigue siendo la evidencia; la vista ampliada alterna entre los dos.
- **Eliminar:** solo administración, con motivo obligatorio. La foto deja de verse en la orden, pero **se conserva** en el historial de evidencias con quién, cuándo y por qué.
- **Límite:** 12 fotos activas por orden. En la recepción se mantienen 8; las fotos se reducen en el navegador (JPEG de hasta unos 560 KB).

## Compatibilidad

- **Órdenes anteriores:** no tienen detalle estructurado; siguen mostrando sus textos de siempre.
- **Borradores anteriores:** se convierten a la inspección nueva.
