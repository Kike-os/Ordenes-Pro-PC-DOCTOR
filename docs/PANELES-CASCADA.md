# Paneles compactos con desplazamiento en cascada (1.5.244)

**Dónde se aplica:** Órdenes de Reparación y la vista **Lista** de la Agenda de Citas. Día, Semana y Mes quedan sin cambios y sin movimiento automático.

## Funcionamiento

**Panel con altura controlada:**
- La altura se ajusta con `clamp()`: unos 5 o 6 registros a la vista en escritorio y el 72 % de la pantalla en el teléfono.
- La cabecera queda fija dentro del panel. El resto se recorre ahí mismo con rueda, touchpad, teclado o dedo.
- La página no crece indefinidamente.

**Movimiento automático (`cascadePanel()` en `app.js`):**
- Espera 5 s y avanza unos 18 px por segundo, en continuo y sin saltos.
- Al final se detiene 4,5 s y vuelve arriba con suavidad.
- Usa los registros ya cargados: no reordena, no duplica y no consulta al servidor.

**Se detiene:**
- con el cursor encima, el foco o texto seleccionado dentro;
- con un menú de acciones, una ventana o un modal abiertos;
- con la pestaña oculta o con «reducir movimiento».

Tras cualquier interacción espera 8 s antes de seguir.

**Control en la cabecera del panel:**
- Interruptor «Movimiento automático», guardado en el navegador para cada panel.
- Pausar / Reanudar.
- Estado: «En movimiento», «En pausa», «Desactivado», «Movimiento reducido» o «Todo a la vista».

En pantallas táctiles empieza **apagado**, con desplazamiento manual. Si todo cabe en el panel, no se mueve.

**Buscar o filtrar** repinta el panel y lo reinicia arriba. El bucle se detiene solo cuando el panel sale de la página, sin dejar temporizadores.

## Otros detalles

- **«Solo activas»:** ya excluía las órdenes entregadas en el servidor. Siguen disponibles quitando el filtro o buscando, y no se borra ni archiva nada.
- **Feriados:** resumen compacto con los próximos tres y «Ver todos los feriados» para el resto. Los datos, los horarios y la lógica de disponibilidad no cambian.

## Pruebas de navegador

Con 126 órdenes y 45 citas ficticias:
- altura;
- movimiento y sus pausas (cursor, menú, modal, Pausar/Reanudar);
- búsqueda con 0, 1, 5 y 20 resultados, sin duplicados;
- «Solo activas»;
- preferencia guardada, movimiento reducido y táctil apagado;
- Agenda (Lista, cabecera fija, citas pasadas, futuras, canceladas y por confirmar);
- feriados y vistas Día, Semana y Mes;
- 320 a 1920 px.
