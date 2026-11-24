# ADI Enterprise AI 3.0 · Smart Communication — fase 1 (1.5.326)

La fase 1 añade a la ventana **Mensaje de seguimiento** de la orden:

- el análisis integral de la orden;
- los mensajes por motivo;
- el control previo al envío;
- la gestión de retrasos.

**Límites:**

- No envía mensajes. El envío real sigue en la comunicación de la orden, que confirma el destinatario y el resultado.
- No registra pagos, no cambia saldos, no aplica intereses y no modifica la orden.
- No necesita migraciones.

Módulo: `local/adi_comms.py`. Ruta: `POST /api/orders/<id>/adi-comms`, con estas acciones:

- `analysis`
- `compose`
- `precheck`
- `record`
- `delay`

Acceso: administración y técnicos, igual que el mensaje de seguimiento.

## Análisis integral

El servidor reúne lo registrado y lo filtra antes de mostrarlo o de pasarlo a la IA. Cada dato indica su fuente. El análisis tiene cinco secciones:

- **Cliente y orden:**
  - nombre y número de orden;
  - celular enmascarado (`…67`) y autorización de avisos por WhatsApp;
  - si tiene correo.
- **Equipo y servicio:**
  - equipo y motivo de ingreso;
  - diagnóstico comunicable;
  - servicios del presupuesto, sin importes;
  - trabajos y seguimientos comunicables;
  - recomendaciones.
- **Estado y plazos:**
  - estado y desde cuándo;
  - fecha estimada confirmada;
  - historial de estados;
  - repuestos con su etapa y llegada estimada;
  - garantía, en equipos entregados.
- **Pagos** (una sola fuente: los pagos de la orden, para no sumar dos veces la misma obligación):
  - valor presupuestado y aprobado;
  - total, pagos y anticipos confirmados;
  - transferencias por conciliar, que no son deuda confirmada ni pago confirmado;
  - saldo;
  - facturas vinculadas. Una factura «autorizada» **no significa pagada**.
  - Vencimientos: «Sin fecha de vencimiento registrada».
  - Compromisos: fase 2.
- **Comunicación:**
  - mensajes anteriores;
  - lo pendiente del cliente: aprobar un presupuesto o responder una consulta.

**Nunca incluye:**

- notas internas (indica cuántas se omitieron);
- costos de adquisición y márgenes;
- contraseñas y credenciales.

Las notas de la orden son datos: no cambian estas reglas.

## Mensajes por motivo

| Grupo | Motivos | Cuándo se ofrecen |
|---|---|---|
| Servicio técnico | Recepción, inicio del diagnóstico, diagnóstico finalizado | Según el estado y el diagnóstico registrado |
| | Presupuesto disponible / pendiente de aprobación | Presupuesto enviado sin decisión (pendiente: al menos 2 días) |
| | Solicitud de información adicional | Orden no entregada; el operador escribe qué se necesita |
| | Repuestos en tránsito / retraso de repuestos | Repuesto pedido sin llegar / con llegada vencida o retraso registrado |
| | Retraso en la reparación | Fecha estimada confirmada vencida y atribuible a PC-DOCTOR |
| | Ampliación de plazos | Nueva fecha estimada confirmada registrada en la orden |
| Entrega y posventa | Reparación finalizada, listo para entregar | Orden lista |
| | Recordatorio de retiro | Lista desde hace al menos 3 días |
| | Garantía / atención posventa | Entregada (posventa: hasta 30 días) |
| Pagos | Pago pendiente | Saldo pendiente confirmado |
| | Confirmación de pago | Pago confirmado en los últimos 7 días |
| | Compromiso de pago / incumplido | Fase 2 (no disponible todavía) |
| | Estado de cuenta | Fase 4 (no disponible todavía) |
| | Aviso de intereses | **Nunca:** los intereses solo se simulan y no se comunican sin validación jurídica y contable y autorización expresa |

**Cómo se redactan:**

- El sistema escribe la base solo con datos registrados.
- En los motivos técnicos, ADI puede mejorar la redacción, pero no recibe importes. Si propone importes o afirmaciones no registradas, se conserva el texto del sistema.
- Los mensajes de pago los escribe solo el sistema, con los valores exactos.
- Si hay transferencias por conciliar, el mensaje lo aclara («no es necesario volver a pagar»).
- **Mensaje discreto:** por WhatsApp, sin la autorización de avisos registrada, un mensaje de pago no muestra importes ni enlaces. Invita a verificar la identidad o a hablar con el personal.
- Un mensaje nunca menciona intereses, mora ni recargos.

## Control previo al envío (12 puntos)

Al pulsar «Enviar», la orden se consulta de nuevo. Cada punto queda en uno de tres niveles: ✓ correcto, ⚠ aviso o ✕ bloqueo. Un solo bloqueo impide continuar.

1. **Orden consultada de nuevo.**
2. **Destinatario registrado:** celular válido para WhatsApp o correo válido.
3. **El destinatario corresponde a la orden:** solo el titular, nunca familiares ni terceros.
4. **Estado actualizado:** el motivo sigue correspondiendo a la orden.
5. **Valores económicos confirmados:** se aplica la misma comprobación que al enviar el mensaje de seguimiento. Si el saldo cambió después de generar el texto, se bloquea.
6. **Pagos recientes:** con transferencias por conciliar, se bloquea un mensaje que afirma un saldo sin aclararlo.
7. **Sin notificación duplicada:** el mismo motivo en las últimas 24 horas se bloquea.
8. **Privacidad:** se bloquean:
   - contraseñas, costos, márgenes y notas internas;
   - números de identificación;
   - importes por WhatsApp sin autorización de avisos.
9. **Horario permitido:**
   - Cobranza: lunes a viernes laborables, de 08:00 a 19:00 (hora de Ecuador), y nunca en feriados. Fuera de ese horario se bloquea.
   - Otros motivos: solo se muestra un aviso.
10. **WhatsApp Business:**
    - sin configurar, se bloquea;
    - fuera de la ventana de 24 h, se avisa de que hace falta una plantilla aprobada.
11. **Permisos y consentimiento:**
    - si el cliente rechazó los avisos, se bloquea;
    - sin registro, se muestra un aviso;
    - **cobranza:** como máximo una gestión al día por cliente entre todos los canales.
12. **Motivo registrado:** al continuar se registra `adi_msg:<motivo>` en la auditoría. El servidor repite el control antes de registrarlo.

## Retrasos

Un retraso se detecta en dos casos:

- la fecha estimada confirmada pasó y la orden no está lista;
- un repuesto tiene la llegada vencida o un retraso registrado.

Si la orden espera al cliente (presupuesto o consulta), el retraso **no se atribuye** a PC-DOCTOR.

Si es atribuible, el mensaje:

- se disculpa y explica solo lo registrado;
- no promete fechas;
- no responsabiliza al cliente;
- ofrece atención humana.

**Registrar incidencia de retraso:**

- Añade una nota en el Centro de Control, en el pendiente de esa orden, para su responsable. Lo deja registrado en la auditoría.
- No cambia la orden.
- Si no hay un retraso atribuible, responde 409.

## Pruebas

`local/tests/test_adi_comms.py` usa una base temporal, datos ficticios, IA simulada y WhatsApp sin credenciales. Cubre:

- **Datos y privacidad:** el análisis filtrado (sin notas internas, costos ni claves; celular enmascarado) y la privacidad (credenciales e identificación).
- **Pagos:**
  - cliente sin deuda;
  - pago parcial y en efectivo, sin intereses;
  - transferencia por conciliar;
  - mensaje discreto sin consentimiento;
  - saldo que cambia después de generar.
- **Motivos e IA:** intereses y fases posteriores nunca se redactan; la IA no añade importes ni afirmaciones.
- **Control previo:**
  - horario: fin de semana, feriado (25/12), antes de las 08:00 y desde las 19:00;
  - duplicados y una gestión de cobranza al día;
  - WhatsApp sin configurar y teléfono incorrecto.
- **Retrasos:** atribuible y no atribuible.
- **Sin efectos:** no se envía ni se cambia nada.

## Pendiente (fases siguientes)

- **2:** compromisos de pago.
- **3:** política de gracia de 90 días y motor de intereses, **solo en simulación**, con el registro de tasas.
- **4:** centro de cartera, expediente económico y estados de cuenta.
- **5:** auditoría de comunicaciones y reglas de campañas.

No se activa el cobro de intereses reales ni campañas automáticas sin una autorización expresa e independiente.
