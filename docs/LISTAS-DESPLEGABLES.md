# Premium Smart Dropdown 2.0 · listas desplegables del sistema

**Componente central:** `local/static/ui-select.js`. Lo cargan todas las páginas con listas: panel, citas y PQRS. No se agregaron dependencias.

## Causa del problema de la Marca (Nueva orden)

Los campos Marca, Provincia, Cantón, Parroquia y Localidad (además de Marca en Citas y Plantillas de WhatsApp) usaban un `<datalist>` nativo. El navegador dibuja esa lista **fuera del control de la página**, y por eso:
- ocupa casi toda la altura;
- usa sus propios colores;
- se superpone al formulario;
- ningún CSS la corrige.

No era un problema de un campo en particular, sino de ese tipo de control.

## Solución (para todo el sistema)

- **`<input list>`:** el componente quita el atributo `list`, que suprime la lista nativa, y muestra la misma lista con el tema del sistema.
  - Búsqueda sin distinguir mayúsculas ni acentos; primero lo que empieza por lo escrito.
  - Visto ✓ en el valor actual, más «Usar «texto»» y «Limpiar selección».
  - El campo sigue aceptando texto libre como antes. No se cambian valores guardados ni marcas históricas.
  - Detecta solo los campos creados después (MutationObserver).
- **`<select>`:** el control cerrado sigue siendo el nativo, con el mismo valor, formulario, validación y eventos. Solo se reemplaza la lista que abre.
  - Con 11 opciones o más, lleva buscador.
  - Muestra grupos, opciones deshabilitadas y el visto en la opción elegida.
  - En pantallas táctiles se conserva el selector del sistema operativo.
- **Posición:**
  - alineada al campo y con su ancho (mínimo 200 px);
  - 5 px de separación;
  - altura máxima de 320 px, que se reduce si falta espacio;
  - se abre arriba si no cabe abajo;
  - 12 px de margen con los bordes;
  - se recoloca al desplazar y se cierra si el campo sale de la vista;
  - dentro de una ventana modal se dibuja en la propia ventana, sin recortes y sin depender de capas excesivas.
- **Teclado:**
  - flechas, Inicio, Fin y Re Pág/Av Pág;
  - Enter elige;
  - Escape cierra la lista **sin cerrar la ventana**;
  - Tab sale;
  - el foco vuelve al campo.
- **Lectores de pantalla:** combobox/listbox con `aria-expanded`, `aria-activedescendant` y nombre tomado de la etiqueta.
- **Diseño:**
  - fondo azul oscuro y borde de 1 px;
  - esquinas de 12 px;
  - opciones de 38 px;
  - aparición suave de 140 ms (solo opacidad, para no desplazar la lista).

## Pruebas (Playwright, base temporal)

- **Marca de Nueva orden:** 1920, 1600, 1366, 1280 y 1024 px con zoom del 80 %, 100 %, 125 % y 150 %, más 768 y 390 px, con el campo en posición normal y cerca del borde inferior. Se revisaron márgenes, altura, separación, alineación, desplazamiento horizontal y colores.
- **Auditoría de módulos:** inicio, órdenes, clientes, equipos, entregas, reportes, facturación, caja, inventario, ventas, licencias, citas, PQRS, centro de atención, ADI, configuración, sistema, correo, mantenimiento y actividad, en 6 tamaños y zooms: **98 listas, 0 fallos**.
- **Ventana de Nueva orden** (escritorio y 390 px): las listas aparecen dentro de la ventana, y Escape no la cierra.
- **Teclado:** Espacio abre, las flechas navegan, Enter elige y dispara `change`, y el foco vuelve al campo.
- **Lista de 100 opciones con el campo al borde inferior:** se abre hacia arriba, y el buscador encuentra «Área técnica» al escribir «area tecnica».

## Pendiente

- **Modo claro:** el sistema hoy es solo oscuro. Las listas usan los mismos colores que el resto de la interfaz.
- **Marcas frecuentes:** no existen estadísticas de uso por marca. Se mostrarán cuando las haya; no se inventan.
