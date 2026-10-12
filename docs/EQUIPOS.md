# Equipos e historial técnico

El módulo «Equipos» muestra cada dispositivo registrado con el icono de su tipo, marca y modelo, número de serie, cliente, cuántas órdenes acumula y el estado de la última.

- **Buscador:** serie, cliente (nombre o identificación), marca o modelo. Filtros por tipo de equipo y «Solo series repetidas».
- **Historial técnico:** botón en cada equipo que abre su ficha (serie, cliente, órdenes registradas, entregadas, en curso, primera recepción) y todas sus reparaciones, de la más reciente a la más antigua, con falla reportada, hallazgos, recomendaciones, responsable y enlace a la orden (`/api/devices/<id>`). No incluye valores económicos.
- **Series repetidas:** cuando el mismo número de serie figura en más de un equipo se marca «Serie repetida» y la ficha enumera los demás registros. No se fusionan ni se borran automáticamente: es una advertencia para comprobarlo con el cliente.
- Todo es de solo lectura, salvo «Editar» y «Registrar equipo», que siguen reservados a administración. Los equipos se crean normalmente al registrar una orden de recepción.
