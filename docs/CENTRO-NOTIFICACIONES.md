# Centro de notificaciones Premium Compact (1.5.266)

Ventana que se abre con la campana. Se rediseñó su presentación; la lógica no cambió:

- los avisos, su lectura y no lectura, y los contadores siguen igual;
- los permisos y el sonido no cambian;
- el historial completo («Ver el historial», `#notices`) se mantiene igual.

## Diseño

- **Contenedor:**
  - hasta 420 px de ancho y 620 px de alto, según la pantalla;
  - radio de 14 px, borde azul discreto y sombra suave.
- **Encabezado fijo:**
  - icono y título «Centro de notificaciones»;
  - dos insignias: «N sin leer», destacada si hay pendientes, y «N en total»;
  - botones de sonido y cerrar de 34 px.
- **Cuerpo:**
  - desplazamiento interno con barra delgada;
  - los avisos se agrupan por categoría: Órdenes, Presupuestos, Pagos, Seguimientos, Citas, Correos, Conversaciones, Licencias, Sistema y Alertas.
- **Grupos:**
  - cada grupo tiene icono, color de acento y su contador («2 sin leer» o «3 avisos»);
  - solo aparecen los que tienen avisos.
- **Tarjetas de aviso:**
  - acento según la prioridad: azul informativo, ámbar pendiente, verde completado y rojo suave urgente;
  - título fuerte y detalle tenue, cada uno en hasta 2 líneas, con el texto completo al pasar el cursor;
  - hora relativa y flecha de «abrir».
- **Avisos sin leer:** se distinguen por punto, título en negrita y la etiqueta «Sin leer», no solo por el color.
- **Muchos avisos en una categoría:**
  - se muestran 3;
  - «Ver N más» amplía hasta 8;
  - el resto se ve en el historial.
- **Pie fijo:**
  - «Marcar todas como leídas» y «Ver el historial», con icono y 38 px de alto;
  - en móvil se apilan a todo el ancho.

## Categorías

La clasificación más fina es **solo del panel** (`ncpCategory`). Presupuestos, Pagos y Seguimientos se separan de Órdenes según la clave y el icono del aviso. El historial conserva sus pestañas.

## Comportamiento

- Al abrir, animación breve y el foco en el título.
- Cada aviso es un botón: Enter o Espacio lo abre, lo marca como leído y cierra el panel.
- Escape cierra el panel y devuelve el foco a la campana.
- Hover y foco visibles.
- Con «movimiento reducido» no hay animaciones.
- En móvil la ventana ocupa el ancho disponible, a 12 px de cada borde, y es más alta.
- A 320 px el título pasa a dos líneas.

## Pruebas

- **Navegador:** a 1920, 1366, 1024, 768, 390 y 320 px.
- **Casos cubiertos:**
  - apertura;
  - contadores contra el servidor;
  - textos largos;
  - scroll interno;
  - categorías y «Ver más»;
  - teclado (Enter y Escape);
  - marcar todas como leídas;
  - historial;
  - movimiento reducido.
- **Datos:** avisos ficticios.
