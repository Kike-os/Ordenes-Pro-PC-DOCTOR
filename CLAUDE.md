# Órdenes Pro | PC-DOCTOR S.A.

Trabaja y comunica resultados en español. Revisa el código existente antes de modificarlo.

## Proyecto

Aplicación local Python (HTTP/WSGI, SQLite) con JavaScript y CSS sin framework.
- Backend: `local/app.py`.
- Interfaz: `local/static/app.js`, `local/static/app.css`.
- Datos locales: `local/data/` (no usar como base de pruebas).
- Documentación: `README.md` y `docs/`.

## Reglas del proyecto

- Conservar colores, logo original, fondo tecnológico e identidad corporativa.
- Priorizar errores confirmados antes de añadir funciones. Acotar estilos a cada módulo.
- Preservar cuentas, sesiones, clientes, números de orden, historial, QR y comprobantes.
- Antes de migraciones o cambios estructurales, revisar dependencias y crear un respaldo.
- No inventar aceptación de condiciones ni autorizaciones históricas. Separar acceso técnico, archivos, respaldo y formateo.
- Mantener autenticación y permisos en backend, CSRF, consultas parametrizadas y errores de acceso genéricos. Nunca guardar contraseñas en el navegador ni imprimirlas.
- No leer ni mostrar secretos de `.env`, tokens o credenciales. No enviar datos reales a servicios externos sin autorización específica.
- Usar datos ficticios y una base temporal para pruebas. No enviar correos, imprimir físicamente ni desplegar cambios como parte de pruebas automáticas.
- Revisar `docs/TICKET-TERMICO.md` y `docs/CONDICIONES.md` antes de cambiar recepción o impresión. La publicación de condiciones exige una decisión administrativa real.

## Verificación

Desde la raíz:

```bash
python -m unittest discover -s local/tests
node --check local/static/app.js
python -m py_compile local/app.py
```

Para cambios visuales comprobar escritorio, tableta y móvil, incluyendo 320 y 390 px; teclado, foco, Escape, movimiento reducido y ausencia de desbordamiento. No afirmar que algo funciona sin verificarlo. Informar archivos modificados, pruebas y pendientes reales.
