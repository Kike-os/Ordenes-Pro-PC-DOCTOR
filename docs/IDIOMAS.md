# Idiomas de la interfaz (1.5.273)

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

## Alcance actual (pendiente de completar)

**Traducido al inglés:**
- inicio de sesión;
- recuperación y restablecimiento de contraseña;
- verificación en dos pasos y verificación de seguridad;
- mensajes del servidor del acceso;
- validaciones;
- aviso de propiedad intelectual;
- versión, estado y estabilidad del sistema;
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
- asistente ADI (conversación y botones).

El soporte bilingüe completo no se da por terminado hasta entonces.

**No se traducen nunca:**
- los datos escritos por clientes o por el personal;
- códigos, números de orden y de serie;
- documentos emitidos o históricos (PDF, condiciones aceptadas, notas de versión).
