# Inicio de sesión Premium Compacto (1.5.280)

Rediseño de presentación de la página de acceso. No cambia la autenticación, las sesiones, los permisos ni el backend.

## Qué cambió

**Orden de la tarjeta:**
1. Logotipo original.
2. «Órdenes Pro».
3. «PC-DOCTOR S.A. · Sistema de Gestión de Reparaciones», en una línea.
4. Selector de idioma.
5. Usuario y contraseña.
6. Recordar sesión y recuperar contraseña.
7. «Iniciar sesión».
8. Aviso de propiedad intelectual compacto.
9. Versión compacta.
10. «Agendar cita» y «PQRS», dentro de la tarjeta.

**Detalle de cada parte:**
- **Logotipo:** es el mismo archivo `logo-original.png`, a 88–108 px de ancho, con su proporción natural y sin filtros (se retiró el halo azul anterior).
- **Selector de idioma:** una sola fila. El rótulo «Seleccione su idioma / Select your language» queda para lectores de pantalla y el idioma activo sigue marcado.
- **Aviso legal:**
  - El título «Software privado · Propiedad intelectual protegida» siempre está visible y despliega el texto completo, sin cambios; se abre con ratón o teclado.
  - El © está siempre visible.
- **Versión:**
  - La fila muestra el número y el estado real («Sistema actualizado» solo si la comprobación tuvo éxito; si falla, el aviso de error con «Reintentar»).
  - «Detalles» despliega la fecha de publicación, la última comprobación, «Actualizaciones del sistema» (historial) y la estabilidad («En observación»).
  - «Reintentar» y «Recargar página» aparecen en la fila cuando hacen falta.
- **Accesos públicos:**
  - «Agendar cita» (icono `calendar-days`) y «PQRS» (`messages-square`) tienen el mismo ancho y alto.
  - En pantallas de hasta 380 px se apilan.
  - En inglés: «Book Appointment» y «PQRS».

**Diseño:**
- Tarjeta de 412 px como máximo, con relleno de 18–22 px y separación de 12 px.
- Sin `overflow:hidden` ni posiciones absolutas para el contenido. En pantallas bajas la página se desplaza con naturalidad, respetando las áreas seguras del dispositivo.
- El fondo de circuitos ya no ensancha la página en móvil.

## Comprobado

**Anchos probados:** 320, 375, 390, 430, 768, 1024, 1366 (768 y 900 de alto) y 1920 px, en español e inglés.
- Sin desbordes, cortes ni superposiciones.
- A partir de 1024×768 la tarjeta entera cabe en pantalla.

**Funciones probadas:**
- Inicio de sesión válido e inválido.
- Mostrar y ocultar contraseña, y recordar sesión.
- Recuperación de contraseña.
- Cambio de idioma.
- Apertura de la Agenda de Citas y de PQRS.
- Aviso legal desplegable con el teclado.
- Panel de versión: estado correcto, estado de error y historial.
- Movimiento reducido.

Pruebas: `tests/test_login_compact.py`.
