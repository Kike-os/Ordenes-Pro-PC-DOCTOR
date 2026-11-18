# Prórrogas del plazo de retiro (1.5.294)

Permiten conceder al cliente días adicionales para retirar su equipo cuando la permanencia en taller está por vencer o ya venció. Se gestionan desde el detalle de la orden, en «Permanencia en taller» → «Plazo de retiro».

## Plazos

- **Fecha original:** el día de ingreso en Ecuador (America/Guayaquil) más el plazo administrativo de permanencia (por defecto 90 días naturales; configurable en «Configurar plazo»).
- **Fecha vigente:** la de la prórroga vigente o, sin prórroga, la original. El día límite cuenta completo: la orden figura vencida a partir de las 00:00 del día siguiente, hora de Ecuador.
- **Nueva fecha:** se suma sobre la fecha vigente o, si ya venció, sobre hoy. Nunca queda una fecha pasada. Opciones: 3, 7, 15 o 30 días, o una fecha personalizada posterior, hasta 365 días por prórroga.

Con una prórroga vigente, la permanencia muestra «Prórroga vigente hasta …», y el indicador de vencidos, los informes y la alerta «superó el plazo» usan la fecha vigente. Además, no se envían los avisos automáticos de permanencia («plazo vencido»): rigen los recordatorios de la prórroga.

## Qué no cambia

- El estado de reparación, el número de orden, los datos originales, las firmas, los documentos y los presupuestos.
- Ningún cobro. El sistema no calcula bodegaje: el almacenaje se rige por las condiciones aceptadas, y una prórroga no condona ni modifica cargos.

## Otorgar, ampliar y revocar (solo administración)

- **Ventana Premium Compact 2.0:** opciones de días o fecha, y un resumen previo con la fecha original, la fecha vigente, los días adicionales y la nueva fecha. Pide motivo (lista más detalle; el detalle es obligatorio con «Otro motivo»), observaciones internas y responsable de la autorización (por defecto, quien la registra). Permite avisar al cliente si hay canales disponibles.
- **Validaciones del servidor:**
  - solo órdenes no entregadas, porque «Entregado» es el único estado final del sistema;
  - fecha posterior a la vigente;
  - motivo y responsable obligatorios;
  - el plazo vigente que vio la persona (`expected_due`) debe seguir siendo el mismo: si otra persona cambió la prórroga mientras tanto, la petición se rechaza (409) y la ventana recarga los datos;
  - la misma prórroga repetida en 2 minutos no se duplica.
- **Ampliar:** la nueva prórroga queda vigente y la anterior pasa a «Reemplazada».
- **Revocar:** exige motivo. Si la prórroga revocada reemplazaba a otra, esa vuelve a regir en una fila nueva; si no, rige la fecha original.
- **Historial (`order_extensions`, migración 109):** nada se borra ni se reescribe; la base lo impide con disparadores. Cada fila guarda el plazo original, el anterior y el nuevo, los días, el motivo, las observaciones, el responsable, quién y cuándo, y el cierre (reemplazo o revocación) con su motivo. Cada acción queda en la auditoría (`order_extension_granted`, `order_extension_revoked`, `order_extension_notice_retry`).
- Los técnicos consultan el plazo y el historial, pero no otorgan ni revocan.

## Avisos

- **Interno:** el otorgamiento y la revocación quedan en el historial de la orden y aparecen en las notificaciones del resto del equipo.
- **Al cliente (`order_extension_notices`):** un registro por prórroga, tipo, anticipación y canal, sin duplicados.
  - **Correo del sistema:** plantilla institucional, archivado y con seguimiento de entrega. Se envía después de confirmar la prórroga: si falla, la prórroga queda registrada y el aviso queda «No enviado» con su motivo. «Reintentar» lo reenvía una sola vez cada vez (hasta 5 intentos): toma el aviso antes de enviarlo, así que dos clics no envían dos correos, y nunca repite uno ya enviado.
  - **WhatsApp Business:** evento «Prórroga del plazo de retiro» en la cola existente, con sus reglas: credenciales configuradas, consentimiento del cliente, plantilla aprobada, sin repeticiones y reintentos desde la cola.
  - Un canal no disponible queda «omitido» con el motivo real. Nada se simula.
- **Recordatorios:** antes del nuevo plazo (por defecto 3 y 1 días), por correo. Están desactivados hasta que administración los active en «Recordatorios de prórroga»; salen una vez por prórroga y anticipación, en horario diurno.

## Centro de Notificaciones y Pendientes

Las prórrogas que vencen en los próximos días (según los recordatorios, mínimo 3) o que vencieron sin retiro aparecen como pendientes de «Órdenes»: «Prórroga por vencer» o «Prórroga vencida», con acceso directo a la orden. Desaparecen al entregar la orden, al revocar la prórroga o al otorgar un plazo mayor.
