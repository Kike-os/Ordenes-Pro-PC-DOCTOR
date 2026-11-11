# Idiomas de la interfaz (1.5.273 · ADI desde 1.5.276)

Órdenes Pro admite **Español (Ecuador, `es-EC`)**, predeterminado, e **Inglés (Estados Unidos, `en-US`)**.

## Cómo funciona

- **Módulo:** `local/static/i18n.js`, sin dependencias. Se carga sin `defer` antes de `app.js` en las páginas de acceso y en el panel, para aplicar el idioma antes de mostrar la tarjeta de acceso.
- **Catálogos por clave:** `CATALOG['es-EC']` y `CATALOG['en-US']` deben tener las mismas claves (lo comprueba `tests/test_i18n.py`). Las plantillas usan `data-i18n="clave"`, `data-i18n-attr="atributo:clave;…"` y `data-i18n-var-<nombre>` para valores como el mínimo de caracteres.
- **Frases en tiempo de ejecución:** `PHRASES` (coincidencia exacta) y `PATTERNS` (expresiones regulares) traducen al inglés los textos en español que llegan del servidor o de las validaciones. Lo que no coincide se deja tal cual.
- **Textos reactivos:** `i18n.text(nodo, texto)` e `i18n.attr(nodo, atributo, texto)` guardan el original en español y lo vuelven a traducir si cambia el idioma.

## Preferencia

- **Pantalla de acceso:** el selector guarda la elección en el navegador (`localStorage`) y la marca para la cuenta.
- **Al entrar:** esa elección se guarda en la cuenta (`POST /api/me/language`, con sesión y CSRF, valores `es-EC` y `en-US`). Si no hay elección pendiente, manda la de la cuenta, que se sincroniza entre equipos. Se guarda en `system_state`, con la clave `ui_lang:<id>`, sin migración. Cada cambio queda en la auditoría.
- **Después:** se puede cambiar desde el menú de cuenta (todas las cuentas) o desde Configuración → Mi perfil.

## ADI bilingüe (1.5.276)

**Causa del fallo anterior:** el chat de ADI (`static/adi-widget.js`) no consultaba `i18n.js`, el navegador no enviaba el idioma con los mensajes, las instrucciones de la IA exigían «español latinoamericano» y las respuestas fijas del servidor, la voz y el dictado estaban escritos solo en español.

**Ahora:**
- **Interfaz del chat.** Usa el mismo `i18n.js`, sin un sistema propio. Abarca:
  - encabezado, estados, presencia de la esfera y avisos del sistema;
  - accesos rápidos, sugerencias, campo de escritura, botones y títulos de accesibilidad;
  - consulta de reparación y reserva en el chat;
  - errores del servidor, horas y fechas (formato de Estados Unidos en inglés).

  El cambio es inmediato y sin recargar, con un fundido breve que se desactiva con movimiento reducido. Las demás pestañas de las páginas públicas siguen el cambio (evento `storage`). En el panel manda el idioma de la cuenta.
- **Respuestas de la IA.** Cada mensaje (`POST /api/public/adi/message`) lleva `locale`. El servidor:
  - lo valida con `adi.language()`: solo `es-EC` o `en-US`; cualquier otro valor, o ninguno, se trata como español;
  - redacta él mismo la instrucción de idioma (`adi.public_system()`), sin reenviar nada del navegador;
  - pide a la IA que responda en inglés aunque el cliente escriba en español, salvo que pida otro idioma;
  - le indica conservar marcas, modelos, números de orden, códigos y enlaces, y escribir los precios en USD con punto decimal.

  Las reglas de seguridad y de negocio no cambian.
- **Sin IA disponible.** Las respuestas fijas tienen versión en inglés (`adi.fallback_en()`), con los mismos datos reales: horarios, agenda, licencias del catálogo y contacto. También están en inglés el aviso de consulta de orden, el de espera de asesor y la comprobación de una hora concreta («tomorrow at 10 am»).
- **Voz.** Funciona en el idioma elegido:
  - la voz natural (`/api/public/adi/speech`) lee en inglés con instrucciones en inglés;
  - el saludo hablado en inglés es fijo, porque el configurado está en español;
  - la transcripción (`/api/public/adi/listen`) usa `language=en`;
  - la voz y el dictado del navegador usan voces `en-*`.
- **Historial.**
  - Cambiar de idioma no borra, duplica ni reescribe mensajes: los del cliente y las respuestas anteriores conservan su texto original.
  - Solo se traducen las etiquetas fijas y los botones de horario.
  - Las respuestas nuevas llegan en el idioma recién elegido.
  - No hay traducción automática del historial.
- **Agenda de Citas pública (`/citas`).** Todavía no es bilingüe: ahí ADI sigue en español para no mezclar idiomas en la misma página.
- **Modo administración del panel.** Las respuestas con datos del taller siguen en español; la interfaz del chat sí cambia.
- **Pruebas:** `tests/test_adi_language.py`.

## Alcance actual (pendiente de completar)

**Traducido al inglés:**
- inicio de sesión;
- recuperación y restablecimiento de contraseña;
- verificación en dos pasos y verificación de seguridad;
- mensajes del servidor del acceso;
- validaciones;
- aviso de propiedad intelectual;
- versión, estado y estabilidad del sistema;
- asistente ADI público: interfaz, respuestas, voz, consulta de reparación y reserva en el chat (1.5.276);
- ventana de actualizaciones (las notas de cada versión se publican en español);
- navegación principal;
- menú de cuenta;
- centro de notificaciones (encabezado).

**Sigue en español hasta traducirse y verificarse módulo a módulo:**
- contenido del panel;
- órdenes y seguimiento;
- clientes;
- presupuestos y proformas;
- ventas e inventario;
- pedidos de repuestos;
- citas y calendario;
- informes técnicos;
- garantías;
- PC-DOCTOR Mail Pro;
- configuración y avisos;
- Agenda de Citas pública (`/citas`);
- respuestas del modo administración de ADI.

El soporte bilingüe completo no se da por terminado hasta entonces.

**No se traducen nunca:**
- los datos escritos por clientes o por el personal;
- códigos, números de orden y de serie;
- documentos emitidos o históricos (PDF, condiciones aceptadas, notas de versión).
