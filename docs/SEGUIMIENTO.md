# Seguimiento de Órdenes (inicio)

Módulo de solo lectura que muestra **una tarjeta por orden** con su último movimiento. Sustituye a la lista de los tres últimos movimientos, donde una misma orden aparecía repetida. No borra ni modifica historial: todos los eventos siguen en `order_history` y se ven al desplegar cada tarjeta.

- **Contadores** calculados con las órdenes reales: En espera, En proceso, Esperando respuesta (cliente o presupuesto), Listas para entregar y Entregadas. El sistema no tiene un estado «diagnóstico» propio, así que no se muestra un contador con ese nombre. Los de un solo estado sirven también de filtro.
- **Tarjeta**: número de orden, cliente, tipo/marca/modelo, estado con color e icono, etapas, último movimiento con fecha y hora exactas y tiempo transcurrido, técnico responsable, quién registró la última actividad y prioridad (solo si es baja, alta o urgente). Los datos que no existen no se muestran.
- **Etapas** (Recibido → En proceso → Listo → Entregado): la actual, las completadas **solo si constan en el historial**, las anteriores sin evidencia marcadas como «sin registro» (línea discontinua) y las pendientes. No existe un estado «cancelada» en el sistema.
- **Herramientas**: buscador por orden, cliente o equipo; filtros por estado, técnico y fecha del último movimiento; «Ver detalles»; historial cronológico desplegable; paginación de 8 órdenes.
- **Actualización**: consulta cada 30 s mientras el inicio está visible (se detiene con la pestaña oculta o al salir). «En vivo · sincronizado HH:MM» solo aparece si la última consulta funcionó; si falla, indica la hora del último dato. Un movimiento nuevo anima su tarjeta y un cambio de estado genera un aviso.
- **Servidor**: `GET /api/tracking` (una consulta agrupada más los contadores) y `GET /api/tracking/<id>` (historial completo de la orden); requieren sesión. Código en `local/tracking_board.py`.

## Tabla compacta (1.5.109)

- El seguimiento pasa de tarjetas a una **tabla** con una fila por orden: Orden (con equipo), Cliente, Estado (con la línea de etapas), Último movimiento (fecha, tiempo transcurrido y quién lo registró), Técnico (con la prioridad si no es normal) y Acciones («Ver» e «Historial»). En tabletas se oculta la columna Técnico y en teléfonos cada fila se muestra como ficha.
- Se eliminaron los cinco contadores internos, que repetían los indicadores superiores. Las **seis tarjetas de estado** del inicio filtran ahora la tabla al pulsarlas (y dejan de filtrar al pulsarlas otra vez); sus números se actualizan con cada sincronización.
- La búsqueda queda siempre visible; estado, técnico y fechas están en «Filtros», con los filtros activos como etiquetas retirables.
- El historial de cada orden se despliega bajo su fila y se mantiene abierto durante las sincronizaciones. No cambia nada del historial ni de los datos.
