# PC-DOCTOR Mail Pro Fluent 2.0

Rediseño visual y de uso del módulo de correo, inspirado en Outlook y Fluent Design 2. Se construye sobre la lógica existente y no cambia ninguna acción del servidor: el envío, las acciones IMAP, las etiquetas, deshacer, el vínculo con órdenes y el Centro de Entrega funcionan igual que antes.

- Código: `renderMail` en `local/static/app.js` (clase `mail-fluent` y funciones `mailInitials` y `mailGroup`).
- Estilos: bloque «Mail Pro Fluent 2.0» al final de `local/static/app.css`, que solo afecta a `.mail-fluent`.

## Qué cambia

### Barra de comandos
Una barra estilo Outlook encima de los tres paneles. Incluye:
- Nuevo correo, Responder, Responder a todos, Reenviar;
- Archivar, Eliminar, Leído / No leído, Etiquetas;
- Sincronizar, Imprimir;
- Destacar, Resumir con ADI, Marcar como respondido;
- modo de lectura ampliado y pantalla completa;
- Más.

Cada comando ejecuta el botón real del mensaje abierto, así que las acciones y los permisos son los mismos de antes. Sin mensaje abierto, esos comandos quedan deshabilitados.

La barra se compacta de forma progresiva:
1. Primero los comandos menos usados pierden el texto.
2. Después todos quedan solo con icono.
3. Solo si aun así no caben, pasan a «Más».

Ningún botón queda cortado.

### Paneles ajustables
- Arrastre de los divisores: navegación entre 210 y 260 px, lista entre 300 y 600 px.
- Teclado: flechas izquierda y derecha, Mayús para pasos mayores, Inicio y Fin para los límites.
- Doble clic restablece el ancho predeterminado.
- Los anchos se recuerdan en este navegador.

### Bandeja
- Avatar con las iniciales del remitente y un color estable.
- Agrupación por fecha: Hoy, Ayer, Esta semana, Este mes, Anteriores (hora de Ecuador).
- Diferencia más clara entre mensajes leídos y no leídos.
- Las acciones rápidas aparecen al pasar el cursor o con el foco del teclado.
- Filtros en una sola fila, sin recortes.
- Carga con esqueleto.
- El buscador indica qué busca: remitente, asunto, cliente u orden.

### Lectura
- Encabezado compacto.
- La barra de comandos reemplaza la barra inferior anterior, así que el botón de ADI ya no puede tapar ninguna acción.
- Pantalla completa disponible.

### Estilo Fluent
- Superficies por capas: Mica en la navegación y Acrylic en la barra de comandos.
- Bordes de 8 a 12 px.
- Segoe UI, o la fuente del sistema cuando no está instalada.
- Transiciones de 150 a 250 ms.
- Con `prefers-reduced-motion` se desactivan las animaciones y transiciones.

### Página
- El encabezado del módulo es compacto, para dejar el espacio al correo.

## Pendientes

- **Sección 6, ADI Mail Intelligence:** el texto de la orden llegó cortado. El resumen existente («Resumir con ADI») está disponible desde la barra. El panel lateral se hará cuando llegue el texto completo.
- **Iconos:** se usa la biblioteca de iconos del sistema (estilo lineal coherente). No se incorporaron los Fluent UI System Icons de Microsoft para no mezclar dos bibliotecas.
