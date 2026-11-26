# Premium Smart Status 2.0

Indicadores de estado de presupuesto con un solo componente, `quoteBadge` en `local/static/app.js`, con estilos `.quote-badge` en `local/static/app.css`.

Se aplica en todos los lugares donde ya se usaba:
- resumen y panel de presupuesto de la orden;
- editor de presupuestos y sus versiones;
- proformas;
- equipos;
- listas.

No cambia la lógica de negocio ni los estados: solo su presentación.

## Estados

| Estado | Icono (Lucide) | Color | Animación |
|---|---|---|---|
| Sin presupuesto (`vacio`) | archivo con + | ámbar | pulso (requiere atención) |
| Borrador | lápiz | gris azulado | — |
| Enviado / en revisión / pendiente | reloj | ámbar | agujas que giran despacio |
| Revisión solicitada (`modificacion`) | flechas de actualizar | ámbar | pulso |
| Correo no enviado (`sin_correo`) | correo con × | rojo | pulso |
| Aprobado | círculo con ✓ | verde | la marca ✓ se dibuja una vez |
| Aprobado parcialmente | círculo a medias | azul | — |
| Rechazado | círculo con × | rojo | — |
| Vencido | calendario con × | naranja | pulso |
| Cancelado | círculo tachado | gris | — |

- **Descripción emergente:** al pasar el cursor se ve el estado y qué significa.
- **Cambios posteriores:** si otro código cambia `data-status` después de crear el indicador, como ocurre con «Sin presupuesto», el icono y la descripción se actualizan solos.
- **Transiciones:** de 200 ms.
- **Movimiento reducido:** con `prefers-reduced-motion` no hay animaciones y la marca ✓ aparece completa.
- **Tema:** el sistema usa el tema oscuro. El componente ya trae los colores del modo claro para cuando se active `data-theme="light"`.
- **Textos:** compactos y sin salto de línea; si un texto no cabe, termina en «…» y la descripción emergente lo muestra completo.
